"""Check the recipe data and synchronization of quantities and cooking steps."""

import itertools
import json
import unittest

from evaluation import DATA_DIR
from recipe_plans import load_recipes, make_plan, resolve_ingredients
from search import IngredientSearch


class RecipePlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))
        cls.search = IngredientSearch(
            cls.catalog["ingredients"], cls.catalog["relations"], cls.catalog["uses"],
        )
        cls.recipes = {recipe["id"]: recipe for recipe in load_recipes()}

    def test_all_configured_options_resolve_and_can_be_combined(self):
        for recipe in self.recipes.values():
            with self.subTest(recipe=recipe["id"]):
                rows = resolve_ingredients(recipe, self.catalog, self.search)
                self.assertTrue(set(recipe["sources"]) <= self.catalog["sources"].keys())
                self.assertTrue(all(row["sources"] for row in rows))
                for row in rows:
                    self.assertEqual(set(row["choices"]), {
                        choice["to"] for choice in row.get("alternatives", [])
                    })
                for targets in itertools.product(*[[None, *row["choices"]] for row in rows]):
                    selection = {row["id"]: target for row, target in zip(rows, targets) if target}
                    shopping, steps = make_plan(recipe, rows, selection)
                    self.assertEqual(sum(entry["substitute"] for entry in shopping), len(selection))
                    self.assertTrue(all("{" not in step for step in steps))

    def test_prepared_totopos_change_quantities_and_remove_the_oil(self):
        recipe = self.recipes["chilaquiles_verdes"]
        rows = resolve_ingredients(recipe, self.catalog, self.search)
        base, original_steps = make_plan(recipe, rows, {})
        updated, steps = make_plan(recipe, rows, {
            "tortilla_maiz": "totopos", "queso_fresco_mexicano": "feta",
        })
        self.assertEqual(base[0]["amount"], "12 piezas")
        self.assertIn("Hornéalos", original_steps[0])
        self.assertEqual(updated[0]["amount"], "200 g de totopos gruesos")
        self.assertEqual(len(updated), len(base) - 1)
        self.assertNotIn("Hornéalos", " ".join(steps))
        self.assertIn("feta suave", steps[-1])

    def test_rejected_option_cannot_change_recipe(self):
        recipe = self.recipes["rajas"]
        revised_relations = [
            {**rel, "human_review": "rejected"} if rel["use"] == "rajas" and rel["to"] == "morron" else rel
            for rel in self.catalog["relations"]
        ]
        search = IngredientSearch(self.catalog["ingredients"], revised_relations, self.catalog["uses"])
        rows = resolve_ingredients(recipe, self.catalog, search)
        shopping, steps = make_plan(recipe, rows, {"chile_poblano": "morron"})
        self.assertFalse(shopping[0]["substitute"])
        self.assertIn("poblanos", steps[0])
