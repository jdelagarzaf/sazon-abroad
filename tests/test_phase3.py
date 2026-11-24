"""Regression checks for context filtering and evaluation."""

import json
import unittest

from evaluation import DATA_DIR, evaluate, evaluate_final, load_cases
from search import IngredientSearch


class ContextSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))
        cls.engine = IngredientSearch(
            cls.catalog["ingredients"], cls.catalog["relations"], cls.catalog["uses"],
        )

    def test_context_disambiguates_two_uses_of_same_pair(self):
        lookup = self.engine.lookup("chile poblano para rajas con crema")
        ingredient = lookup.hits[0].ingredient["id"]
        self.assertEqual(ingredient, "chile_poblano")
        self.assertEqual(lookup.use, "rajas")
        relations = self.engine.relations_for(ingredient, lookup.use)
        self.assertEqual([(row["to"], row["use"]) for row in relations], [("morron", "rajas")])

    def test_unknown_qualifier_does_not_become_a_supported_use(self):
        lookup = self.engine.lookup("amido di mais per addensare senza glutine")
        self.assertEqual(lookup.hits[0].ingredient["id"], "fecula_maiz")
        self.assertIsNone(lookup.use)
        self.assertEqual(lookup.context, "addensare senza glutine")

    def test_warning_is_distinct_from_substitution(self):
        lookup = self.engine.lookup("masa harina para tortillas")
        relations = self.engine.relations_for(lookup.hits[0].ingredient["id"], lookup.use)
        self.assertEqual({row["type"] for row in relations}, {"not_equivalent"})
        self.assertEqual({row["to"] for row in relations}, {"harina_maiz", "polenta"})

    def test_oaxaca_is_a_distinct_ingredient_and_alternatives_depend_on_use(self):
        lookup = self.engine.lookup("quesillo para quesadillas")
        original = lookup.hits[0].ingredient
        self.assertEqual(original["id"], "queso_oaxaca")
        self.assertIsNone(original["name_it"])
        self.assertEqual(lookup.use, "quesadillas")
        relations = {row["to"]: row for row in self.engine.relations_for(original["id"], lookup.use)}
        self.assertEqual(relations.keys(), {"mozzarella", "scamorza"})
        self.assertTrue(relations["mozzarella"]["adaptation"])
        self.assertFalse(self.engine.relations_for(original["id"], "ensalada"))

    def test_tomatillo_gap_does_not_recommend_the_jitomate(self):
        lookup = self.engine.lookup("tomatillo para salsa verde")
        original = lookup.hits[0].ingredient
        self.assertEqual(original["id"], "tomatillo")
        self.assertEqual(lookup.use, "salsa_verde")
        self.assertIn(lookup.use, original["substitution_gaps"])
        relations = self.engine.relations_for(original["id"], lookup.use)
        self.assertEqual([(row["to"], row["type"]) for row in relations], [("jitomate", "not_equivalent")])

    def test_rejected_relations_are_hidden(self):
        relations = [
            {**row, "human_review": "rejected"} if row["use"] == "rajas" else row
            for row in self.catalog["relations"]
        ]
        engine = IngredientSearch(self.catalog["ingredients"], relations, self.catalog["uses"])
        self.assertFalse(engine.relations_for("chile_poblano", "rajas"))
        self.assertTrue(engine.relations_for("chile_poblano", "rellenar"))

    def test_benchmark_counts_and_metrics(self):
        cases = [case for case in load_cases() if case["query"] in {
            "harina maiz", "leche condensada sin azúcar", "masa harina para tortilla",
        }]
        result = evaluate(self.catalog, cases, self.engine)
        full = next(row for row in result["summary"] if row["method"] == "BM25 + contexto")
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["answerable"], 2)
        self.assertEqual(result["contextual"], 1)
        self.assertEqual(full["top1"], 1)
        self.assertEqual(full["recall_at_3"], 1)
        self.assertEqual(full["no_result"], 1)
        self.assertEqual(full["context"], 1)

    def test_quality_ignores_substitutions_without_human_review(self):
        pending = {"type": "culinary_substitute"}
        catalog = {**self.catalog, "relations": [pending]}
        self.assertIsNone(evaluate(catalog, [], self.engine)["accepted_share"])

        catalog["relations"].extend([
            {**pending, "human_review": "accepted"},
            {**pending, "human_review": "rejected"},
        ])
        result = evaluate(catalog, [], self.engine)
        self.assertEqual(result["human_reviewed"], 2)
        self.assertEqual(result["accepted_share"], 0.5)

    def test_final_benchmark_uses_the_same_cases_for_each_system(self):
        report = evaluate_final()
        self.assertEqual(report["count"], 36)
        self.assertEqual(report["contextual"], 18)
        expected = {row["query"] for row in report["details"]}
        for summary in report["summary"]:
            rows = [row for row in report["details"] if row["method"] == summary["method"]]
            self.assertEqual(len(rows), len(expected))
            self.assertEqual({row["query"] for row in rows}, expected)
        self.assertEqual(evaluate_final("habitual")["count"], 11)
        self.assertEqual(evaluate_final("especializado")["count"], 25)

    def test_adjustment_metric_distinguishes_missing_advice_from_missing_substitute(self):
        case = {
            "query": "elote tierno para esquites", "kind": "ajuste", "expected_ids": "elote_tierno",
            "expected_substitutes": "maiz_dulce", "expected_warnings": "", "expected_adjustments": "maiz_dulce",
        }
        relations = [
            {key: value for key, value in row.items() if key != "adaptation"}
            for row in self.catalog["relations"]
        ]
        engine = IngredientSearch(self.catalog["ingredients"], relations, self.catalog["uses"])
        report = evaluate(
            self.catalog, [case],
            systems={"Sin ajuste": (engine, "bm25"), "Con ajuste": (self.engine, "bm25")},
        )
        missing, correct = report["summary"]
        self.assertEqual(missing["missed_substitutes"], 0)
        self.assertEqual(missing["missed_adjustments"], 1)
        self.assertEqual(missing["adjustment_coverage"], 0)
        self.assertEqual(missing["context"], 0)
        self.assertEqual(correct["adjustment_coverage"], 1)
        self.assertEqual(correct["context"], 1)


if __name__ == "__main__":
    unittest.main()
