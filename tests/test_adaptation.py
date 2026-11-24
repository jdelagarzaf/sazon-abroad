"""Contract, transport and Flask integration checks; no installed model required."""

from copy import deepcopy
from dataclasses import replace
from http.client import BadStatusLine
import io
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from adaptation import (
    AdaptationRequest, AdaptationService, RESPONSE_SCHEMA, generation_schema, local_evidence, name_only, normalize_result, validate_result,
)
from jsonschema import Draft202012Validator
from app import app
from ingredient_views import get_catalog
from local_model import ModelError, ModelSettings, OllamaClient
from search import IngredientSearch


def proposal():
    return {
        "original_name": "Hojas de curry", "local_name": "foglie di curry",
        "kind": "same_ingredient", "culinary_use": None,
        "summary": "Busca hojas de curry, no una mezcla de especias en polvo.",
        "clarification": None, "warnings": [], "source_ids": [], "alternatives": [],
    }


class AdaptationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog, cls.index = get_catalog()

    def setUp(self):
        self.service = AdaptationService()
        self.client = Mock(settings=ModelSettings())
        self.client.generate.return_value = proposal()
        self.client.generate.side_effect = lambda messages, schema: (
            {"local_name": self.client.generate.return_value["local_name"]}
            if set(schema.get("properties", {})) == {"local_name"} else self.client.generate.return_value
        )
        self.context = AdaptationRequest(query="hojas de curry")

    def adapt(self, context=None):
        return self.service.adapt(context or self.context, self.catalog, self.index, self.client)

    def test_unknown_ingredient_reaches_model_without_catalog_id(self):
        result = self.adapt()
        self.assertEqual(result["result"]["local_name"], "foglie di curry")
        messages, schema = self.client.generate.call_args.args
        payload = json.loads(messages[1]["content"])
        self.assertEqual(payload["context"]["query"], "hojas de curry")
        self.assertEqual(payload["evidence"]["ingredients"], [])
        self.assertEqual(set(schema["properties"]), {"local_name"})
        self.assertEqual(result["result"]["alternatives"], [])
        self.assertTrue(result["name_only"])
        self.assertEqual(result["evidence_status"], "generated_unverified")

    def test_cache_isolated_by_country_use_restrictions_model_and_evidence(self):
        first = self.adapt()
        self.assertFalse(first["cached"])
        first["result"]["local_name"] = "changed by caller"
        self.assertEqual(self.adapt()["result"]["local_name"], "foglie di curry")
        self.assertTrue(self.adapt()["cached"])
        self.assertEqual(self.client.generate.call_count, 1)
        for context in [replace(self.context, destination_country="Alemania", target_language="de"),
                        replace(self.context, culinary_use="curry"),
                        replace(self.context, restrictions="sin gluten"),
                        replace(self.context, preparation="fresco")]:
            self.assertFalse(self.adapt(context)["cached"])
        self.client.settings = replace(self.client.settings, model="qwen3:1.7b")
        self.assertFalse(self.adapt()["cached"])
        self.assertEqual(self.client.generate.call_count, 6)

    def test_cache_is_invalidated_when_evidence_changes_and_expires(self):
        context = replace(self.context, query="jitomate")
        self.client.generate.return_value = {**proposal(), "original_name": "Jitomate", "local_name": "pomodoro"}
        self.adapt(context)
        changed = deepcopy(self.catalog)
        next(item for item in changed["ingredients"] if item["id"] == "jitomate")["note"] = "Nueva revisión"
        updated_index = IngredientSearch(changed["ingredients"], changed["relations"], changed["uses"])
        self.assertFalse(self.service.adapt(context, changed, updated_index, self.client)["cached"])
        self.service.ttl = 0
        self.assertFalse(self.adapt(context)["cached"])

    def test_cache_is_bounded_and_errors_are_not_cached(self):
        self.service.capacity = 1
        self.adapt()
        self.adapt(replace(self.context, query="otra consulta"))
        self.assertEqual(len(self.service.cache), 1)
        self.client.generate.side_effect = ModelError("timeout", "timeout")
        for _ in range(2):
            with self.assertRaises(ModelError):
                self.adapt()
        self.assertEqual(self.client.generate.call_count, 4)

    def test_directional_evidence_is_not_reused_for_other_countries_or_languages(self):
        for context in [replace(self.context, query="jitomate", destination_country="Alemania"),
                        replace(self.context, query="jitomate", origin_country="Italia"),
                        replace(self.context, query="jitomate", target_language="de")]:
            self.assertEqual(local_evidence(context, self.catalog, self.index)["ingredients"], [])

    def test_open_question_recovers_context_and_keeps_warnings_distinct(self):
        evidence = local_evidence(replace(self.context, query="¿Qué uso en vez de poblano para rajas?"), self.catalog, self.index)
        self.assertEqual(evidence["ingredients"][0]["original_name"], "Chile poblano")
        relations = evidence["ingredients"][0]["relations"]
        self.assertEqual({row["use"] for row in relations}, {"rajas"})
        evidence = local_evidence(replace(self.context, query="masa harina para tortillas"), self.catalog, self.index)
        self.assertEqual({r["type"] for r in evidence["ingredients"][0]["relations"]}, {"not_equivalent"})

    def test_identity_query_does_not_receive_unrequested_substitutions(self):
        evidence = local_evidence(replace(self.context, query="jitomate"), self.catalog, self.index)
        self.assertEqual(evidence["ingredients"][0]["relations"], [])
        self.client.generate.return_value = {**proposal(), "original_name": "Jitomate", "local_name": "pomodoro"}
        self.adapt(replace(self.context, query="jitomate"))
        schema = self.client.generate.call_args.args[1]
        self.assertEqual(schema["properties"]["local_name"], {"const": "pomodoro"})
        for changes in [{"culinary_use": "sugo"}, {"local_name": "pomodori pelati"}]:
            with self.assertRaises(ModelError):
                validate_result({**self.client.generate.return_value, **changes}, evidence)

    def test_schema_rejects_unknown_fields_urls_and_invented_sources(self):
        for changes in [{"confidence": 0.99}, {"source_ids": ["inventada"]},
                        {"summary": "Consulta https://inventado.example"},
                        {"original_name": " "}, {"kind": "verified"},
                        {"culinary_use": "null"},
                        {"alternatives": [{}]}, {"summary": "x" * 351}]:
            with self.subTest(changes=changes), self.assertRaises(ModelError):
                validate_result({**proposal(), **changes}, {"sources": {}})

    def test_substitute_requires_context_and_cannot_replace_original_name_contract(self):
        alternative = {"local_name": "peperone verde", "reason": "Conserva la forma.",
                       "adjustment": "Asar primero.", "limitation": "Cambia el sabor.", "source_ids": []}
        result = {**proposal(), "kind": "substitute", "local_name": None, "alternatives": [alternative]}
        with self.assertRaises(ModelError):
            validate_result(result, {"sources": {}})
        result["culinary_use"] = "rellenar"
        self.assertEqual(validate_result(result, {"sources": {}})["alternatives"][0]["local_name"], "peperone verde")
        for changes in [{"clarification": "¿Para qué plato?"}, {"kind": "no_proposal"},
                        {"local_name": "peperone verde"},
                        {"alternatives": [alternative, alternative]}]:
            with self.assertRaises(ModelError):
                validate_result({**result, **changes}, {"sources": {}})

    def test_abstention_and_clarification_are_valid_without_suggestions(self):
        result = {**proposal(), "kind": "no_proposal", "local_name": None,
                  "clarification": "¿En qué platillo lo usarás?"}
        self.assertIsNotNone(validate_result(result, {"sources": {}})["clarification"])

    def test_documented_non_equivalence_rejects_matching_proposals_for_requested_use(self):
        evidence = local_evidence(replace(self.context, query="masa harina para tortillas"), self.catalog, self.index)
        original_name = evidence["ingredients"][0]["original_name"]
        result = {**proposal(), "original_name": original_name, "local_name": "polenta"}
        with self.assertRaises(ModelError):
            validate_result(result, evidence)
        alternative = {"local_name": "polenta", "reason": "Supuesto reemplazo.",
                       "adjustment": None, "limitation": "Cambia la textura.", "source_ids": []}
        result.update(kind="substitute", local_name=None, culinary_use="tortillas", alternatives=[alternative])
        with self.assertRaises(ModelError):
            validate_result(result, evidence)

    def test_input_rejects_empty_overlong_and_nontext_values(self):
        for mapping in [{"query": " "}, {"query": "a" * 501}, {"query": ["jitomate"]},
                        {"query": "jitomate", "target_language": ""}]:
            with self.assertRaises(ValueError):
                AdaptationRequest.from_mapping(mapping)

    def test_generation_modes_cannot_mix_questions_and_replacements(self):
        schema = generation_schema({"ingredients": [], "sources": {}})
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        self.assertTrue(validator.is_valid(proposal()))
        self.assertFalse(validator.is_valid({**proposal(), "clarification": "¿Qué plato?"}))
        self.assertTrue(validator.is_valid({**proposal(), "kind": "no_proposal", "local_name": None,
                                           "clarification": "¿Qué plato?"}))

    def test_only_plain_names_use_minimal_generation(self):
        self.assertTrue(name_only(replace(self.context, query="anís estrellado")))
        for context in [replace(self.context, query="¿Qué uso en vez de poblano?"),
                        replace(self.context, query="masa harina para tortillas"),
                        replace(self.context, query="harina sin gluten"),
                        replace(self.context, culinary_use="curry"),
                        replace(self.context, preparation="seco"),
                        replace(self.context, restrictions="sin gluten")]:
            self.assertFalse(name_only(context))

    def test_original_term_is_not_labeled_as_its_own_replacement(self):
        context = replace(self.context, query="masa harina para tortillas")
        evidence = local_evidence(context, self.catalog, self.index)
        item = evidence["ingredients"][0]
        term = item["local_name"] or item["search_term"]
        raw = {**proposal(), "original_name": item["original_name"], "local_name": None,
               "kind": "substitute", "culinary_use": "tortillas", "alternatives": [{
                   "local_name": term, "reason": "El original.", "adjustment": None,
                   "limitation": "Comprobar el envase.", "source_ids": [],
               }]}
        result = normalize_result(raw, evidence, context)
        self.assertEqual(result["local_name"], term)
        self.assertEqual(result["kind"], "descriptive")
        self.assertEqual(result["alternatives"], [])

    def test_malformed_fields_are_rejected_before_normalization(self):
        self.client.generate.side_effect = None
        self.client.generate.return_value = {**proposal(), "original_name": None}
        with self.assertRaises(ModelError):
            self.adapt(replace(self.context, culinary_use="curry"))

    def test_known_alternative_uses_documented_notes_without_invented_adjustment(self):
        context = replace(self.context, query="chile poblano para rajas")
        evidence = local_evidence(context, self.catalog, self.index)
        item = evidence["ingredients"][0]
        documented = next(row for row in item["relations"] if row["type"] == "culinary_substitute")
        raw = {**proposal(), "original_name": item["original_name"], "local_name": None,
               "kind": "substitute", "culinary_use": "rajas", "warnings": ["Aviso inventado"],
               "alternatives": [{"local_name": documented["local_name"], "reason": "Motivo inventado",
                                 "adjustment": "Evitar el original", "limitation": "Límite inventado", "source_ids": []}]}
        result = normalize_result(raw, evidence, context)
        self.assertEqual(result["alternatives"][0]["reason"], documented["reason"])
        self.assertEqual(result["alternatives"][0]["adjustment"], documented["adjustment"])
        self.assertNotIn("inventado", json.dumps(result))
        restricted = normalize_result(raw, evidence, replace(context, restrictions="sin gluten"))
        self.assertEqual(restricted["alternatives"][0]["reason"], "Motivo inventado")
        self.client.generate.return_value = raw
        self.adapt(replace(context, query="¿Qué uso sin gluten en vez de poblano para rajas?"))
        schema = self.client.generate.call_args.args[1]
        substitute_mode = next(mode for mode in schema["oneOf"] if mode["properties"]["kind"].get("const") == "substitute")
        self.assertNotIn("enum", substitute_mode["properties"]["alternatives"]["items"]["properties"]["local_name"])


class TransportTests(unittest.TestCase):
    def test_settings_forbid_remote_urls_credentials_and_invalid_limits(self):
        for changes in [{"base_url": "https://api.example.com"},
                        {"base_url": "http://127.0.0.1:11434/path"},
                        {"base_url": "http://user:pass@localhost:11434"},
                        {"model": "qwen3:cloud"},
                        {"timeout": 0}, {"context_size": 1}, {"output_tokens": 1}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(ModelSettings(), **changes).validate()

    def client_with_envelope(self, envelope):
        client = OllamaClient(ModelSettings())
        client.thinking_mode = False
        client.opener = Mock()
        client.opener.open.return_value.__enter__ = Mock(return_value=io.BytesIO(json.dumps(envelope).encode()))
        client.opener.open.return_value.__exit__ = Mock(return_value=False)
        return client

    def test_payload_enforces_json_nonstreaming_and_bounded_generation(self):
        client = self.client_with_envelope({"done": True, "message": {"content": json.dumps(proposal())}})
        self.assertEqual(client.generate([], RESPONSE_SCHEMA), proposal())
        req = client.opener.open.call_args.args[0]
        payload = json.loads(req.data)
        self.assertFalse(payload["stream"])
        self.assertFalse(payload["think"])
        self.assertEqual(payload["format"], RESPONSE_SCHEMA)
        self.assertEqual(payload["options"]["temperature"], 0)
        self.assertEqual(client.opener.open.call_args.kwargs["timeout"], 120)

    def test_invalid_incomplete_and_truncated_envelopes_are_errors(self):
        for envelope in [{"done": False}, {"done": True, "done_reason": "length"},
                         {"done": True, "message": {"content": "not JSON"}}, []]:
            with self.assertRaises(ModelError) as error:
                self.client_with_envelope(envelope).generate([], RESPONSE_SCHEMA)
            self.assertEqual(error.exception.code, "invalid_response")

    def test_unavailable_timeout_missing_model_and_redirect_are_actionable(self):
        for failure, code in [(URLError("connection refused"), "unavailable"),
                              (BadStatusLine("invalid HTTP response"), "invalid_response"),
                              (TimeoutError(), "timeout"),
                              (HTTPError("http://localhost", 404, "missing", {}, None), "model_missing"),
                              (HTTPError("http://localhost", 302, "redirect", {}, None), "server_error")]:
            client = OllamaClient(ModelSettings())
            client.opener.open = Mock(side_effect=failure)
            with self.assertRaises(ModelError) as error:
                client.generate([], RESPONSE_SCHEMA)
            self.assertEqual(error.exception.code, code)

    def test_thinking_only_models_use_supported_mode_and_only_final_content(self):
        for values, expected in [([True], True), ([True, False], False), ([], None)]:
            client = OllamaClient(ModelSettings())
            envelopes = [
                {"thinking": {"values": values}},
                {"done": True, "message": {"thinking": "Private intermediate reasoning", "content": json.dumps(proposal())}},
            ]
            responses = []
            for envelope in envelopes:
                response = Mock()
                response.__enter__ = Mock(return_value=io.BytesIO(json.dumps(envelope).encode()))
                response.__exit__ = Mock(return_value=False)
                responses.append(response)
            client.opener.open = Mock(side_effect=responses)
            self.assertEqual(client.generate([], RESPONSE_SCHEMA), proposal())
            payload = json.loads(client.opener.open.call_args.args[0].data)
            if expected is None:
                self.assertNotIn("think", payload)
            else:
                self.assertIs(payload["think"], expected)


class AdaptationRouteTests(unittest.TestCase):
    def setUp(self):
        self.browser = app.test_client()

    def test_get_does_not_generate_and_existing_pages_work(self):
        with patch("app.OllamaClient") as client:
            self.assertEqual(self.browser.get("/adaptar?q=hojas+de+curry").status_code, 200)
            client.assert_not_called()
        for path in ["/", "/busqueda?q=jitomate", "/catalogo", "/recetas", "/evaluacion"]:
            self.assertEqual(self.browser.get(path).status_code, 200)

    def test_generation_shows_unverified_result_and_escapes_model_text(self):
        response = {"result": {**proposal(), "summary": "<script>alert(1)</script>"},
                    "sources": {}, "model": "test", "elapsed_seconds": 0.1, "cached": False}
        with patch("app.adaptation_service.adapt", return_value=response):
            page = self.browser.post("/adaptar", data={"query": "hojas de curry"})
        self.assertEqual(page.status_code, 200)
        self.assertIn("foglie di curry", page.get_data(as_text=True))
        self.assertIn("pendiente de verificación", page.get_data(as_text=True))
        self.assertNotIn("<script>alert(1)</script>", page.get_data(as_text=True))

    def test_failures_preserve_query_and_offer_catalog_without_remote_fallback(self):
        for code, expected in [("unavailable", 503), ("timeout", 504), ("invalid_response", 502)]:
            with patch("app.adaptation_service.adapt", side_effect=ModelError(code, "Prueba de fallo")):
                page = self.browser.post("/adaptar", data={"query": "hojas de curry"})
            self.assertEqual(page.status_code, expected)
            self.assertIn('value="hojas de curry"', page.get_data(as_text=True))
            self.assertIn("Consultar catálogo", page.get_data(as_text=True))

    def test_bad_input_is_rejected_before_inference(self):
        with patch("app.adaptation_service.adapt") as adapt:
            self.assertEqual(self.browser.post("/adaptar", data={"query": " "}).status_code, 400)
            self.assertEqual(self.browser.post("/adaptar", data={"query": "a" * 501}).status_code, 400)
            adapt.assert_not_called()

    def test_substitution_card_keeps_original_and_alternative_separate(self):
        result = {**proposal(), "original_name": "Chile poblano", "local_name": None,
                  "kind": "substitute", "culinary_use": "rajas", "alternatives": [{
                      "local_name": "Peperone verde", "reason": "Conserva el volumen.",
                      "adjustment": None, "limitation": "Cambia el sabor.", "source_ids": []}]}
        response = {"result": result, "sources": {}, "model": "test", "elapsed_seconds": 1,
                    "cached": False, "name_only": False}
        with patch("app.adaptation_service.adapt", return_value=response):
            page = self.browser.post("/adaptar", data={"query": "poblano para rajas"})
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Chile poblano", html)
        self.assertIn("Peperone verde", html)
        self.assertIn("Por qué puede servir", html)


if __name__ == "__main__":
    unittest.main()
