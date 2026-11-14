"""Run the labeled retrieval benchmark from the CLI or Streamlit."""

import csv
import json
from pathlib import Path
from statistics import mean

from search import IngredientSearch, METHODS, normalize

DATA_DIR = Path(__file__).resolve().parent / "data"


def load_cases(path=DATA_DIR / "evaluation.csv"):
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def evaluate(catalog, cases, engine=None):
    if engine is None:
        engine = IngredientSearch(catalog["ingredients"], catalog["relations"], catalog.get("uses"))
    ingredients = {row["id"]: row for row in catalog["ingredients"]}
    seen_queries = set()
    details = []
    for case in cases:
        query = case["query"]
        normalized = normalize(query)
        if not normalized or normalized in seen_queries:
            raise ValueError(f"Consulta vacía o duplicada: {query!r}")
        seen_queries.add(normalized)
        expected = case["expected_ids"].split("|") if case["expected_ids"] else []
        substitutes = set(filter(None, case["expected_substitutes"].split("|")))
        warnings = set(filter(None, case["expected_warnings"].split("|")))
        unknown = (set(expected) | substitutes | warnings) - ingredients.keys()
        if unknown:
            raise ValueError(f"{query!r} tiene IDs desconocidos: {', '.join(sorted(unknown))}")
        contextual = case["kind"] == "contexto"
        for method, label in METHODS.items():
            lookup = engine.lookup(query, limit=3, method=method)
            returned = [hit.ingredient["id"] for hit in lookup.hits]
            top_one = bool(returned and returned[0] in expected)
            recall = len(set(expected).intersection(returned)) / len(expected) if expected else None
            relationships = []
            if contextual and returned and lookup.use:
                relationships = engine.relations_for(returned[0], lookup.use)
            found_subs = {rel["to"] for rel in relationships if rel["type"] == "culinary_substitute"}
            found_warnings = {rel["to"] for rel in relationships if rel["type"] == "not_equivalent"}
            correct_context = None
            correct = top_one if expected else not returned
            if contextual:
                correct_context = top_one and found_subs == substitutes and found_warnings == warnings
                correct = correct_context
            details.append({
                "query": query, "kind": case["kind"], "method": label,
                "expected": expected, "returned": returned,
                "expected_substitutes": sorted(substitutes), "substitutes": sorted(found_subs),
                "expected_warnings": sorted(warnings), "warnings": sorted(found_warnings),
                "top1": top_one, "recall_at_3": recall,
                "correct_context": correct_context,
                "correct": correct,
            })

    summary = []
    for label in METHODS.values():
        method_cases = [row for row in details if row["method"] == label]
        answerable = [row for row in method_cases if row["expected"]]
        unanswerable = [row for row in method_cases if not row["expected"]]
        contextual = [row for row in method_cases if row["correct_context"] is not None]
        summary.append({
            "method": label,
            "top1": average(row["top1"] for row in answerable),
            "recall_at_3": average(row["recall_at_3"] for row in answerable),
            "no_result": average(not row["returned"] for row in unanswerable),
            "context": average(row["correct_context"] for row in contextual),
        })

    mexican = [row for row in ingredients.values() if row["scope"] == "México"]
    sources = catalog["sources"]
    covered = sum(any(sources.get(key, {}).get("url") for key in row["sources"]) for row in mexican)
    relations = [rel for rel in catalog["relations"] if rel["type"] == "culinary_substitute"]
    reviewed = [rel for rel in relations if rel.get("human_review") in {"accepted", "rejected"}]
    return {
        "count": len(cases),
        "answerable": sum(bool(case["expected_ids"]) for case in cases),
        "contextual": sum(case["kind"] == "contexto" for case in cases),
        "catalog_count": len(mexican),
        "source_count": covered,
        "substitutions": len(relations),
        "human_reviewed": len(reviewed),
        "accepted_share": average(rel["human_review"] == "accepted" for rel in reviewed),
        "summary": summary,
        "details": details,
    }


def average(values):
    items = list(values)
    return mean(items) if items else None


if __name__ == "__main__":
    catalog = json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))
    print(json.dumps(evaluate(catalog, load_cases()), ensure_ascii=True, indent=2))
