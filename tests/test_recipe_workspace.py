from copy import deepcopy
import re
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import app
from adaptation import AdaptationService
from local_model import ModelError, ModelSettings
from recipe_workspace import DraftStore, extract_recipe, quantity, shopping_list


class RecipeDataTests(unittest.TestCase):
    def test_exact_units_and_traceability(self):
        draft = extract_recipe("Ingredientes\n250 g de lenteja\n1/2 kg de lenteja\n1 taza de lenteja\nSal al gusto\nPreparación\nCuece todo.")
        for row in draft["rows"]:
            row["local_name"] = row["name"]
        shopping = shopping_list(draft)
        self.assertEqual(shopping[0]["amount"], "750 g")
        self.assertEqual(len(shopping[0]["rows"]), 2)
        self.assertEqual(shopping[1]["amount"], "1 taza")
        self.assertEqual(shopping[2]["amount"], "al gusto")
        self.assertEqual(draft["steps"], ["Cuece todo."])

    def test_counts_qualifiers_and_preparations_do_not_merge(self):
        draft = extract_recipe("2 huevos\n1 huevo\n100 g de apio\n200 g de apio")
        self.assertEqual(draft["rows"][0]["name"], "huevos")
        for row in draft["rows"]:
            row["local_name"] = "apio"
        draft["rows"][-1]["preparation"] = "seco"
        self.assertEqual(len(shopping_list(draft)), 4)
        self.assertIsNone(quantity("1 taza colmada"))
        self.assertEqual(quantity("1 1/2 kg"), (1500, "g"))
        self.assertEqual(quantity("½ l"), (500, "ml"))
        self.assertIsNone(quantity("1/0 kg"))

    def test_substitution_does_not_copy_quantity(self):
        draft = extract_recipe("200 g de panela")
        draft["rows"][0].update(local_name="panela", selected_name="halloumi", selected_amount="")
        self.assertEqual(shopping_list(draft)[0]["amount"], "Por confirmar")
        self.assertEqual(draft["rows"][0]["amount"], "200 g")

    def test_extraction_limits_and_original(self):
        for text in ("", "x" * 6001, "\n".join(["apio"] * 17)):
            with self.assertRaises(ValueError):
                extract_recipe(text)
        draft = extract_recipe("Mi sopa\nIngredientes\n200 g de colinabo\nPreparación\nCuece.")
        self.assertEqual(draft["title"], "Mi sopa")
        self.assertEqual(draft["rows"][0]["amount"], "200 g")
        self.assertIn("colinabo", draft["raw"])

    def test_storage_owner_and_stale_write(self):
        with tempfile.TemporaryDirectory() as directory:
            store = DraftStore(Path(directory) / "drafts.sqlite")
            draft = store.create("one", extract_recipe("apio"))
            self.assertIsNone(store.get("two", draft["id"]))
            store.save("one", draft, 0)
            with self.assertRaises(ValueError):
                store.save("one", draft, 0)


class RecipeRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        app.config.update(TESTING=True, RECIPE_DB=str(Path(self.temp.name) / "recipes.sqlite"),
                          SEARCH_DB=str(Path(self.temp.name) / "search.sqlite"))
        self.previous_service = app.extensions["adaptation_service"]
        app.extensions["adaptation_service"] = AdaptationService()
        self.client = app.test_client()
        self.client.get("/mi-receta/nueva")
        with self.client.session_transaction() as session:
            self.csrf, self.owner = session["recipe_csrf"], session.get("recipe_owner")

    def tearDown(self):
        app.extensions["adaptation_service"] = self.previous_service
        app.config.pop("RECIPE_DB", None)
        app.config.pop("SEARCH_DB", None)
        self.temp.cleanup()

    def create(self):
        response = self.client.post("/mi-receta/nueva", data={"csrf": self.csrf, "raw": "Ingredientes\n200 g de colinabo\nPreparación\nCuece el colinabo."})
        self.assertEqual(response.status_code, 303)
        self.url = response.location
        self.id = self.url.rsplit("/", 1)[1]
        with self.client.session_transaction() as session:
            self.owner = session["recipe_owner"]
        return self.get()

    def get(self):
        return DraftStore(app.config["RECIPE_DB"]).get(self.owner, self.id)

    def test_csrf_owner_and_editable_extraction(self):
        self.assertEqual(self.client.post("/mi-receta/nueva", data={"raw": "apio"}).status_code, 400)
        draft = self.create()
        self.assertEqual(draft["context"]["city"], "Milano")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"200 g", response.data)
        other = app.test_client()
        self.assertEqual(other.get(self.url).status_code, 404)
        self.assertEqual(other.get(self.url + "/estado").status_code, 404)

    def test_async_translation_and_invalidation(self):
        draft = self.create()
        with patch("recipe_routes.jobs.submit", side_effect=lambda fn: fn()), patch("recipe_routes.OllamaClient") as client:
            client.return_value.settings = ModelSettings()
            client.return_value.generate.return_value = "cavolo rapa"
            response = self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"], "action": "translate"})
        self.assertEqual(response.status_code, 303)
        draft = self.get()
        self.assertEqual(draft["status"], "ready")
        self.assertEqual(draft["rows"][0]["local_name"], "cavolo rapa")
        self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"], "action": "save", "city": "Roma"})
        draft = self.get()
        self.assertEqual(draft["rows"][0]["local_name"], "cavolo rapa")
        self.assertEqual(draft["context"]["city"], "Roma")
        row_id = draft["rows"][0]["id"]
        response = self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"], "action": "save", "destination_country": "Alemania"})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.get()["rows"][0]["local_name"], "")
        stale = self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"], "action": "save"})
        self.assertEqual(stale.status_code, 400)

    def test_model_failure_preserves_input_and_retry(self):
        draft = self.create()
        with patch("recipe_routes.jobs.submit", side_effect=lambda fn: fn()), patch("recipe_routes.OllamaClient") as client:
            client.return_value.settings = ModelSettings()
            client.return_value.generate.side_effect = ModelError("unavailable", "Inicia Ollama.")
            self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"], "action": "translate"})
        current = self.get()
        self.assertEqual(current["status"], "editable")
        self.assertEqual(current["rows"][0]["amount"], "200 g")
        self.assertEqual(current["error"], "Inicia Ollama.")

    def test_import_selected_recipe_keeps_documented_adjustments(self):
        response = self.client.post("/mi-receta/importar", data={"csrf": self.csrf, "recipe": "quesadillas_quesillo", "choice_queso_oaxaca": "mozzarella"})
        self.assertEqual(response.status_code, 303)
        page = self.client.get(response.location)
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"mozzarella", page.data.lower())
        self.assertIn("escúrrela".encode(), page.data)

    def test_missing_key_is_actionable_and_no_fake_coverage(self):
        draft = self.create()
        database = DraftStore(app.config["RECIPE_DB"])
        draft["rows"][0]["local_name"] = "cavolo rapa"
        draft = database.save(self.owner, draft, draft["revision"])
        with patch.dict("os.environ", {"TAVILY_API_KEY": ""}), patch("recipe_routes.jobs.submit", side_effect=lambda fn: fn()):
            response = self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"], "action": "stores", "products": "cavolo rapa"})
        self.assertEqual(response.status_code, 303)
        self.assertIn("TAVILY_API_KEY", self.get()["stores"]["errors"][0]["message"])
        self.assertEqual(self.get()["stores"]["searches"], [])
        self.assertIn(b"Productos verificados: 0", self.client.get(self.url).data)

    def test_store_links_are_escaped_and_counted_as_candidates(self):
        draft = self.create()
        database = DraftStore(app.config["RECIPE_DB"])
        draft["rows"][0]["local_name"] = "cavolo rapa"
        draft = database.save(self.owner, draft, draft["revision"])
        result = {"product": "cavolo rapa", "query": "cavolo rapa comprare Milano", "cached": False,
                  "queried_at": "2026-11-24T20:00:00+00:00", "results": [{"domain": "example.com", "title": "<script>alert(1)</script>",
                  "url": "https://example.com/prodotto", "snippet": "<b>dato del proveedor</b>", "evidence": "Enlace candidato",
                  "stock": "Desconocido", "location": "Por comprobar"}]}
        with patch("recipe_routes.jobs.submit", side_effect=lambda fn: fn()), patch("recipe_routes.StoreSearchService.search", return_value=result):
            self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"], "action": "stores", "products": "cavolo rapa"})
        page = self.client.get(self.url).get_data(as_text=True)
        self.assertIn('href="https://example.com/prodotto"', page)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("enlaces para 1 de 1 productos", page)
        self.assertIn("Productos verificados: 0", page)

    def test_substitute_selection_uses_separate_amount_and_preserves_steps(self):
        draft = self.create()
        row = draft["rows"][0]
        row["adaptation"] = {"result": {"alternatives": [{"local_name": "sedano rapa", "adjustment": "Ajusta el tiempo.", "limitation": "Sabor distinto.", "reason": "Textura parecida.", "source_ids": []}],
                                      "warnings": [], "clarification": None}, "sources": {}}
        database = DraftStore(app.config["RECIPE_DB"])
        draft = database.save(self.owner, draft, draft["revision"])
        self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"], "action": "choose", "row": row["id"], "alternative": "0", "sub_amount": ""})
        current = self.get()
        self.assertEqual(shopping_list(current)[0]["amount"], "Por confirmar")
        self.assertEqual(current["steps"], draft["steps"])
        page = self.client.get(self.url).get_data(as_text=True)
        self.assertIn("Cambios para cocinar", page)
        self.assertIn("Ajusta el tiempo.", page)
        self.assertIn("Sabor distinto.", page)

    def test_restart_recovers_draft_instead_of_polling_forever(self):
        draft = self.create()
        draft.update(status="working", job_instance="old-process")
        DraftStore(app.config["RECIPE_DB"]).save(self.owner, draft, draft["revision"])
        response = self.client.get(self.url + "/estado")
        self.assertEqual(response.json["status"], "editable")
        self.assertIn("interrumpió", self.get()["error"])
        self.assertEqual(self.get()["rows"][0]["amount"], "200 g")

    def test_title_search_and_delete(self):
        response = self.client.get("/recetas?q=quesadillas")
        self.assertIn(b"Quesadillas", response.data)
        self.assertNotIn(b"option value=\"guacamole", response.data)
        self.create()
        response = self.client.post(self.url + "/borrar", data={"csrf": self.csrf})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.client.get(self.url).status_code, 404)
