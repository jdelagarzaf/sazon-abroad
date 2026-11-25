"""Recipe workspace routes. Local drafts are scoped to the browser session."""
from copy import deepcopy
from dataclasses import asdict
import hmac
import os
from pathlib import Path
import secrets

from flask import Blueprint, abort, current_app, redirect, render_template, request, session, url_for

from adaptation import AdaptationRequest
from ingredient_views import get_catalog
from local_model import ModelError, ModelSettings, OllamaClient
from recipe_plans import load_recipes, make_plan, resolve_ingredients
from recipe_workspace import DraftStore, LocalJobs, MAX_ROWS, extract_recipe, shopping_list, translate_draft
from store_search import StoreSearchError, StoreSearchService, TavilySearch, group_stores, manual_search

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
    if request.method == "POST":
        check_csrf()
        try:
            if request.form.get("revision") != str(draft["revision"]):
                raise ValueError("La receta cambió. Recarga antes de guardar.")
            if draft["status"] == "working":
                raise ValueError("Espera a que termine la tarea antes de editar.")
            action = request.form.get("action", "save")
            if action in {"save", "translate", "add", "remove"}:
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
                    from uuid import uuid4
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
                database_path = current_app.config.get("SEARCH_DB")
                def search(data, progress):
                    results, errors = [], []
                    search_service = StoreSearchService(database_path)
                    for name in names:
                        progress("Buscando comercios: " + name)
                        try:
                            results.append(search_service.search(name, data["context"]["city"], data["context"]["destination_country"], data["context"]["target_language"]))
                        except StoreSearchError as exc:
                            errors.append({"product": name, "message": str(exc)})
                            if "TAVILY_API_KEY" in str(exc) or "cuota" in str(exc) or "diario" in str(exc):
                                break
                    data["stores"] = {"searches": results, "errors": errors, "requested": names}
                    return data
                start_job(draft, search, kind="search")
            else:
                raise ValueError("Acción desconocida.")
            return redirect(url_for("workspace.edit", draft_id=draft_id), code=303)
        except (ValueError, ModelError) as exc:
            error = str(exc)
            draft = get_draft(draft_id)
    shopping = shopping_list(draft)
    products = list(dict.fromkeys(item["name"] for item in shopping))
    searches = (draft.get("stores") or {}).get("searches", [])
    return render_template("recipe_workspace.html", draft=draft, shopping=shopping, error=error,
                           store_groups=group_stores(searches, len(shopping)), searches=searches,
                           search_products=products,
                           manual_search=manual_search, search_configured=TavilySearch().api_key not in {"", "PEGA_TU_CLAVE_AQUI"}), 400 if error else 200


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
