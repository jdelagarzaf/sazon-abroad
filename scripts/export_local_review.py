"""Create a review worksheet without assigning human labels."""
import csv
import json
from pathlib import Path
import argparse

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default=str(ROOT / "docs" / "local-ai-results.json"))
    parser.add_argument("--output", default=str(ROOT / "docs" / "revision-culinaria.csv"))
    args = parser.parse_args()
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    output = Path(args.output)
    if output.exists():
        raise SystemExit("El archivo ya existe. Usa --output con una ruta nueva para conservar la revisión.")
    fields = ["case", "variant", "query", "use", "restrictions", "local_name", "kind", "clarification", "warnings", "sources", "alternatives", "error",
              "identity_correct", "culinary_useful", "adjustment_correct", "restrictions_respected",
              "abstention_correct", "sources_supported", "accepted", "reviewer", "review_date", "notes"]
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in report["rows"]:
            result = row.get("response", {}).get("result", {})
            values = {"case": row["case"], "variant": row["variant"], "query": row["input"]["query"],
                "use": row["input"]["culinary_use"], "restrictions": row["input"]["restrictions"],
                "local_name": result.get("local_name"), "alternatives": json.dumps(result.get("alternatives", []), ensure_ascii=False),
                "kind": result.get("kind"), "clarification": result.get("clarification"),
                "warnings": json.dumps(result.get("warnings", []), ensure_ascii=False),
                "sources": json.dumps(row.get("response", {}).get("sources", {}), ensure_ascii=False),
                "error": row.get("error", "")}
            writer.writerow({key: ("'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value)
                             for key, value in values.items()})


if __name__ == "__main__":
    main()
