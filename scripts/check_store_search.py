"""Explicit one-credit activation check. No secrets are printed."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from store_search import StoreSearchError, StoreSearchService


def main():
    parser = argparse.ArgumentParser(description="Comprueba Tavily: hasta una búsqueda basic nueva.")
    parser.add_argument("--product", default="tortilla di mais")
    parser.add_argument("--city", default="Milano")
    parser.add_argument("--country", default="Italia")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False)
    try:
        result = StoreSearchService().search(args.product, args.city, args.country)
    except StoreSearchError as error:
        print(error)
        return 1
    print("Tavily: respuesta válida. " + ("Caché local; sin nueva petición." if result["cached"] else "Consulta real nueva."))
    print("Fecha:", result["queried_at"])
    print("Enlaces candidatos:", len(result["results"]))
    for item in result["results"]:
        print(item["url"])
    print("Stock, pertinencia comercial y envío pendientes de comprobar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
