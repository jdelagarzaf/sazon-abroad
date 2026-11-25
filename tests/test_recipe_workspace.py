from copy import deepcopy
import re
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from app import app
from adaptation import AdaptationService
from local_model import ModelError, ModelSettings
from recipe_workspace import DraftStore, extract_recipe, quantity, shopping_list, propose_draft
from shopping_plan import product_key, purchase_plan
from retailers import RETAILERS


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
                  "queried_at": "2026-11-24T20:00:00+00:00", "results": [{"domain": "esselunga.it", "title": "<script>alert(1)</script> Cavolo rapa",
                  "url": "https://www.esselunga.it/p/cavolo-rapa/12345678.html", "snippet": "<b>dato del proveedor</b>", "evidence": "Enlace candidato",
                  "stock": "Desconocido", "location": "Por comprobar"}]}
        with patch("recipe_routes.jobs.submit", side_effect=lambda fn: fn()), patch("recipe_routes.StoreSearchService.search", return_value=result):
            self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"], "action": "stores", "products": "cavolo rapa"})
        page = self.client.get(self.url).get_data(as_text=True)
        self.assertIn('href="https://www.esselunga.it/p/cavolo-rapa/12345678.html"', page)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("1 de 1 productos con evidencia", page)
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
        self.assertNotIn("<h3>Cambios para cocinar", page)
        self.assertIn('class="recipe-note-panel"', page)
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

    def test_compact_table_and_always_visible_steps(self):
        self.create()
        html = self.client.get(self.url).get_data(as_text=True)
        visible = html.split('<dialog', 1)[0]
        self.assertIn('aria-label="Ingredientes y propuestas"', visible)
        self.assertIn('Producto / original</th>', visible)
        self.assertIn('Cuece el colinabo.', visible)
        self.assertNotIn('name="name"', visible)
        self.assertNotIn('Guardar cambios', html)
        self.assertNotIn('Consultar los pasos guardados', html)
        self.assertIn('id="recipe-settings"', html)
        self.assertIn('name="action" value="row_regenerate"', visible)
        self.assertNotIn('Generar solo este', html)
        self.assertNotIn('Tu lista de compra', html)
        self.assertNotIn('Búsqueda manual de apoyo', html)

    def test_modal_add_edit_remove_and_invalid_input(self):
        draft = self.create()
        response = self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"],
            "action": "row_add", "name": "Eneldo", "amount": "al gusto", "use": "ensalada"})
        self.assertEqual(response.status_code, 303)
        draft = self.get()
        added = draft["rows"][1]
        response = self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"],
            "action": "row_save", "row": added["id"], "name": "Eneldo fresco", "amount": "10 g", "local_name": "aneto", "use": "ensalada"})
        self.assertEqual(response.status_code, 303)
        draft = self.get()
        self.assertEqual(draft["rows"][0]["amount"], "200 g")
        self.assertEqual(draft["rows"][1]["local_name"], "aneto")
        response = self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"],
            "action": "row_save", "row": added["id"], "name": "", "amount": "20 g"})
        self.assertEqual(response.status_code, 400)
        self.assertIn('data-auto-open', response.get_data(as_text=True))
        self.assertEqual(self.get()["rows"][1]["amount"], "10 g")
        self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"], "action": "row_remove", "row": added["id"]})
        draft = self.get()
        self.assertEqual(len(draft["rows"]), 1)
        response = self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"], "action": "row_remove", "row": draft["rows"][0]["id"]})
        self.assertEqual(response.status_code, 400)

    def proposal(self):
        return {"model": "test", "sources": {}, "result": {"local_name": "cavolo rapa", "kind": "substitute",
            "warnings": [], "clarification": None, "source_ids": [], "alternatives": [
            {"local_name": "sedano rapa", "adjustment": "Ajusta el tiempo.", "limitation": "Sabor distinto.", "reason": "Textura parecida.", "source_ids": []},
            {"local_name": "rapa", "adjustment": None, "limitation": "Otro sabor.", "reason": "Otra opción.", "source_ids": []}]}}

    def test_global_send_selects_first_and_modal_can_change_proposal(self):
        draft = self.create()
        with patch("recipe_routes.jobs.submit", side_effect=lambda fn: fn()), patch.object(app.extensions["adaptation_service"], "adapt", return_value=self.proposal()):
            response = self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"], "action": "generate"})
        self.assertEqual(response.status_code, 303)
        draft = self.get()
        row = draft["rows"][0]
        self.assertEqual(row["selected_name"], "sedano rapa")
        self.assertEqual(row["selected_amount"], "")
        self.assertEqual(shopping_list(draft)[0]["amount"], "Por confirmar")
        self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"], "action": "row_save",
            "row": row["id"], "proposal": "alternative:1", "sub_amount": "120 g"})
        draft = self.get()
        self.assertEqual(draft["rows"][0]["selected_name"], "rapa")
        self.assertEqual(shopping_list(draft)[0]["amount"], "120 g")
        self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"], "action": "row_save", "row": row["id"], "proposal": "original"})
        draft = self.get()
        self.assertNotIn("selected_name", draft["rows"][0])
        self.assertEqual(shopping_list(draft)[0]["amount"], "200 g")

    def test_individual_generation_saves_edits_and_does_not_touch_other_rows(self):
        draft = self.create()
        draft["rows"].append({"id": "other", "name": "sal", "amount": "1 g", "local_name": "sale", "use": "", "preparation": ""})
        draft = DraftStore(app.config["RECIPE_DB"]).save(self.owner, draft, draft["revision"])
        with patch("recipe_routes.jobs.submit", side_effect=lambda fn: fn()), patch.object(app.extensions["adaptation_service"], "adapt", return_value=self.proposal()) as adapt:
            response = self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"], "action": "row_generate", "row": draft["rows"][0]["id"], "name": "Colinabo fresco", "amount": "300 g", "use": "sopa", "preparation": "fresco"})
        self.assertIn('edit=', response.location)
        self.assertEqual(adapt.call_count, 1)
        context = adapt.call_args.args[0]
        self.assertEqual((context.query, context.culinary_use, context.preparation), ("¿Qué uso en vez de Colinabo fresco para sopa?", "sopa", "fresco"))
        current = self.get()
        self.assertEqual(current["rows"][0]["amount"], "300 g")
        self.assertEqual(current["rows"][1], draft["rows"][1])

    def test_row_reload_uses_saved_context_and_preserves_matching_substitute_amount(self):
        draft = self.create()
        row = draft["rows"][0]
        row.update(local_name="cavolo rapa", use="sopa", adaptation=self.proposal(),
                   selected_name="sedano rapa", selected_index=0, selected_amount="120 g")
        draft["rows"].append({"id": "other", "name": "sal", "amount": "1 g", "local_name": "sale", "use": "", "preparation": ""})
        draft = DraftStore(app.config["RECIPE_DB"]).save(self.owner, draft, draft["revision"])
        with patch("recipe_routes.jobs.submit", side_effect=lambda fn: fn()), patch.object(app.extensions["adaptation_service"], "adapt", return_value=self.proposal()) as adapt:
            response = self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"],
                "action": "row_regenerate", "row": row["id"], "name": "Unsubmitted edit", "amount": "999 g"})
        self.assertEqual(response.status_code, 303)
        self.assertNotIn("edit=", response.location)
        self.assertEqual(adapt.call_count, 1)
        self.assertEqual(adapt.call_args.args[0].culinary_use, "sopa")
        current = self.get()
        self.assertEqual(current["rows"][0]["name"], row["name"])
        self.assertEqual(current["rows"][0]["amount"], "200 g")
        self.assertEqual(current["rows"][0]["selected_amount"], "120 g")
        self.assertEqual(current["rows"][1], draft["rows"][1])
        html = self.client.get(self.url).get_data(as_text=True)
        table_row = html.split('id="ingrediente-' + row["id"] + '"', 1)[1].split('</tr>', 1)[0]
        self.assertEqual(table_row.count("120 g"), 1)
        self.assertNotIn("200 g", table_row)
        self.assertIn('search?q=sedano+rapa', table_row)
        self.assertLess(table_row.index('>sedano rapa</a>'), table_row.index('>colinabo</span>'))

    def test_row_reload_failure_keeps_previous_choice_and_quantity(self):
        draft = self.create()
        draft["rows"][0].update(local_name="cavolo rapa", adaptation=self.proposal(),
            selected_name="rapa", selected_index=1, selected_amount="120 g")
        draft = DraftStore(app.config["RECIPE_DB"]).save(self.owner, draft, draft["revision"])
        with patch("recipe_routes.jobs.submit", side_effect=lambda fn: fn()), patch.object(app.extensions["adaptation_service"], "adapt", side_effect=ModelError("offline", "Modelo no disponible.")):
            self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"],
                "action": "row_regenerate", "row": draft["rows"][0]["id"]})
        current = self.get()
        self.assertEqual(current["rows"], draft["rows"])
        self.assertIn("Modelo no disponible", current["error"])

    def test_settings_and_steps_are_saved_independently(self):
        draft = self.create()
        draft["rows"][0]["local_name"] = "cavolo rapa"
        draft = DraftStore(app.config["RECIPE_DB"]).save(self.owner, draft, draft["revision"])
        self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"], "action": "settings", "title": "Mi sopa", "city": "Roma"})
        draft = self.get()
        self.assertEqual(draft["rows"][0]["local_name"], "cavolo rapa")
        self.assertEqual(draft["context"]["city"], "Roma")
        self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"], "action": "steps", "steps": "Corta.\nCuece."})
        self.assertEqual(self.get()["steps"], ["Corta.", "Cuece."])

    def test_context_edit_discards_outdated_options_and_invalid_choice_is_rejected(self):
        draft = self.create()
        draft["rows"][0].update(adaptation=self.proposal(), local_name="cavolo rapa", selected_name="sedano rapa", selected_index=0, selected_amount="100 g")
        draft = DraftStore(app.config["RECIPE_DB"]).save(self.owner, draft, draft["revision"])
        row_id = draft["rows"][0]["id"]
        invalid = self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"], "action": "row_save", "row": row_id, "proposal": "alternative:99"})
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(self.get()["rows"][0]["selected_name"], "sedano rapa")
        self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"], "action": "row_save", "row": row_id, "use": "otro plato", "proposal": "alternative:0"})
        row = self.get()["rows"][0]
        self.assertNotIn("adaptation", row)
        self.assertNotIn("selected_name", row)
        self.assertEqual(row["local_name"], "")

    def test_add_and_generate_queue_failure_reopens_saved_row_without_duplicate(self):
        draft = self.create()
        with patch("recipe_routes.jobs.submit", side_effect=ValueError("Cola llena.")):
            response = self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"],
                "action": "row_add_generate", "name": "Eneldo", "amount": "10 g"})
        self.assertEqual(response.status_code, 400)
        current = self.get()
        self.assertEqual(len(current["rows"]), 2)
        row_id = current["rows"][-1]["id"]
        html = response.get_data(as_text=True)
        self.assertIn("El ingrediente se guardó", html)
        self.assertRegex(html, 'id="ingredient-' + row_id + '"[^>]*data-auto-open')

    def test_store_preferences_use_preferred_domains_then_fallback_only_if_needed(self):
        draft = self.create()
        draft["rows"][0]["local_name"] = "cavolo rapa"
        draft = DraftStore(app.config["RECIPE_DB"]).save(self.owner, draft, draft["revision"])
        calls = []
        def lookup(product, city, country, language, domains):
            calls.append(domains)
            rows = [{"url": "https://reddit.com/p/cavolo-rapa/12345678", "title": "Cavolo rapa"}] if len(calls) == 1 else [
                {"url": "https://www.lidl.it/p/cavolo-rapa/p12345678", "title": "Cavolo rapa", "snippet": "Verdura"}]
            return {"product": product, "queried_at": "2026-11-25", "cached": False, "query": product, "results": rows}
        with patch("recipe_routes.jobs.submit", side_effect=lambda fn: fn()), patch("recipe_routes.StoreSearchService.search", side_effect=lookup):
            response = self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"], "action": "stores",
                "products": "cavolo rapa", "preferences_form": "1", "retailers": "esselunga", "allow_other": "1"})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(calls[0], ["esselunga.it"])
        self.assertIn("lidl.it", calls[1])
        current = self.get()
        self.assertEqual(current["store_preferences"]["ids"], ["esselunga"])
        self.assertEqual(current["stores"]["searches"][0]["results"][0]["retailer_id"], "lidl")
        self.assertEqual(purchase_plan(shopping_list(current), current["stores"], RETAILERS)["store_count"], 1)

    def test_store_search_does_not_spend_fallback_query_when_preferred_has_product(self):
        draft = self.create()
        draft["rows"][0]["local_name"] = "cavolo rapa"
        draft = DraftStore(app.config["RECIPE_DB"]).save(self.owner, draft, draft["revision"])
        result = {"product": "cavolo rapa", "queried_at": "2026-11-25", "cached": True, "query": "q", "results": [
            {"url": "https://www.esselunga.it/p/cavolo-rapa/12345678", "title": "Cavolo rapa", "snippet": "Verdura"}]}
        with patch("recipe_routes.jobs.submit", side_effect=lambda fn: fn()), patch("recipe_routes.StoreSearchService.search", return_value=result) as search:
            self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"], "action": "stores",
                "products": "cavolo rapa", "preferences_form": "1", "retailers": "esselunga", "allow_other": "1"})
        self.assertEqual(search.call_count, 1)
        self.assertEqual(self.get()["stores"]["searches"][0]["results"][0]["retailer_id"], "esselunga")

    def test_manual_store_distribution_persists_and_reset_reoptimizes_without_search(self):
        draft = self.create()
        draft["rows"][0]["local_name"] = "cavolo rapa"
        draft["rows"].append({"id": "rice", "name": "arroz", "amount": "100 g", "local_name": "riso", "use": "", "preparation": ""})
        draft["stores"] = {"requested": ["cavolo rapa", "riso"], "preferred": ["esselunga", "penny"], "errors": [], "searches": [
            {"product": name, "queried_at": "2026-11-25", "results": [{"url": f"https://www.{sid}.it/p/{name.replace(' ', '-')}/12345678", "title": name, "snippet": ""} for sid in stores]}
            for name, stores in [("cavolo rapa", ["esselunga", "penny"]), ("riso", ["esselunga"])]]}
        draft = DraftStore(app.config["RECIPE_DB"]).save(self.owner, draft, draft["revision"])
        with patch("recipe_routes.StoreSearchService.search") as search:
            self.client.post(self.url, data={"csrf": self.csrf, "revision": draft["revision"], "action": "store_plan", "pin_" + product_key("cavolo rapa"): "penny"})
            current = self.get()
            self.assertEqual(current["store_assignments"], {"cavolo rapa": "penny"})
            self.assertEqual(purchase_plan(shopping_list(current), current["stores"], RETAILERS, current["store_assignments"])["store_count"], 2)
            self.client.post(self.url, data={"csrf": self.csrf, "revision": current["revision"], "action": "reset_store_plan"})
            current = self.get()
            self.assertEqual(current["store_assignments"], {})
            self.assertEqual(purchase_plan(shopping_list(current), current["stores"], RETAILERS)["store_count"], 1)
            invalid = self.client.post(self.url, data={"csrf": self.csrf, "revision": current["revision"], "action": "store_plan", "pin_" + product_key("riso"): "lidl"})
            self.assertEqual(invalid.status_code, 400)
            search.assert_not_called()
