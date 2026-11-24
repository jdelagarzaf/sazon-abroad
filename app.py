"""Flask routes for Sazón Abroad."""

from collections import defaultdict
from functools import lru_cache

from flask import Flask, render_template, request

from evaluation import DEVELOPMENT_PATH, FINAL_PATH, GROUPS, SNAPSHOT_PATH, evaluate, evaluate_final, load_cases
from ingredient_views import (
    CATALOG_PATH, EVIDENCE_LABELS, PROPERTY_LABELS, REFERENCE_LABELS, VERIFICATION_LABELS,
    get_catalog, load_photos,
)
from recipe_plans import load_recipes, make_plan, resolve_ingredients
from search import METHODS, normalize

app = Flask(__name__)
app.jinja_env.globals.update(
    verification_labels=VERIFICATION_LABELS,
    reference_labels=REFERENCE_LABELS,
    evidence_labels=EVIDENCE_LABELS,
    property_labels=PROPERTY_LABELS,
)

METRICS = {
    "top1": "Top-1 Accuracy",
    "recall_at_3": "Recall@3",
    "no_result": "Abstención correcta",
    "context": "Acierto contextual",
}
KINDS = {
    "exacta": "Nombre exacto",
    "alias": "Alias",
    "prefijo": "Prefijo",
    "errata": "Errata",
    "palabras": "Palabras reordenadas u omitidas",
    "contexto": "Uso culinario",
    "sin resultado": "Fuera del catálogo",
}
FINAL_METRICS = {
    **METRICS,
    "no_substitute": "Abstención contextual correcta",
    "adjustment_coverage": "Cobertura de ajustes",
}
FINAL_KINDS = {
    "identidad": "Identidad",
    "contexto": "Sustitución por uso",
    "ajuste": "Sustitución con ajustes",
    "sin sustituto": "Sin sustituto apropiado",
    "sin resultado": "Fuera del catálogo",
}


@app.get("/")
def home():
    try:
        recipes = load_recipes()
    except (OSError, ValueError):
        app.logger.exception("No se pudieron cargar las recetas para Inicio")
        recipes = []
    return render_template("home.html", recipes=recipes)


@app.get("/busqueda")
def find():
    query = request.args.get("q", "")[:160].strip()
    if not query:
        return render_template("find.html", query=query)
    catalog, index = get_catalog()
    lookup = index.lookup(query)
    matches = {hit.ingredient["id"]: hit.ingredient for hit in lookup.hits}
    selected = request.args.get("ingredient")
    if selected not in matches:
        selected = next(iter(matches), None)
    groups = defaultdict(list)
    if selected and (not lookup.context or lookup.use):
        for relation in index.relations_for(selected, lookup.use):
            key = (relation["type"], relation["to"], relation["target_name_it"], relation["target_name_es"])
            groups[key].append(relation)
    context = catalog["uses"][lookup.use]["label"] if lookup.use else lookup.context
    gaps = matches.get(selected, {}).get("substitution_gaps", {})
    gaps = [
        (catalog["uses"][use]["label"], gap) for use, gap in gaps.items()
        if not lookup.context or lookup.use == use
    ]
    return render_template(
        "find.html", query=query, lookup=lookup, matches=matches, selected=selected,
        context=context, sources=catalog["sources"], photos=load_photos(),
        substitutes=[cards for key, cards in groups.items() if key[0] == "culinary_substitute"],
        warnings=[cards for key, cards in groups.items() if key[0] == "not_equivalent"],
        gaps=gaps,
    )


@app.get("/catalogo")
def catalog_page():
    catalog, index = get_catalog()
    ingredients = [item for item in catalog["ingredients"] if item["scope"] == "México"]
    categories = sorted({item["category"] for item in ingredients})
    statuses = [status for status in VERIFICATION_LABELS if any(item["verification"] == status for item in ingredients)]
    category = request.args.get("category", "")
    status = request.args.get("status", "")
    options = sorted(
        (item for item in ingredients
         if (not category or item["category"] == category) and (not status or item["verification"] == status)),
        key=lambda item: normalize(item["name_es"]),
    )
    selected = next((item for item in options if item["id"] == request.args.get("ingredient")), None)
    return render_template(
        "catalog.html", options=options, selected=selected, categories=categories, statuses=statuses,
        category=category, status=status, total=len(ingredients), sources=catalog["sources"],
        uses=catalog["uses"],
        relations=index.relations_for(selected["id"]) if selected else [],
    )


@app.get("/recetas")
def recipes_page():
    recipes = {recipe["id"]: recipe for recipe in load_recipes()}
    recipe = recipes.get(request.args.get("recipe"), next(iter(recipes.values()), None))
    if recipe is None:
        return render_template("recipes.html", recipes=recipes, recipe=None)
    catalog, index = get_catalog()
    rows = resolve_ingredients(recipe, catalog, index)
    italy = request.args.get("version") != "original"
    selection = {}
    if italy:
        for row in rows:
            target = request.args.get(f"choice_{row['id']}")
            if target in row["choices"]:
                selection[row["id"]] = target
    shopping, steps = make_plan(recipe, rows, selection)
    omitted = sorted({row["name"] for row in rows} - {entry["original"] for entry in shopping})
    return render_template(
        "recipes.html", recipes=recipes, recipe=recipe, italy=italy, rows=rows,
        selection=selection, shopping=shopping, steps=steps, omitted=omitted, sources=catalog["sources"],
    )


@lru_cache(maxsize=1)
def benchmark(catalog_revision, cases_revision):
    catalog, index = get_catalog()
    return evaluate(catalog, load_cases(), engine=index)


@lru_cache(maxsize=len(GROUPS) + 1)
def final_benchmark(snapshot_revision, cases_revision, development_revision, group):
    return evaluate_final(group)


@app.get("/evaluacion")
def evaluation_page():
    final = request.args.get("dataset") != "desarrollo"
    group = request.args.get("group", "")
    if not final or group not in GROUPS:
        group = ""
    development_revision = DEVELOPMENT_PATH.stat().st_mtime_ns
    if final:
        result = final_benchmark(
            SNAPSHOT_PATH.stat().st_mtime_ns, FINAL_PATH.stat().st_mtime_ns, development_revision, group,
        )
        metrics, kinds = FINAL_METRICS, FINAL_KINDS
        methods = [row["method"] for row in result["summary"]]
        names, sources = result["names"], result["sources"]
    else:
        catalog, _ = get_catalog()
        result = benchmark(CATALOG_PATH.stat().st_mtime_ns, development_revision)
        metrics, kinds = METRICS, KINDS
        methods = list(METHODS.values())
        names = {item["id"]: item["name_es"] for item in catalog["ingredients"]}
        sources = {}
    metric = request.args.get("metric", "top1")
    if metric not in metrics:
        metric = "top1"
    method = request.args.get("method")
    if method not in methods:
        method = methods[-1]
    kind = request.args.get("kind", "")
    if kind not in kinds:
        kind = ""
    errors = request.args.get("errors") == "1"
    rows = [
        row for row in result["details"]
        if row["method"] == method and (not kind or row["kind"] == kind)
        and (not errors or not row["correct"])
    ]
    counts = {
        "top1": result["answerable"], "recall_at_3": result["answerable"],
        "no_result": result["count"] - result["answerable"], "context": result["contextual"],
        "no_substitute": result["contextual_abstentions"],
        "adjustment_coverage": result["required_adjustments"],
    }
    return render_template(
        "evaluation.html", result=result, rows=rows, names=names, sources=sources, counts=counts,
        metrics=metrics, metric=metric, methods=methods, method=method, kinds=kinds, kind=kind,
        errors=errors, final=final, groups=GROUPS, group=group,
    )


@app.errorhandler(500)
def server_error(error):
    return render_template("error.html"), 500
