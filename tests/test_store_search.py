import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from store_search import StoreSearchError, StoreSearchService, TavilySearch, group_stores, public_url


class StoreSearchTests(unittest.TestCase):
    def test_real_protocol_and_untrusted_urls(self):
        opener = Mock()
        opener.open.return_value = io.BytesIO(json.dumps({"results": [
            {"title": "Producto", "url": "https://example.com/prodotto", "content": "Compra online"},
            {"title": "bad", "url": "javascript:alert(1)", "content": "x"},
            {"title": "bad", "url": "http://127.0.0.1/admin", "content": "x"},
            {"title": "bad", "url": "https://user:pass@example.com", "content": "x"},
            {"title": "duplicate", "url": "https://example.com/prodotto", "content": "x"}
        ]}).encode())
        results = TavilySearch("test-only-secret", opener).search("apio Milano")
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.tavily.com/search")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-only-secret")
        payload = json.loads(request.data)
        self.assertEqual(payload["search_depth"], "basic")
        self.assertFalse(payload["auto_parameters"])
        self.assertFalse(payload["include_answer"])
        self.assertNotIn("api_key", payload)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["stock"], "Desconocido")

    def test_provider_errors_hide_body_and_key(self):
        for code in (401, 429, 432, 500):
            opener = Mock()
            opener.open.side_effect = HTTPError("https://api.tavily.com/search", code, "private-body-secret", {}, None)
            with self.assertRaises(StoreSearchError) as error:
                TavilySearch("secret", opener).search("apio Milano")
            self.assertNotIn("secret", str(error.exception))
        opener = Mock()
        opener.open.return_value = io.BytesIO(b'{"results":null}')
        with self.assertRaises(StoreSearchError):
            TavilySearch("secret", opener).search("x")

    def test_persistent_cache_daily_cap_and_location_key(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"SAZON_SEARCH_DAILY_LIMIT": "2"}):
            path = Path(directory) / "search.sqlite"
            provider = Mock()
            provider.search.return_value = []
            service = StoreSearchService(path)
            self.assertFalse(service.search("apio", "Milano", "Italia", provider=provider)["cached"])
            self.assertTrue(StoreSearchService(path).search("apio", "Milano", "Italia", provider=provider)["cached"])
            service.search("apio", "Roma", "Italia", provider=provider)
            with self.assertRaises(StoreSearchError):
                service.search("perejil", "Milano", "Italia", provider=provider)
            self.assertEqual(provider.search.call_count, 2)

    def test_missing_key_uses_no_budget_and_cache_expires(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"TAVILY_API_KEY": ""}):
            service = StoreSearchService(Path(directory) / "search.sqlite")
            with self.assertRaises(StoreSearchError):
                service.search("apio", "Milano", "Italia")
            with service.connect() as db:
                self.assertEqual(db.execute("SELECT count(*) FROM usage").fetchone()[0], 0)
            provider = Mock()
            provider.search.return_value = []
            service.search("apio", "Milano", "Italia", provider=provider)
            with service.connect() as db:
                db.execute("UPDATE cache SET stamp=0")
            self.assertFalse(service.search("apio", "Milano", "Italia", provider=provider)["cached"])
            self.assertEqual(provider.search.call_count, 2)

    def test_coverage_is_distinct_products_per_domain(self):
        hit = {"domain": "example.com", "url": "https://example.com", "title": "store"}
        searches = [{"product": "apio", "queried_at": "2026-11-24", "results": [hit, hit]},
                    {"product": "lenteja", "queried_at": "2026-11-24", "results": [hit]}]
        groups = group_stores(searches, 3)
        self.assertEqual(groups[0]["products"], ["apio", "lenteja"])
        self.assertFalse(public_url("http://192.168.1.2"))
        self.assertFalse(public_url("http://[::1]"))
        self.assertFalse(public_url("https://foo.internal/a"))
        self.assertTrue(public_url("https://example.com/item"))
