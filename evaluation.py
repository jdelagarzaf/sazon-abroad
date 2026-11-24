"""Run the labeled retrieval benchmark from the CLI or web app."""

import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path
from statistics import mean

from search import IngredientSearch, METHODS, normalize

DATA_DIR = Path(__file__).resolve().parent / "data"
DEVELOPMENT_PATH = DATA_DIR / "evaluation.csv"
FINAL_PATH = DATA_DIR / "evaluation_final.csv"
SNAPSHOT_PATH = DATA_DIR / "evaluation_snapshot.json"
CONTEXT_KINDS = {"contexto", "ajuste", "sin sustituto"}
FINAL_KINDS = {"identidad", "sin resultado"} | CONTEXT_KINDS
GROUPS = {"habitual": "Habituales", "especializado": "Especializadas"}


def load_cases(path=DEVELOPMENT_PATH):
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def case_ids(case, field):
    return set(filter(None, case.get(field, "").split("|")))


def evaluate(catalog, cases, engine=None, *, systems=None, match_display=False):
    if systems is None:
        if engine is None:
            engine = IngredientSearch(catalog["ingredients"], catalog["relations"], catalog.get("uses"))
        systems = {label: (engine, method) for method, label in METHODS.items()}
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
        substitutes = case_ids(case, "expected_substitutes")
        warnings = case_ids(case, "expected_warnings")
        adjustments = case_ids(case, "expected_adjustments")
        unknown = (set(expected) | substitutes | warnings | adjustments) - ingredients.keys()
        if unknown:
            raise ValueError(f"{query!r} tiene IDs desconocidos: {', '.join(sorted(unknown))}")
        contextual = case["kind"] in CONTEXT_KINDS
        if adjustments - substitutes or substitutes & warnings:
            raise ValueError(f"Etiquetas de sustitución, ajuste o advertencia incompatibles en {query!r}.")
        for label, (system, method) in systems.items():
            lookup = system.lookup(query, limit=3, method=method)
            returned = [hit.ingredient["id"] for hit in lookup.hits]
            top_one = bool(returned and returned[0] in expected)
            recall = len(set(expected).intersection(returned)) / len(expected) if expected else None
            relationships = []
            if contextual and returned and (lookup.use or (match_display and not lookup.context)):
                relationships = system.relations_for(returned[0], lookup.use)
            found_subs = {rel["to"] for rel in relationships if rel["type"] == "culinary_substitute"}
            found_warnings = {rel["to"] for rel in relationships if rel["type"] == "not_equivalent"}
            found_adjustments = {
                rel["to"] for rel in relationships
                if rel["type"] == "culinary_substitute" and rel.get("adaptation")
            }
            relevant_subs = found_subs if top_one else set()
            relevant_warnings = found_warnings if top_one else set()
            missed_adjustments = (adjustments & relevant_subs) - found_adjustments
            correct_context = None
            correct = top_one if expected else not returned
            if contextual:
                correct_context = top_one and found_subs == substitutes and found_warnings == warnings and not missed_adjustments
                correct = correct_context
            details.append({
                "query": query, "kind": case["kind"], "method": label,
                "group": case.get("group"),
                "source_ids": sorted(case_ids(case, "source_ids")),
                "expected": expected, "returned": returned,
                "expected_substitutes": sorted(substitutes), "substitutes": sorted(found_subs),
                "expected_warnings": sorted(warnings), "warnings": sorted(found_warnings),
                "expected_adjustments": sorted(adjustments), "adjustments": sorted(found_adjustments),
                "covered_adjustments": len(adjustments & found_adjustments) if top_one else 0,
                "wrong_substitutes": sorted(found_subs - (substitutes if top_one else set())),
                "missed_substitutes": sorted(substitutes - relevant_subs),
                "missed_adjustments": sorted(missed_adjustments),
                "missed_warnings": sorted(warnings - relevant_warnings),
                "correct_no_substitute": (top_one and not found_subs) if contextual and not substitutes else None,
                "top1": top_one, "recall_at_3": recall,
                "correct_context": correct_context,
                "correct": correct,
            })

    summary = []
    for label in systems:
        method_cases = [row for row in details if row["method"] == label]
        answerable = [row for row in method_cases if row["expected"]]
        unanswerable = [row for row in method_cases if not row["expected"]]
        contextual = [row for row in method_cases if row["correct_context"] is not None]
        required_adjustments = sum(len(row["expected_adjustments"]) for row in contextual)
        summary.append({
            "method": label,
            "top1": average(row["top1"] for row in answerable),
            "recall_at_3": average(row["recall_at_3"] for row in answerable),
            "no_result": average(not row["returned"] for row in unanswerable),
            "context": average(row["correct_context"] for row in contextual),
            "no_substitute": average(
                row["correct_no_substitute"] for row in contextual if row["correct_no_substitute"] is not None
            ),
            "adjustment_coverage": (
                sum(row["covered_adjustments"] for row in contextual) / required_adjustments
                if required_adjustments else None
            ),
            **{
                key: sum(len(row[key]) for row in contextual)
                for key in ("wrong_substitutes", "missed_substitutes", "missed_adjustments", "missed_warnings")
            },
        })

    mexican = [row for row in ingredients.values() if row["scope"] == "México"]
    sources = catalog["sources"]
    covered = sum(any(sources.get(key, {}).get("url") for key in row["sources"]) for row in mexican)
    relations = [rel for rel in catalog["relations"] if rel["type"] == "culinary_substitute"]
    reviewed = [rel for rel in relations if rel.get("human_review") in {"accepted", "rejected"}]
    return {
        "count": len(cases),
        "answerable": sum(bool(case["expected_ids"]) for case in cases),
        "contextual": sum(case["kind"] in CONTEXT_KINDS for case in cases),
        "contextual_abstentions": sum(
            case["kind"] in CONTEXT_KINDS and not case_ids(case, "expected_substitutes") for case in cases
        ),
        "required_adjustments": sum(len(case_ids(case, "expected_adjustments")) for case in cases),
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


def evaluate_final(group=""):
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    cases_text = FINAL_PATH.read_text(encoding="utf-8")
    if sha256(cases_text.encode("utf-8")).hexdigest() != snapshot["cases_sha256"]:
        raise ValueError("Las consultas finales no coinciden con la versión evaluada.")
    cases = list(csv.DictReader(cases_text.splitlines()))
    development = {normalize(case["query"]) for case in load_cases()}
    catalog = snapshot["enriched"]
    if group and group not in GROUPS:
        raise ValueError(f"Grupo de evaluación desconocido: {group!r}")
    for case in cases:
        kind = case["kind"]
        if (
            normalize(case["query"]) in development
            or case["group"] not in GROUPS
            or kind not in FINAL_KINDS
            or bool(case["expected_ids"]) != (kind != "sin resultado")
            or bool(case["expected_adjustments"]) != (kind == "ajuste")
            or bool(case["expected_substitutes"]) != (kind in {"contexto", "ajuste"})
        ):
            raise ValueError(f"Consulta final duplicada o con etiquetas incoherentes: {case['query']!r}")
        if case_ids(case, "source_ids") - catalog["sources"].keys():
            raise ValueError(f"Fuentes desconocidas para {case['query']!r}.")

    baseline = snapshot["baseline"]
    literal = [
        {**item, "reference_it": None, "aliases_es": [], "aliases_it": []}
        for item in baseline["ingredients"] if item["name_it"]
    ]
    systems = {
        "Traducción literal (catálogo base)": (IngredientSearch(literal), "exact"),
        "BM25 + contexto (catálogo base)": (
            IngredientSearch(baseline["ingredients"], baseline["relations"], baseline["uses"]), "bm25",
        ),
        "BM25 + contexto (catálogo ampliado)": (
            IngredientSearch(catalog["ingredients"], catalog["relations"], catalog["uses"]), "bm25",
        ),
    }
    scored = [case for case in cases if not group or case["group"] == group]
    report = evaluate(catalog, scored, systems=systems, match_display=True)
    report.update(
        baseline_revision=snapshot["baseline_revision"],
        catalog_sha256=snapshot["catalog_sha256"],
        cases_sha256=snapshot["cases_sha256"],
        names={item["id"]: item["name_es"] for item in baseline["ingredients"] + catalog["ingredients"]},
        sources=catalog["sources"],
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--final", action="store_true", help="Compara los catálogos congelados.")
    parser.add_argument("--group", choices=GROUPS, help="Filtra el conjunto final por dificultad.")
    args = parser.parse_args()
    if args.group and not args.final:
        parser.error("--group requiere --final.")
    if args.final:
        result = evaluate_final(args.group or "")
    else:
        catalog = json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))
        result = evaluate(catalog, load_cases())
    print(json.dumps(result, ensure_ascii=True, indent=2))
