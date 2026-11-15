"""Build shopping lists and steps from catalog-backed recipe ingredients."""

import json
from pathlib import Path
import re

RECIPES_PATH = Path(__file__).resolve().parent / "data" / "recipes.json"
STEP_INGREDIENT = re.compile(r"\{([a-z0-9_]+)\}")


def load_recipes(path=RECIPES_PATH):
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_ingredients(recipe, catalog, search_index):
    ingredients = {ingredient["id"]: ingredient for ingredient in catalog["ingredients"]}
    if len({row["id"] for row in recipe["ingredients"]}) != len(recipe["ingredients"]):
        raise ValueError(f"Ingrediente repetido en {recipe['title']}.")
    rows = []
    for row in recipe["ingredients"]:
        ingredient = ingredients[row["id"]]
        use = row.get("use")
        # Only show options with quantities and instructions checked for this recipe.
        available = {
            relation["to"]: relation for relation in search_index.relations_for(row["id"], use)
            if use and relation["type"] == "culinary_substitute"
        }
        alternatives = {
            choice["to"]: {**available[choice["to"]], "amount": choice["amount"]}
            for choice in row.get("alternatives", []) if choice["to"] in available
        }
        rows.append({
            **row,
            "name": row.get("label", ingredient["name_es"]),
            "italian": ingredient["name_it"] or ingredient["reference_it"],
            "sources": ingredient["sources"],
            "choices": alternatives,
        })
    return rows


def make_plan(recipe, rows, selection):
    """Return the selected shopping list and matching cooking steps."""
    active = {
        row["id"]: row["choices"][target]
        for row in rows
        if (target := selection.get(row["id"])) in row["choices"]
    }
    names = {}
    shopping = []
    for row in rows:
        ingredient_id = row["id"]
        alternative = active.get(ingredient_id)
        names[ingredient_id] = alternative["target_name_es"] if alternative else row["name"]
        omit = row.get("omit_with")
        if omit and active.get(omit["from"], {}).get("to") == omit["to"]:
            continue
        shopping.append({
            "original": row["name"],
            "original_amount": row["amount"],
            "italian": alternative["target_name_it"] if alternative else row["italian"],
            "amount": alternative["amount"] if alternative else row["amount"],
            "substitute": alternative is not None,
        })

    steps = []
    for step in recipe["steps"]:
        applicable = [
            change["text"] for change in step.get("changes", [])
            if active.get(change["from"], {}).get("to") == change["to"]
        ]
        if len(applicable) > 1:
            raise ValueError(f"Hay ajustes incompatibles en un paso de {recipe['title']}.")
        text = applicable[0] if applicable else step["text"]
        steps.append(STEP_INGREDIENT.sub(lambda match: names[match[1]].lower(), text))
    return shopping, steps
