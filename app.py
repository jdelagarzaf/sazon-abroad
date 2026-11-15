"""Flask routes for Sazón Abroad."""

from collections import defaultdict
from functools import lru_cache

from flask import Flask, render_template, request

from evaluation import DATA_DIR, evaluate, load_cases
from ingredient_views import CATALOG_PATH, EVIDENCE_LABELS, REFERENCE_LABELS, VERIFICATION_LABELS, get_catalog, load_photos
from recipe_plans import load_recipes, make_plan, resolve_ingredients
from search import METHODS, normalize

app = Flask(__name__)
app.jinja_env.globals.update(
    verification_labels=VERIFICATION_LABELS,
    reference_labels=REFERENCE_LABELS,
    evidence_labels=EVIDENCE_LABELS,
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
CASES_PATH = DATA_DIR / "evaluation.csv"


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
    return render_template(
        "find.html", query=query, lookup=lookup, matches=matches, selected=selected,
        context=context, sources=catalog["sources"], photos=load_photos(),
        substitutes=[cards for key, cards in groups.items() if key[0] == "culinary_substitute"],
        warnings=[cards for key, cards in groups.items() if key[0] == "not_equivalent"],
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
    return evaluate(catalog, load_cases(CASES_PATH), engine=index)


@app.get("/evaluacion")
def evaluation_page():
    catalog, _ = get_catalog()
    result = benchmark(CATALOG_PATH.stat().st_mtime_ns, CASES_PATH.stat().st_mtime_ns)
    metric = request.args.get("metric", "top1")
    if metric not in METRICS:
        metric = "top1"
    method = request.args.get("method", list(METHODS.values())[-1])
    if method not in METHODS.values():
        method = list(METHODS.values())[-1]
    kind = request.args.get("kind", "")
    errors = request.args.get("errors") == "1"
    rows = [
        row for row in result["details"]
        if row["method"] == method and (not kind or row["kind"] == kind)
        and (not errors or not row["correct"])
    ]
    counts = {
        "top1": result["answerable"], "recall_at_3": result["answerable"],
        "no_result": result["count"] - result["answerable"], "context": result["contextual"],
    }
    names = {item["id"]: item["name_es"] for item in catalog["ingredients"]}
    return render_template(
        "evaluation.html", result=result, rows=rows, names=names, counts=counts,
        metrics=METRICS, metric=metric, methods=METHODS.values(), method=method,
        kinds=KINDS, kind=kind, errors=errors,
    )


@app.errorhandler(500)
def server_error(error):
    return render_template("error.html"), 500
