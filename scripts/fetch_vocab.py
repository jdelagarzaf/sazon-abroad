"""Find vocabulary candidates for catalog ingredients in Wikidata and AGROVOC."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fetch_data import API_URL, ROOT, fetch_entities, write_json

AGROVOC_API = "https://agrovoc.fao.org/browse/rest/v1"
USER_AGENT = "SazonAbroad/0.5 (https://github.com/jdelagarzaf/sazon-abroad)"


def request_json(endpoint, **params):
    request = Request(
        f"{endpoint}?{urlencode(params)}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urlopen(request, timeout=15) as response:
        payload = json.load(response)
    if "error" in payload:
        raise ValueError(payload["error"].get("info", "Error del servicio de vocabulario"))
    return payload


def wikidata_candidates(term):
    payload = request_json(
        API_URL, action="wbsearchentities", format="json", search=term, language="es", limit=5,
    )
    hits = payload["search"]
    entities = fetch_entities([item["id"] for item in hits])
    return [
        {
            "id": item["id"],
            "label": item["label"],
            "label_it": entities[item["id"]]["labels"].get("it", {}).get("value"),
            "description": item.get("description", ""),
            "url": f"https://www.wikidata.org/wiki/{item['id']}",
        }
        for item in hits
    ]


def agrovoc_candidates(term):
    payload = request_json(f"{AGROVOC_API}/search", query=term, lang="es", vocab="agrovoc", maxhits=5)
    candidates = []
    for item in payload["results"]:
        labels = request_json(f"{AGROVOC_API}/agrovoc/label", uri=item["uri"], lang="it")
        candidates.append({
            "id": item["localname"],
            "label": item["prefLabel"],
            "label_it": labels.get("prefLabel"),
            "url": f"https://agrovoc.fao.org/browse/agrovoc/es/page/{item['localname']}",
        })
    return candidates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ids", nargs="+", help="IDs del catálogo a consultar.")
    parser.add_argument("--provider", choices=("both", "wikidata", "agrovoc"), default="both")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        catalog = json.loads((ROOT / "data/catalog.json").read_text(encoding="utf-8"))
        ingredients = {row["id"]: row for row in catalog["ingredients"]}
        unknown = set(args.ids) - ingredients.keys()
        if unknown:
            raise ValueError(f"Ingredientes desconocidos: {', '.join(sorted(unknown))}")
        providers = {"wikidata": wikidata_candidates, "agrovoc": agrovoc_candidates}
        if args.provider != "both":
            providers = {args.provider: providers[args.provider]}
        results = {}
        for ingredient_id in dict.fromkeys(args.ids):
            term = ingredients[ingredient_id]["name_es"]
            results[ingredient_id] = {
                "query": term,
                **{name: lookup(term) for name, lookup in providers.items()},
            }
        if args.output:
            write_json(args.output, results)
        else:
            print(json.dumps(results, ensure_ascii=True, indent=2))
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"No se pudo obtener el vocabulario: {exc}\n")


if __name__ == "__main__":
    main()
