"""Build the local catalog from curated ingredients and the Wikidata Action API."""

import argparse
import csv
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
API_URL = "https://www.wikidata.org/w/api.php"
SNAPSHOT_PATH = ROOT / "data/wikidata_snapshot.json"


def fetch_entities(ids):
    entities = {}
    for start in range(0, len(ids), 50):
        batch = ids[start:start + 50]
        params = urlencode({
            "action": "wbgetentities",
            "format": "json",
            "ids": "|".join(batch),
            "props": "info|labels|aliases",
            "languages": "es|it",
        })
        request = Request(
            f"{API_URL}?{params}",
            headers={"User-Agent": "SazonAbroad/0.1 (academic ingredient catalog)"},
        )
        with urlopen(request, timeout=20) as response:
            payload = json.load(response)
        if "error" in payload:
            raise ValueError(payload["error"].get("info", "Error de Wikidata"))
        for qid in batch:
            item = payload.get("entities", {}).get(qid, {})
            if not item or "missing" in item:
                raise ValueError(f"Wikidata no devolvió el concepto {qid}")
            entities[qid] = {
                "lastrevid": item["lastrevid"],
                "labels": item.get("labels", {}),
                "aliases": item.get("aliases", {}),
            }
    return entities


def terms_for(entity, language):
    terms = {alias["value"].casefold() for alias in entity.get("aliases", {}).get(language, [])}
    label = entity.get("labels", {}).get(language)
    if label:
        terms.add(label["value"].casefold())
    return terms


def distinct_aliases(aliases, primary):
    seen = {primary.casefold()} if primary else set()
    result = []
    for part in aliases.split("|"):
        term = " ".join(part.split())
        normalized = term.casefold()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(term)
    return result


def build_catalog(rows, annotations, entities):
    sources = dict(annotations["sources"])
    ingredient_ids = set()
    seen_qids = set()
    ingredients = []
    for row in rows:
        ingredient_id = row["id"]
        if not ingredient_id or ingredient_id in ingredient_ids:
            raise ValueError(f"ID de ingrediente vacío o duplicado: {ingredient_id!r}")
        ingredient_ids.add(ingredient_id)
        local = annotations["local_ingredients"].get(ingredient_id, {})
        ingredient_sources = list(local.get("sources", []))
        qid = row["wikidata_id"]
        entity = entities.get(qid, {})
        if qid:
            if not entity or qid in seen_qids:
                raise ValueError(f"{ingredient_id}: concepto de Wikidata ausente o duplicado ({qid}).")
            seen_qids.add(qid)
            sources[qid] = {
                "label": f"Wikidata · {qid}",
                "url": f"https://www.wikidata.org/wiki/{qid}",
                "license": "CC0-1.0",
                "revision": entity["lastrevid"],
                "revision_url": f"https://www.wikidata.org/w/index.php?oldid={entity['lastrevid']}",
            }
            ingredient_sources.append(qid)

        # A preferred Italian name is included only if it is still attested as a label or alias.
        term_it = row["term_it"].strip()
        reference = local.get("reference_it")
        reference_kind = local.get("reference_kind")
        attested_term = reference if reference_kind == "scientific" else term_it
        if attested_term and attested_term.casefold() not in terms_for(entity, "it"):
            raise ValueError(f"{row['id']}: Wikidata ya no contiene el término {attested_term!r}")

        if term_it:
            verification = "retrieved"
        elif ingredient_sources:
            verification = "source_supported"
        else:
            verification = "pending"

        ingredients.append({
            "id": ingredient_id,
            "name_es": row["name_es"],
            "name_it": term_it or None,
            "aliases_es": distinct_aliases(row["aliases_es"], row["name_es"]),
            "aliases_it": distinct_aliases(row["aliases_it"], term_it or reference),
            "category": row["category"],
            "scope": row["scope"],
            "note": row["note"],
            "reference_it": reference,
            "reference_kind": reference_kind,
            "note_it": local.get("note_it"),
            "wikidata_id": qid or None,
            "wikidata_labels": {lang: data["value"] for lang, data in entity.get("labels", {}).items()},
            "sources": ingredient_sources,
            "verification": verification,
        })

    unknown_annotations = annotations["local_ingredients"].keys() - ingredient_ids
    if unknown_annotations:
        raise ValueError(f"Anotaciones sin ingrediente: {', '.join(sorted(unknown_annotations))}")
    uses = annotations.get("uses", {})
    relationship_keys = set()
    for relation in annotations["relations"]:
        origin, target = relation["from"], relation["to"]
        if {origin, target} - ingredient_ids:
            raise ValueError(f"La relación {relation['from']} → {relation['to']} tiene un ID desconocido.")
        if relation["type"] not in {"culinary_substitute", "not_equivalent"}:
            raise ValueError(f"Tipo de relación desconocido: {relation['type']}")
        use = relation.get("use")
        if use is not None and use not in uses:
            raise ValueError(f"Uso culinario desconocido: {use}")
        key = (origin, target, use)
        if origin == target or key in relationship_keys:
            raise ValueError(f"Relación duplicada o reflexiva: {key}")
        relationship_keys.add(key)
        if not relation["sources"] or not relation["context"] or not relation["limitations"]:
            raise ValueError(f"Relación incompleta: {key}")
        if relation.get("evidence") not in {None, "direct", "inferred"}:
            raise ValueError(f"Tipo de evidencia desconocido: {key}")
        if relation.get("human_review") not in {None, "accepted", "rejected"}:
            raise ValueError(f"Estado de revisión humana desconocido: {key}")
    for record in ingredients + annotations["relations"]:
        missing = set(record["sources"]) - sources.keys()
        if missing:
            raise ValueError(f"Fuentes desconocidas: {', '.join(sorted(missing))}")
    return {
        "schema_version": 1,
        "ingredients": ingredients,
        "uses": uses,
        "relations": annotations["relations"],
        "sources": sources,
    }


def write_json(path, data):
    # Keep the previous file if writing its replacement fails.
    temporary_path = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False,
        ) as file:
            temporary_path = Path(file.name)
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
        temporary_path.replace(path)
    finally:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/catalog.json")
    parser.add_argument("--refresh", action="store_true", help="Descarga las revisiones actuales de Wikidata.")
    args = parser.parse_args()
    if args.output.resolve() == SNAPSHOT_PATH.resolve():
        parser.error("--output debe ser distinto del archivo de revisiones.")
    try:
        with (ROOT / "data/ingredients.csv").open(encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))
        annotations = json.loads((ROOT / "data/annotations.json").read_text(encoding="utf-8"))
        ids = sorted({row["wikidata_id"] for row in rows if row["wikidata_id"]})
        if args.refresh:
            entities = fetch_entities(ids)
        else:
            entities = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        catalog = build_catalog(rows, annotations, entities)
        if args.refresh:
            write_json(SNAPSHOT_PATH, entities)
        write_json(args.output, catalog)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"No se pudo regenerar el catálogo: {exc}\n")
    print(f"{len(catalog['ingredients'])} registros, {len(ids)} conceptos de Wikidata → {args.output}")


if __name__ == "__main__":
    main()
