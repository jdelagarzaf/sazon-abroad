"""Reproducible, resumable local evaluation. Never assigns culinary approval."""
import argparse
from datetime import datetime, timezone
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from adaptation import AdaptationRequest, AdaptationService, PROMPT_VERSION
from ingredient_views import get_catalog
from local_model import ModelError, ModelSettings, OllamaClient
from recipe_workspace import extract_recipe, shopping_list, translate_draft
from search import IngredientSearch, normalize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(ROOT / "docs" / "local-ai-results.json"))
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--variant", choices=["hybrid", "model_only", "both"], default="both")
    parser.add_argument("--translate-recipes", action="store_true", help="También ejecuta IA local sobre las cinco recetas reservadas.")
    args = parser.parse_args()
    if not 1 <= args.limit <= 50:
        parser.error("--limit debe estar entre 1 y 50")
    load_dotenv(ROOT / ".env", override=False)
    path = ROOT / "data" / "local_ai_reserved.json"
    frozen = json.loads(path.read_text(encoding="utf-8"))
    digest = sha256(path.read_bytes()).hexdigest()
    catalog, index = get_catalog()
    empty = {**catalog, "ingredients": [], "relations": []}
    empty_index = IngredientSearch([])
    output = Path(args.output)
    report = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {
        "dataset_sha256": digest, "prompt": PROMPT_VERSION, "model": asdict(ModelSettings.from_env()),
        "human_acceptance": None, "rows": [], "recipes": []}
    if report["dataset_sha256"] != digest or report["prompt"] != PROMPT_VERSION or report["model"] != asdict(ModelSettings.from_env()):
        raise SystemExit("Dataset/prompt/model changed. Use a new report path.")
    cases = [("mx_it", row) for row in frozen["mx_it"]] + [("mx_de", row) for row in frozen["mx_de"]]
    variants = ["hybrid", "model_only"] if args.variant == "both" else [args.variant]
    done = {(row["case"], row["variant"]) for row in report["rows"]}
    def save():
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(output)
    client = OllamaClient(ModelSettings.from_env())
    for number, (group, case) in enumerate(cases[:args.limit], 1):
        context = AdaptationRequest.from_mapping({**case, **({"destination_country": "Alemania", "target_language": "de"} if group == "mx_de" else {})})
        for variant in variants:
            if (number, variant) in done:
                continue
            row = {"case": number, "group": group, "variant": variant, "input": asdict(context),
                   "kind": case.get("kind", "identity"), "expected_provisional": case.get("expected"),
                   "human_review": None, "culinary_accepted": None}
            started = time.monotonic()
            try:
                service = AdaptationService()
                response = service.adapt(context, catalog if variant == "hybrid" else empty,
                                         index if variant == "hybrid" else empty_index, client)
                row.update(response=response, published_schema_valid=True)
                term = response["result"]["local_name"] or ""
                row["provisional_term_match"] = normalize(case["expected"]) in normalize(term) if case.get("expected") else None
                # A repeat measures service cache, not another model inference.
                cached_start = time.monotonic()
                service.adapt(context, catalog if variant == "hybrid" else empty,
                              index if variant == "hybrid" else empty_index, client)
                row["cache_seconds"] = time.monotonic() - cached_start
            except (ModelError, ValueError) as exc:
                row.update(error=str(exc), error_code=getattr(exc, "code", "input"), published_schema_valid=False)
            row["seconds"] = time.monotonic() - started
            report["rows"].append(row)
            save()
            print(f"{number}/50 {variant}: {row['seconds']:.2f}s {'error' if 'error' in row else 'published'}", flush=True)
    previous_recipes = {row["title"]: row for row in report.get("recipes", [])}
    report["recipes"] = []
    recipe_service = AdaptationService()
    for case in frozen["recipes"]:
        previous = previous_recipes.get(case["title"])
        if previous and previous.get("generated_rows") and (not args.translate_recipes or not previous.get("error")):
            previous["shopping"] = shopping_list({"rows": previous["generated_rows"]})
            report["recipes"].append(previous)
            continue
        draft = extract_recipe(case["text"])
        original = [row["amount"] for row in draft["rows"]]
        recipe_error = None
        if args.translate_recipes:
            try:
                translate_draft(draft, recipe_service, catalog, index, client, lambda message: print(message, flush=True))
            except (ModelError, ValueError) as exc:
                recipe_error = str(exc)
        else:
            for row in draft["rows"]:
                row["local_name"] = row["name"]  # Test arithmetic, NOT a model translation.
        report["recipes"].append({"title": case["title"], "rows": len(original), "original_amounts": original,
                                  "shopping": shopping_list(draft), "steps_preserved": draft["steps"],
                                  "quantities_preserved": original == [row["amount"] for row in draft["rows"]],
                                  "generated_rows": draft["rows"] if args.translate_recipes else None, "error": recipe_error,
                                  "scope": "local translations plus deterministic extraction" if args.translate_recipes else
                                           "deterministic extraction/consolidation; generation not assessed"})
        save()
    report["retrieval_baseline"] = []
    for number, (group, case) in enumerate(cases, 1):
        query = case["query"] + (" para " + case["culinary_use"] if case.get("culinary_use") else "")
        lookup = index.lookup(query)
        top = lookup.hits[0].ingredient if lookup.hits else None
        report["retrieval_baseline"].append({"case": number, "group": group, "query": query,
            "top_id": top["id"] if top else None,
            "local_name": (top.get("name_it") or top.get("reference_it")) if top and group == "mx_it" else None,
            "supported_task": group == "mx_it" and not case.get("restrictions") and case.get("kind") not in {"ambiguity", "abstention"},
            "note": "Catalog retrieval only; no generated answer, no German translation or dietary constraint reasoning."})
    report["summary"] = {}
    for variant in sorted({row["variant"] for row in report["rows"]}):
        rows = [row for row in report["rows"] if row["variant"] == variant]
        times = sorted(row["seconds"] for row in rows)
        matches = [row["provisional_term_match"] for row in rows if row.get("provisional_term_match") is not None]
        report["summary"][variant] = {"attempts": len(rows), "published": sum(row["published_schema_valid"] for row in rows),
            "errors": sum("error" in row for row in rows), "p50_seconds": statistics.median(times),
            "p95_seconds": times[max(0, __import__('math').ceil(.95 * len(times)) - 1)],
            "provisional_term_matches": sum(matches), "provisional_term_total": len(matches),
            "human_acceptance": None, "note": "Term containment and schema validity do not establish culinary correctness."}
        cached_times = sorted(row["cache_seconds"] for row in rows if "cache_seconds" in row)
        report["summary"][variant]["cache_p50_seconds"] = statistics.median(cached_times) if cached_times else None
        report["summary"][variant]["cache_p95_seconds"] = cached_times[max(0, __import__('math').ceil(.95 * len(cached_times)) - 1)] if cached_times else None
    report["timer"] = {"implementation": time.get_clock_info("monotonic").implementation,
                       "resolution_seconds": time.get_clock_info("monotonic").resolution}
    report["recorded_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save()


if __name__ == "__main__":
    main()
