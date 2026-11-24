"""Run a real local inference smoke check; this is not culinary acceptance scoring."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adaptation import AdaptationRequest, AdaptationService
from ingredient_views import get_catalog
from local_model import ModelError, ModelSettings, OllamaClient


class InspectionClient(OllamaClient):
    last_response = None

    def generate(self, messages, schema):
        self.last_response = super().generate(messages, schema)
        return self.last_response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", action="append", help="Consulta; puede repetirse.")
    parser.add_argument("--destination", default="Italia")
    parser.add_argument("--target-language", default="it")
    parser.add_argument("--output", type=Path, help="Guardar respuestas para revisión humana.")
    parser.add_argument("--diagnostics", action="store_true", help="Incluir salidas rechazadas y motivo en el archivo local.")
    args = parser.parse_args()
    try:
        client = InspectionClient(ModelSettings.from_env())
    except ModelError as error:
        print(str(error))
        return 1
    catalog, index = get_catalog()
    service = AdaptationService()
    queries = args.query or [
        "jitomate", "¿Qué uso en vez de poblano para rajas?",
        "masa harina para tortillas", "anís estrellado",
    ]
    rows = []
    for query in queries:
        client.last_response = None
        context = AdaptationRequest(query=query, destination_country=args.destination,
                                    target_language=args.target_language)
        try:
            response = service.adapt(context, catalog, index, client)
            rows.append({"context": asdict(context), **response})
            print(f"OK | {query} | {response['elapsed_seconds']} s | {response['result']['kind']}")
        except ModelError as error:
            failed = {"context": asdict(context), "error": error.code, "message": str(error)}
            if args.diagnostics:
                failed.update(rejected_response=client.last_response, diagnostic=str(error.__cause__))
            rows.append(failed)
            print(f"ERROR | {query} | {error.code}: {error}")
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("La validez técnica no acredita aceptación culinaria; revisar las propuestas manualmente.")
    return int(any("error" in row for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
