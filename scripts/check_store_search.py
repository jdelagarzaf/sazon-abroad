"""Explicit one-credit activation check. No secrets are printed."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from store_search import StoreSearchError, StoreSearchService
from retailers import commercial_result, retailer_options, resolve_retailers


def main():
    parser = argparse.ArgumentParser(description="Comprueba Tavily: hasta una búsqueda basic nueva.")
    parser.add_argument("--product", default="tortilla di mais")
    parser.add_argument("--city", default="Milano")
    parser.add_argument("--country", default="Italia")
    parser.add_argument("--domain", action="append", default=[], help="Dominio de comercio para destinos sin cadenas preconfiguradas.")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False)
    try:
        stores = resolve_retailers(args.country, [row["id"] for row in retailer_options(args.country)], ",".join(args.domain))
        domains = sorted({domain for store in stores for domain in store["domains"]})
        result = StoreSearchService().search(args.product, args.city, args.country, domains=domains)
        results = [hit for candidate in result["results"] if (hit := commercial_result(candidate, args.product, stores))]
    except (StoreSearchError, ValueError) as error:
        print(error)
        return 1
    print("Tavily: respuesta válida. " + ("Caché local; sin nueva petición." if result["cached"] else "Consulta real nueva."))
    print("Fecha:", result["queried_at"])
    print("Fichas o catálogos pertinentes:", len(results))
    print("Descartados por pertinencia:", len(result["results"]) - len(results))
    for item in results:
        print(item["url"])
    print("Stock, pertinencia comercial y envío pendientes de comprobar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
