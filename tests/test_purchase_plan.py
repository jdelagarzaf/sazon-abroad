from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from retailers import RETAILERS, commercial_result, custom_retailers, resolve_retailers
from shopping_plan import purchase_plan
from store_search import StoreSearchService, TavilySearch
from recipe_workspace import extract_recipe, shopping_list


def hit(product, sid, path=None):
    store = next(store for store in RETAILERS if store["id"] == sid)
    return {"url": f"https://www.{store['domains'][0]}" + (path or "/p/" + product.replace(" ", "-") + "/12345678"),
            "title": product.title(), "snippet": "Prodotto alimentare", "domain": store["domains"][0]}


def fixture(coverage, preferred=None):
    shopping = [{"name": name, "amount": "100 g", "origins": [], "rows": []} for name in coverage]
    searches = [{"product": name, "queried_at": "2026-11-25T12:00:00Z", "results": [hit(name, sid) for sid in shops]} for name, shops in coverage.items()]
    stored = {"requested": list(coverage), "preferred": preferred or [], "searches": searches}
    return shopping, stored


class CommercialFilterTests(unittest.TestCase):
    def test_real_pecorino_product_urls_are_not_lost(self):
        # Public catalog pages checked on 2026-11-25; this is not a stock assertion.
        pages = [
            ("Pecorino Romano DOP 250 g | Prodotti Coop", "https://www.coop.it/il-prodotto-coop/coop/formaggi/alimenti-freschi/formaggi-stagionati-servizio-assistito/pecorino", "coop"),
            ("Pecorino Romano DOP Grattugiato 100 g | Prodotti Coop", "https://www.coop.it/il-prodotto-coop/coop/formaggi/alimenti-freschi/formaggi-stagionati-libero-servizio/pecorino-romano", "coop"),
            ("Pecorino Romano DOP 12 mesi Conad in vendita online | Conad", "https://spesaonline.conad.it/p/sapori-dintorni-conad-pecorino-romano-dop-stagionatura-minima-12-mesi-300-g--358059", "conad"),
        ]
        for title, url, retailer in pages:
            with self.subTest(url=url):
                result = commercial_result({"title": title, "url": url}, "pecorino romano", RETAILERS)
                self.assertIsNotNone(result)
                self.assertEqual(result["retailer_id"], retailer)
                self.assertEqual(result["evidence_type"], "product_page")
                self.assertEqual(result["stock"], "Desconocido")
        self.assertIsNone(commercial_result({"title": "Pecorino Romano", "url": "https://www.coop.it/il-prodotto-coop/coop"}, "pecorino romano", RETAILERS))

    def test_manufacturer_prefix_does_not_hide_product_or_admit_composite_food(self):
        self.assertIsNotNone(commercial_result(hit("CAO Formaggi Pecorino Romano DOP", "esselunga"), "pecorino romano", RETAILERS))
        self.assertIsNotNone(commercial_result(hit("Granarolo Latte senza lattosio", "conad"), "latte senza lattosio", RETAILERS))
        self.assertIsNone(commercial_result(hit("Sugo al Pecorino Romano", "conad"), "pecorino romano", RETAILERS))
        self.assertIsNone(commercial_result(hit("Cioccolato al latte", "conad"), "latte", RETAILERS))
        self.assertIsNone(commercial_result(hit("Esselunga Pizza 4 formaggi", "esselunga"), "pecorino romano", RETAILERS))

    def test_scoped_query_names_store_alternatives_without_requiring_city(self):
        with tempfile.TemporaryDirectory() as directory:
            service = StoreSearchService(Path(directory) / "cache.sqlite")
            provider = Mock()
            provider.search.return_value = []
            result = service.search("pecorino romano", "Milano", "Italia", provider=provider,
                                    domains=["penny.it", "esselunga.it", "lidl.it"])
            self.assertEqual(result["query"], '"pecorino romano" (Esselunga OR Lidl OR PENNY)')
            self.assertNotIn("Milano", result["query"])
            self.assertEqual(provider.search.call_args.kwargs["domains"], ["esselunga.it", "lidl.it", "penny.it"])
            self.assertTrue(service.search("pecorino romano", "Milano", "Italia", provider=provider,
                                         domains=["esselunga.it", "lidl.it", "penny.it"])["cached"])
            self.assertFalse(service.search("pecorino romano", "Roma", "Italia", provider=provider,
                                          domains=["esselunga.it", "lidl.it", "penny.it"])["cached"])

    def test_query_deduplicates_shop_domains_and_supports_custom_country(self):
        with tempfile.TemporaryDirectory() as directory:
            service = StoreSearchService(Path(directory) / "cache.sqlite")
            provider = Mock()
            provider.search.return_value = []
            result = service.search("pecorino romano", "Milano", "Italia", provider=provider, domains=["coop.it", "coopshop.it"])
            self.assertEqual(result["query"], '"pecorino romano" (Coop)')
            result = service.search("rice", "Berlin", "Alemania", provider=provider, domains=["shop.example.de"])
            self.assertEqual(result["query"], '"rice" (shop.example.de)')

    def test_host_boundary_social_recipe_locator_and_product_mismatch(self):
        valid = hit("mozzarella", "esselunga")
        self.assertIsNotNone(commercial_result(valid, "mozzarella", RETAILERS))
        for url in ["https://reddit.com/p/mozzarella/12345678", "https://www.instagram.com/p/mozzarella/12345678",
                    "https://esselunga.it.evil.com/p/mozzarella/12345678", "https://www.esselunga.it/ricette/p/mozzarella/12345678",
                    "https://www.esselunga.it/negozi/p/mozzarella/12345678", "https://www.esselunga.it/it-it/homepage.html",
                    "https://www.esselunga.it/cerca?q=mozzarella", "http://127.0.0.1/p/mozzarella/12345678"]:
            with self.subTest(url=url):
                self.assertIsNone(commercial_result({**valid, "url": url}, "mozzarella", RETAILERS))
        self.assertIsNone(commercial_result(hit("latte", "conad"), "latte condensato", RETAILERS))
        self.assertIsNone(commercial_result(hit("latte", "conad"), "latte senza lattosio", RETAILERS))
        self.assertIsNone(commercial_result({**hit("latte", "conad"), "snippet": "latte condensato"}, "latte condensato", RETAILERS))
        self.assertIsNone(commercial_result(hit("sofficini pomodoro e mozzarella", "penny"), "mozzarella", RETAILERS))
        self.assertIsNone(commercial_result(hit("cioccolato al latte", "penny"), "latte", RETAILERS))

    def test_catalog_is_labeled_and_subdomains_are_valid(self):
        result = commercial_result(hit("mozzarella", "conad", "/prodotti/formaggi/mozzarella.html"), "mozzarella", RETAILERS)
        self.assertEqual(result["evidence_type"], "catalog_listing")
        result = commercial_result({**hit("mozzarella", "esselunga"), "url": "https://spesaonline.esselunga.it/p/mozzarella/12345678"}, "mozzarella", RETAILERS)
        self.assertEqual(result["retailer_id"], "esselunga")
        self.assertEqual(result["stock"], "Desconocido")

    def test_custom_domains_are_bounded_and_do_not_lock_other_countries(self):
        self.assertEqual(resolve_retailers("Alemania", [], "shop.example.de")[0]["name"], "shop.example.de")
        for value in ["reddit.com", "www.instagram.com", "127.0.0.1", "foo.internal", "https://shop.it/a", "x.it y.it z.it w.it"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                custom_retailers(value)
        self.assertEqual(resolve_retailers("Italia", ["penny"], "spesaonline.conad.it")[-1]["id"], "conad")

    def test_provider_uses_hard_domain_filter_and_rechecks_returned_hosts(self):
        opener = Mock()
        opener.open.return_value = io.BytesIO(json.dumps({"results": [hit("mozzarella", "esselunga"),
             {"title": "mozzarella", "url": "https://www.reddit.com/p/mozzarella/12345678", "content": "wrong"}]}).replace('"snippet"', '"content"').encode())
        rows = TavilySearch("test-only", opener).search("mozzarella", domains=["esselunga.it"])
        payload = json.loads(opener.open.call_args.args[0].data)
        self.assertEqual(payload["include_domains"], ["esselunga.it"])
        self.assertEqual(payload["include_domains_mode"], "restrict")
        self.assertEqual(len(rows), 1)

    def test_cache_separates_store_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            service = StoreSearchService(Path(directory) / "cache.sqlite")
            provider = Mock()
            provider.search.return_value = []
            service.search("mozzarella", "Milano", "Italia", provider=provider, domains=["penny.it"])
            service.search("mozzarella", "Milano", "Italia", provider=provider, domains=["lidl.it"])
            self.assertTrue(service.search("mozzarella", "Milano", "Italia", provider=provider, domains=["penny.it"])["cached"])
            self.assertEqual(provider.search.call_count, 2)


class MinimumStorePlanTests(unittest.TestCase):
    def test_single_store_covers_all_and_items_are_not_duplicated(self):
        shopping, stored = fixture({"latte": ["esselunga", "penny"], "riso": ["esselunga"], "sale": ["esselunga", "lidl"]})
        plan = purchase_plan(shopping, stored, RETAILERS)
        self.assertEqual(plan["store_count"], 1)
        self.assertEqual(plan["covered"], 3)
        self.assertEqual(len(plan["groups"][0]["items"]), 3)

    def test_exact_solution_beats_greedy_largest_first(self):
        # Esselunga covers the most, but needs two more stores; Penny+Lidl suffice.
        shopping, stored = fixture({"uno": ["esselunga", "penny"], "due": ["esselunga", "penny"],
            "tre": ["esselunga", "lidl"], "quattro": ["esselunga", "lidl"], "cinque": ["penny"], "sei": ["lidl"]})
        plan = purchase_plan(shopping, stored, RETAILERS)
        self.assertEqual(plan["store_count"], 2)
        self.assertEqual({group["store"]["id"] for group in plan["groups"]}, {"penny", "lidl"})
        self.assertEqual(sum(len(group["items"]) for group in plan["groups"]), 6)

    def test_preferences_precede_fallback_and_missing_are_honest(self):
        shopping, stored = fixture({"latte": ["esselunga", "conad"], "riso": ["penny", "conad"], "sale": []}, ["esselunga", "penny"])
        plan = purchase_plan(shopping, stored, RETAILERS)
        self.assertEqual(plan["store_count"], 2)
        self.assertEqual(plan["missing"], ["sale"])
        self.assertEqual(plan["covered"], 2)

    def test_manual_pin_is_respected_and_unknown_assignment_rejected(self):
        shopping, stored = fixture({"latte": ["esselunga", "penny"], "riso": ["esselunga"]})
        plan = purchase_plan(shopping, stored, RETAILERS, {"latte": "penny"})
        self.assertEqual(plan["assignments"]["latte"], "penny")
        self.assertEqual(plan["store_count"], 2)
        with self.assertRaises(ValueError):
            purchase_plan(shopping, stored, RETAILERS, {"riso": "lidl"})

    def test_old_unfiltered_results_are_rechecked_before_planning(self):
        shopping, stored = fixture({"latte": ["esselunga"]})
        stored["searches"][0]["results"][0]["url"] = "https://reddit.com/p/latte/12345678"
        plan = purchase_plan(shopping, stored, RETAILERS)
        self.assertEqual(plan["covered"], 0)
        self.assertEqual(plan["store_count"], 0)

    def test_empty_partial_and_same_product_different_units(self):
        self.assertEqual(purchase_plan([], None, RETAILERS)["groups"], [])
        shopping, stored = fixture({"latte": ["penny"]})
        shopping.append({**shopping[0], "amount": "1 taza"})
        shopping.append({"name": "riso", "amount": "2 g"})
        plan = purchase_plan(shopping, stored, RETAILERS)
        self.assertEqual(len(plan["groups"][0]["items"]), 2)
        self.assertEqual(plan["total"], 1)
        self.assertEqual(plan["unsearched"], ["riso"])

    def test_merged_notes_preserve_adjustments_and_limits(self):
        draft = extract_recipe("200 g de queso")
        row = draft["rows"][0]
        row.update(selected_name="mozzarella", selected_index=0, selected_amount="", adaptation={"result": {
            "alternatives": [{"adjustment": "Escurrir.", "limitation": "Otro sabor."}], "warnings": ["Revisa el envase."], "clarification": None}})
        item = shopping_list(draft)[0]
        self.assertEqual(item["notes"], ["Escurrir.", "Otro sabor.", "Revisa el envase."])
        self.assertEqual(item["amount"], "Por confirmar")
