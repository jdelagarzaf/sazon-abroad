"""Protect essential instructions when explanations become collapsible."""

from html.parser import HTMLParser
import unittest
from unittest.mock import Mock, patch

from app import app
from ingredient_views import get_catalog, group_relation_cards
from recipe_plans import load_recipes


class DisclosureText(HTMLParser):
    """Classify text using native details/summary visibility, independent of CSS classes."""

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.disclosures = []
        self.text = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "details":
            self.disclosures.append({"open": "open" in dict(attrs), "summary": False})
        elif tag == "summary" and self.disclosures:
            self.disclosures[-1]["summary"] = True

    def handle_endtag(self, tag):
        if tag == "details":
            self.disclosures.pop()
        elif tag == "summary" and self.disclosures:
            self.disclosures[-1]["summary"] = False

    def handle_data(self, data):
        self.text.append((data, all(row["open"] or row["summary"] for row in self.disclosures)))

    def contains(self, text, *, visible):
        return any(text in value and exposed == visible for value, exposed in self.text)


class CompactViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog, cls.index = get_catalog()
        cls.mozzarella = next(row for row in cls.index.relations_for("queso_oaxaca", "quesadillas") if row["to"] == "mozzarella")

    def setUp(self):
        self.client = app.test_client()

    def test_search_keeps_full_adjustments_visible_and_reason_collapsed(self):
        page = self.client.get("/busqueda", query_string={"q": "quesillo para quesadillas"})
        self.assertEqual(page.status_code, 200)
        text = DisclosureText(page.get_data(as_text=True))
        self.assertTrue(text.contains(self.mozzarella["adaptation"], visible=True))
        self.assertTrue(text.contains(self.mozzarella["limitations"], visible=True))
        self.assertTrue(text.contains(self.mozzarella["reason"], visible=False))
        self.assertTrue(text.contains("Revisión pendiente", visible=True))
        starch = self.client.get("/busqueda", query_string={"q": "fécula de maíz para espesar"})
        self.assertTrue(DisclosureText(starch.get_data(as_text=True)).contains("Contiene gluten.", visible=True))

    def test_warnings_are_not_hidden_by_the_two_alternative_limit(self):
        warnings = self.index.relations_for("masa_harina", "tortillas") + self.index.relations_for("chipotle", "ahumado")
        self.assertEqual(len(warnings), 3)
        index = Mock(wraps=self.index)
        index.relations_for.return_value = warnings
        with patch("app.get_catalog", return_value=(self.catalog, index)):
            page = self.client.get("/busqueda", query_string={"q": "masa harina para tortillas"})
        self.assertEqual(page.status_code, 200)
        text = DisclosureText(page.get_data(as_text=True))
        for relation in warnings:
            self.assertTrue(text.contains(relation["limitations"], visible=True))

    def test_only_additional_substitutes_start_collapsed(self):
        # Use a third real product; this fixture tests presentation, not culinary ranking.
        third = next(row for row in self.index.relations_for("queso_cotija", "decorar") if row["to"] == "pecorino_romano")
        groups = [self.index.relations_for("chile_poblano", "rajas"), [self.mozzarella], [third]]
        with app.test_request_context():
            html = str(app.jinja_env.get_template("components.html").module.relation_list(groups, self.catalog["sources"], {}))
        text = DisclosureText(html)
        for group in groups[:2]:
            self.assertTrue(text.contains(group[0]["target_name_it"], visible=True))
        self.assertTrue(text.contains(groups[2][0]["target_name_it"], visible=False))
        self.assertTrue(text.contains("Ver 1 alternativa más", visible=True))

    def test_grouping_preserves_priority_and_separates_non_equivalence(self):
        poblano = self.index.relations_for("chile_poblano")
        warning = {**poblano[0], "type": "not_equivalent"}
        groups = group_relation_cards([poblano[0], self.mozzarella, poblano[1], warning])
        self.assertEqual(groups, [[poblano[0], poblano[1]], [self.mozzarella], [warning]])
        page = self.client.get("/catalogo", query_string={"ingredient": "chile_poblano"})
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertEqual(html.count(f'>{poblano[0]["target_name_it"]}</h3>'), 1)

    def test_selected_recipe_keeps_adjustments_outside_its_disclosure(self):
        recipe = next(recipe for recipe in load_recipes() if any(
            row["id"] == "queso_oaxaca" and any(choice["to"] == "mozzarella" for choice in row.get("alternatives", []))
            for row in recipe["ingredients"]
        ))
        page = self.client.get("/recetas", query_string={"recipe": recipe["id"], "choice_queso_oaxaca": "mozzarella"})
        self.assertEqual(page.status_code, 200)
        text = DisclosureText(page.get_data(as_text=True))
        self.assertTrue(text.contains(self.mozzarella["adaptation"], visible=True))
        self.assertTrue(text.contains(self.mozzarella["limitations"], visible=True))
        self.assertTrue(text.contains(self.mozzarella["reason"], visible=False))

    def test_ai_view_keeps_cautions_visible_and_collapses_explanations(self):
        result = {
            "original_name": "Queso Oaxaca", "local_name": None, "kind": "substitute",
            "culinary_use": "quesadillas", "summary": "Resumen generado de la adaptación.",
            "clarification": None, "warnings": ["Comprueba la presentación del producto."],
            "source_ids": [], "alternatives": [{
                "local_name": "Mozzarella", "reason": self.mozzarella["reason"],
                "adjustment": self.mozzarella["adaptation"], "limitation": self.mozzarella["limitations"],
                "source_ids": [],
            }],
        }
        response = {"result": result, "sources": {}, "model": "fixture", "elapsed_seconds": 1,
                    "cached": False, "name_only": False}
        with patch("app.adaptation_service.adapt", return_value=response):
            page = self.client.post("/adaptar", data={"query": "quesillo para quesadillas"})
        self.assertEqual(page.status_code, 200)
        text = DisclosureText(page.get_data(as_text=True))
        for content in [result["warnings"][0], self.mozzarella["adaptation"], self.mozzarella["limitations"],
                        "pendiente de verificación culinaria"]:
            self.assertTrue(text.contains(content, visible=True))
        for content in [result["summary"], self.mozzarella["reason"]]:
            self.assertTrue(text.contains(content, visible=False))


if __name__ == "__main__":
    unittest.main()
