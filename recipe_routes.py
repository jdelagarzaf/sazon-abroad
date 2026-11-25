"""Recipe workspace routes. Local drafts are scoped to the browser session."""
from copy import deepcopy
from dataclasses import asdict
import hmac
import os
from pathlib import Path
import secrets
from uuid import uuid4

from flask import Blueprint, abort, current_app, redirect, render_template, request, session, url_for

from adaptation import AdaptationRequest
from ingredient_views import get_catalog
from local_model import ModelError, ModelSettings, OllamaClient
from recipe_plans import load_recipes, make_plan, resolve_ingredients
from recipe_workspace import DraftStore, LocalJobs, MAX_ROWS, extract_recipe, shopping_list, translate_draft, propose_draft
from store_search import StoreSearchError, StoreSearchService, TavilySearch, manual_search
from retailers import DEFAULT_PREFERENCES, commercial_result, retailer_options, resolve_retailers
from shopping_plan import product_key, purchase_plan

workspace = Blueprint("workspace", __name__)
jobs = LocalJobs()


def session_key():
    configured = os.environ.get("SAZON_SESSION_SECRET")
    if configured:
        return configured
    path = Path(__file__).resolve().parent / ".runtime" / "session-secret"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_text(encoding="ascii")
    with os.fdopen(fd, "w", encoding="ascii") as handle:
        value = secrets.token_hex(32)
        handle.write(value)
    return value


def owner():
    if "recipe_owner" not in session:
        session["recipe_owner"] = secrets.token_hex(24)
    return session["recipe_owner"]


def csrf_token():
    if "recipe_csrf" not in session:
        session["recipe_csrf"] = secrets.token_hex(24)
    return session["recipe_csrf"]


def check_csrf():
    if not hmac.compare_digest(session.get("recipe_csrf", "!"), request.form.get("csrf", "")):
        abort(400, "El formulario caducó. Recarga la página e intenta otra vez.")


def store():
    return DraftStore(current_app.config.get("RECIPE_DB"))


def get_draft(draft_id):
    draft = store().get(owner(), draft_id)
    if not draft:
        abort(404)
    if draft["status"] == "working" and draft.get("job_instance") != jobs.instance:
        revision = draft["revision"]
        draft.update(status="editable", error="La tarea se interrumpió al reiniciar. Puedes reintentar; se conserva la receta.")
        draft = store().save(owner(), draft, revision)
    return draft


def start_job(draft, function, kind="model"):
    database, identity = store(), owner()
    revision = draft["revision"]
    draft.update(status="working", error=None, progress="En espera…", job_instance=jobs.instance, job_kind=kind)
    draft = database.save(identity, draft, revision)
    def run():
        current = draft
        def progress(message):
            current["progress"] = message
            saved = database.save(identity, current, current["revision"])
            current["revision"] = saved["revision"]
        try:
            result = function(current, progress)
            # Progress saves advance the revision while result carries the same edits.
            result["revision"] = current["revision"]
            result.update(status="ready", progress="", error=None)
            database.save(identity, result, current["revision"])
        except Exception as exc:
            current.update(status="editable", progress="", error=str(exc) if isinstance(exc, (ModelError, ValueError, StoreSearchError)) else
                           "No se pudo completar la tarea. Se conserva la receta para volver a intentar.")
            database.save(identity, current, current["revision"])
    try:
        jobs.submit(run)
    except ValueError:
        draft.update(status="editable", progress="")
        database.save(identity, draft, draft["revision"])
        raise


def bounded(value, limit, label, required=False):
    value = value.strip()
    if len(value) > limit or (required and not value):
        raise ValueError(f"Revisa {label}: {'obligatorio, ' if required else ''}máximo {limit} caracteres.")
    return value


def invalidate_row(row):
    for key in ("translation", "adaptation", "selected_name", "selected_amount", "selected_index", "manual",
                "import_note", "import_adjustment", "import_limitation"):
        row.pop(key, None)
    row.update(local_name="", imported=False)


def edit_row(row, form):
    """Save one modal atomically, validating the selected option against its saved proposals."""
    previous = (row["name"], row.get("use", ""), row.get("preparation", ""))
    previous_local = row.get("local_name", "")
    previous_amount = row.get("amount", "")
    for key, limit in (("name", 160), ("amount", 100), ("use", 160), ("preparation", 160)):
        row[key] = bounded(form.get(key, row.get(key, "")), limit, key, key == "name")
    local = bounded(form.get("local_name", previous_local), 120, "término local")
    changed = previous != (row["name"], row["use"], row["preparation"])
    if row["amount"] != previous_amount:
        row.pop("import_note", None)
    if changed:
        invalidate_row(row)
        # Only retain a term explicitly corrected alongside the changed source.
        if local == previous_local:
            local = ""
    if local != row.get("local_name", ""):
        row["translation"] = None
        row["manual"] = bool(local)
    row["local_name"] = local
    choice = form.get("proposal", "original")
    alternatives = row.get("adaptation", {}).get("result", {}).get("alternatives", [])
    for key in ("selected_name", "selected_index", "selected_amount"):
        row.pop(key, None)
    if choice != "original" and not changed:
        allowed = {f"alternative:{i}": i for i in range(len(alternatives))}
        if choice not in allowed:
            raise ValueError("Esa propuesta ya no está disponible. Genera nuevas opciones.")
        selected = allowed[choice]
        row.update(selected_index=selected, selected_name=alternatives[selected]["local_name"],
                   selected_amount=bounded(form.get("sub_amount", ""), 100, "cantidad del sustituto"))


@workspace.route("/mi-receta/nueva", methods=["GET", "POST"])
def new():
    error, raw = None, ""
    if request.method == "POST":
        check_csrf()
        raw = request.form.get("raw", "")
        try:
            draft = extract_recipe(raw)
            draft["title"] = bounded(request.form.get("title", "") or draft["title"], 120, "título", True)
            if draft["title"] != "Mi receta":
                for row in draft["rows"]:
                    row["use"] = draft["title"][:160]
            draft = store().create(owner(), draft)
            return redirect(url_for("workspace.edit", draft_id=draft["id"]), code=303)
        except ValueError as exc:
            error = str(exc)
    return render_template("recipe_new.html", error=error, raw=raw, drafts=store().list(owner())), 400 if error else 200


@workspace.get("/ayuda/comercios")
def search_help():
    return render_template("store_help.html")


@workspace.post("/mi-receta/importar")
def import_recipe():
    check_csrf()
    recipe = next((item for item in load_recipes() if item["id"] == request.form.get("recipe")), None)
    if not recipe:
        abort(404)
    catalog, index = get_catalog()
    rows = resolve_ingredients(recipe, catalog, index)
    selection = {row["id"]: request.form.get(f"choice_{row['id']}") for row in rows}
    shopping, steps = make_plan(recipe, rows, selection)
    draft = extract_recipe("Ingredientes\n" + "\n".join(item["original"] for item in shopping))
    draft.update(title=recipe["title"], steps=steps, source_recipe=recipe["id"], status="ready")
    for row, item in zip(draft["rows"], shopping):
        row.update(amount=item["amount"], local_name=item["italian"] or "", imported=True, use=recipe["title"][:160])
        if item["substitute"]:
            row["name"] = item["italian"]
            original = next(r for r in rows if r["name"] == item["original"])
            row["import_origin"] = {"name": item["original"], "amount": original["amount"]}
            row["import_note"] = f"Sustituye {item['original']} ({original['amount']}); cantidad documentada para esta versión."
            relation = original["choices"][selection[original["id"]]]
            row["import_adjustment"] = relation.get("adaptation", "")
            row["import_limitation"] = relation.get("limitations", "")
    draft = store().create(owner(), draft)
    return redirect(url_for("workspace.edit", draft_id=draft["id"]), code=303)


@workspace.route("/mi-receta/<draft_id>", methods=["GET", "POST"])
def edit(draft_id):
    draft, error = get_draft(draft_id), None
    dialog_id = request.args.get("edit", "")
    modal_values = None
    created_row_id = None
    if request.method == "POST":
        check_csrf()
        try:
            if request.form.get("revision") != str(draft["revision"]):
                raise ValueError("La receta cambió. Recarga antes de guardar.")
            if draft["status"] == "working":
                raise ValueError("Espera a que termine la tarea antes de editar.")
            action = request.form.get("action", "save")
            if action in {"settings", "row_save", "row_add", "row_add_generate", "row_generate", "row_remove", "generate", "steps"}:
                updated = deepcopy(draft)
                row_id = request.form.get("row", "")
                if action == "settings":
                    updated["title"] = bounded(request.form.get("title", ""), 120, "título", True)
                    new_context = asdict(AdaptationRequest.from_mapping({**draft["context"],
                        **{key: request.form.get(key, value) for key, value in draft["context"].items()}, "query": "receta"}))
                    new_context["query"] = ""
                    if any(value != draft["context"].get(key) for key, value in new_context.items() if key != "city"):
                        for row in updated["rows"]:
                            invalidate_row(row)
                    updated["context"] = new_context
                elif action == "steps":
                    updated["steps"] = bounded(request.form.get("steps", ""), 6000, "pasos").splitlines()
                elif action in {"row_add", "row_add_generate"}:
                    if len(updated["rows"]) >= MAX_ROWS:
                        raise ValueError("El máximo es 16 ingredientes.")
                    row = {"id": uuid4().hex[:12], "name": "", "amount": "", "use": "", "preparation": ""}
                    edit_row(row, request.form)
                    updated["rows"].append(row)
                    row_id = row["id"]
                elif action in {"row_save", "row_generate", "row_remove"}:
                    row = next((row for row in updated["rows"] if row["id"] == row_id), None)
                    if not row:
                        raise ValueError("Ingrediente desconocido.")
                    if action == "row_remove":
                        if len(updated["rows"]) == 1:
                            raise ValueError("Conserva al menos un ingrediente.")
                        updated["rows"].remove(row)
                    else:
                        edit_row(row, request.form)
                updated.update(stores=None, error=None, status="editable")
                draft = store().save(owner(), updated, draft["revision"])
                if action == "row_add_generate":
                    created_row_id = row_id
                if action in {"generate", "row_generate", "row_add_generate"}:
                    catalog, index = get_catalog()
                    service, client = current_app.extensions["adaptation_service"], OllamaClient(ModelSettings.from_env())
                    targets = {row_id} if action != "generate" else None
                    start_job(draft, lambda data, progress: propose_draft(data, service, catalog, index, client, progress, targets))
                    if action != "generate":
                        return redirect(url_for("workspace.edit", draft_id=draft_id, edit=row_id), code=303)
            elif action in {"save", "translate", "add", "remove"}:
                updated = deepcopy(draft)
                updated["title"] = bounded(request.form.get("title", draft["title"]), 120, "título", True)
                context = AdaptationRequest.from_mapping({**draft["context"], **{key: request.form.get(key, value) for key, value in draft["context"].items()}, "query": "receta"})
                new_context = asdict(context)
                new_context["query"] = ""
                context_changed = any(value != draft["context"].get(key) for key, value in new_context.items() if key != "city")
                updated["context"] = new_context
                updated["steps"] = bounded(request.form.get("steps", "\n".join(draft["steps"])), 6000, "pasos").splitlines()
                for row in updated["rows"]:
                    before = (row["name"], row["amount"], row.get("use", ""), row.get("preparation", ""))
                    for key, limit in (("name", 160), ("amount", 100), ("use", 160), ("preparation", 160)):
                        row[key] = bounded(request.form.get(f"{key}_{row['id']}", row.get(key, "")), limit, key, key == "name")
                    local = bounded(request.form.get(f"local_{row['id']}", row.get("local_name", "")), 120, "nombre local")
                    changed = before != (row["name"], row["amount"], row["use"], row["preparation"]) or context_changed
                    if changed:
                        for key in ("translation", "adaptation", "selected_name", "selected_amount", "selected_index", "manual", "import_note", "import_adjustment", "import_limitation"):
                            row.pop(key, None)
                        row["imported"] = False
                        row["local_name"] = ""
                    else:
                        if local != row.get("local_name", ""):
                            row["translation"] = None
                            row["manual"] = True
                        row["local_name"] = local
                if action == "add":
                    if len(updated["rows"]) >= MAX_ROWS:
                        raise ValueError("El máximo es 16 ingredientes.")
                    updated["rows"].append({"id": uuid4().hex[:12], "name": "Nuevo ingrediente", "amount": "", "use": "", "preparation": ""})
                if action == "remove":
                    updated["rows"] = [row for row in updated["rows"] if row["id"] != request.form.get("row")]
                    if not updated["rows"]:
                        raise ValueError("Conserva al menos un ingrediente.")
                updated.update(stores=None, error=None, status="editable")
                draft = store().save(owner(), updated, draft["revision"])
                if action == "translate":
                    catalog, index = get_catalog()
                    service = current_app.extensions["adaptation_service"]
                    client = OllamaClient(ModelSettings.from_env())
                    start_job(draft, lambda data, progress: translate_draft(data, service, catalog, index, client, progress))
            elif action == "alternative":
                row_id = request.form.get("row")
                row = next((row for row in draft["rows"] if row["id"] == row_id), None)
                if not row or not row.get("use"):
                    raise ValueError("Guarda un uso o platillo para este ingrediente antes de pedir alternativas.")
                catalog, index = get_catalog()
                service, client = current_app.extensions["adaptation_service"], OllamaClient(ModelSettings.from_env())
                def generate(data, progress):
                    target = next(row for row in data["rows"] if row["id"] == row_id)
                    progress("Buscando una alternativa para " + target["name"])
                    target["adaptation"] = service.adapt(AdaptationRequest.from_mapping({**data["context"], "query": target["name"],
                        "culinary_use": target["use"], "preparation": target.get("preparation", "")}), catalog, index, client)
                    return data
                start_job(draft, generate)
            elif action == "choose":
                row = next((row for row in draft["rows"] if row["id"] == request.form.get("row")), None)
                if not row:
                    raise ValueError("Ingrediente desconocido.")
                selected = request.form.get("alternative", "")
                for key in ("selected_name", "selected_amount", "selected_index"):
                    row.pop(key, None)
                if selected:
                    alternatives = row.get("adaptation", {}).get("result", {}).get("alternatives", [])
                    if selected not in {str(number) for number in range(len(alternatives))}:
                        raise ValueError("Alternativa desconocida.")
                    row.update(selected_name=alternatives[int(selected)]["local_name"], selected_index=int(selected),
                               selected_amount=bounded(request.form.get("sub_amount", ""), 100, "cantidad del sustituto"))
                draft["stores"] = None
                draft = store().save(owner(), draft, draft["revision"])
            elif action == "stores":
                products = shopping_list(draft)
                chosen = request.form.getlist("products")
                names = list(dict.fromkeys(item["name"] for item in products if item["name"] in chosen))
                if not 1 <= len(names) <= 8:
                    raise ValueError("Elige entre 1 y 8 productos para buscar.")
                if not draft["context"]["city"]:
                    raise ValueError("Guarda una ciudad antes de buscar comercios.")
                available = retailer_options(draft["context"]["destination_country"])
                saved_preferences = draft.get("store_preferences", {})
                preferred_ids = request.form.getlist("retailers") if "preferences_form" in request.form else saved_preferences.get("ids", [row["id"] for row in available if row["id"] in DEFAULT_PREFERENCES])
                custom = bounded(request.form.get("custom_retailers", saved_preferences.get("custom", "")), 400, "dominios de comercios")
                preferred = resolve_retailers(draft["context"]["destination_country"], preferred_ids, custom)
                allow_other = request.form.get("allow_other") == "1" if "preferences_form" in request.form else saved_preferences.get("allow_other", True)
                additional = [row for row in available if row["id"] not in {store["id"] for store in preferred}]
                draft["store_preferences"] = {"ids": preferred_ids, "custom": custom, "allow_other": allow_other}
                draft["store_assignments"] = {}
                draft["stores"] = {"searches": [], "errors": [], "requested": names, "preferred": [row["id"] for row in preferred]}
                database_path = current_app.config.get("SEARCH_DB")
                def search(data, progress):
                    results, errors = [], []
                    search_service = StoreSearchService(database_path)
                    for name in names:
                        progress("Buscando comercios: " + name)
                        try:
                            def lookup(retailers):
                                domains = sorted({domain for store in retailers for domain in store["domains"]})
                                raw = search_service.search(name, data["context"]["city"], data["context"]["destination_country"], data["context"]["target_language"], domains=domains)
                                accepted = [hit for candidate in raw["results"] if (hit := commercial_result(candidate, name, retailers))]
                                return {**raw, "results": accepted, "discarded": len(raw["results"]) - len(accepted), "domains": domains}
                            primary = lookup(preferred)
                            primary["queries"] = [{key: value for key, value in primary.items() if key != "results"}]
                            results.append(primary)
                            if not primary["results"] and allow_other and additional:
                                extra = lookup(additional)
                                primary["results"] = extra["results"]
                                primary["queries"].append({key: value for key, value in extra.items() if key != "results"})
                                primary["cached"] = primary["cached"] and extra["cached"]
                                primary["queried_at"] = extra["queried_at"]
                                primary["discarded"] += extra["discarded"]
                        except StoreSearchError as exc:
                            errors.append({"product": name, "message": str(exc)})
                            if "TAVILY_API_KEY" in str(exc) or "clave" in str(exc).lower() or "cuota" in str(exc) or "diario" in str(exc):
                                break
                    data["stores"] = {"searches": results, "errors": errors, "requested": names, "preferred": [row["id"] for row in preferred]}
                    return data
                start_job(draft, search, kind="search")
            elif action in {"store_plan", "reset_store_plan"}:
                available = configured_retailers(draft)
                stored = draft.get("stores")
                if not stored:
                    raise ValueError("Busca primero los productos para poder distribuir la compra.")
                pins = {name: value for name in stored["requested"] if (value := request.form.get("pin_" + product_key(name), ""))} if action == "store_plan" else {}
                purchase_plan(shopping_list(draft), stored, available, pins)
                draft["store_assignments"] = pins
                draft = store().save(owner(), draft, draft["revision"])
            else:
                raise ValueError("Acción desconocida.")
            return redirect(url_for("workspace.edit", draft_id=draft_id), code=303)
        except (ValueError, ModelError) as exc:
            error = str(exc)
            draft = get_draft(draft_id)
            action = request.form.get("action")
            dialog_id = "settings" if action == "settings" else "new" if action in {"row_add", "row_add_generate"} else "steps" if action == "steps" else request.form.get("row", "") if action in {"row_save", "row_generate"} else ""
            if created_row_id:
                dialog_id = created_row_id
                error = "El ingrediente se guardó, pero no se pudo generar: " + error
            modal_values = request.form if dialog_id else None
    shopping = shopping_list(draft)
    products = list(dict.fromkeys(item["name"] for item in shopping))
    searches = (draft.get("stores") or {}).get("searches", [])
    retailers = configured_retailers(draft)
    plan = purchase_plan(shopping, draft.get("stores"), retailers, draft.get("store_assignments", {}) if draft.get("stores") else {})
    preferences = draft.get("store_preferences", {"ids": [row["id"] for row in retailer_options(draft["context"]["destination_country"]) if row["id"] in DEFAULT_PREFERENCES], "custom": "", "allow_other": True})
    search_selection = None
    if error and request.form.get("action") == "stores" and "preferences_form" in request.form:
        preferences = {"ids": request.form.getlist("retailers"), "custom": request.form.get("custom_retailers", ""), "allow_other": request.form.get("allow_other") == "1"}
        search_selection = request.form.getlist("products")
    return render_template("recipe_workspace.html", draft=draft, shopping=shopping, error=error,
                           searches=searches,
                           search_products=products,
                           dialog_id=dialog_id, modal_values=modal_values,
                           retailers=retailers, retailer_options=retailer_options(draft["context"]["destination_country"]), store_preferences=preferences,
                           purchase_plan=plan, product_key=product_key,
                           search_selection=search_selection,
                           manual_search=manual_search, search_configured=TavilySearch().api_key not in {"", "PEGA_TU_CLAVE_AQUI"}), 400 if error else 200


def configured_retailers(draft):
    available = retailer_options(draft["context"]["destination_country"])
    custom = draft.get("store_preferences", {}).get("custom", "")
    if custom:
        return resolve_retailers(draft["context"]["destination_country"], [row["id"] for row in available], custom)
    return available


@workspace.get("/mi-receta/<draft_id>/estado")
def status(draft_id):
    draft = get_draft(draft_id)
    return {"status": draft["status"], "progress": draft["progress"], "revision": draft["revision"]}, {"Cache-Control": "no-store"}


@workspace.post("/mi-receta/<draft_id>/borrar")
def delete(draft_id):
    check_csrf()
    draft = get_draft(draft_id)
    if draft["status"] == "working":
        abort(409, "Espera a que termine la tarea antes de borrar.")
    with store().connect() as db:
        db.execute("DELETE FROM drafts WHERE id=? AND owner=?", (draft_id, owner()))
    return redirect(url_for("workspace.new"), code=303)
