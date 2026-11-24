"""Prepare model input and check draft substitutions for editorial review."""

import argparse
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

from fetch_data import ROOT, write_json

TASK = (
    "Propón sustituciones culinarias para los pares y usos indicados. Responde en español "
    "con un objeto JSON que solo contenga la lista candidates. Cada candidato debe incluir "
    "from, to, use, reason, limitations y sources, y puede incluir adaptation. Usa los IDs "
    "del lote. Fundamenta las propuestas en las propiedades y notas incluidas. En sources "
    "usa solo IDs de fuentes del par. Explica qué función "
    "se conserva y qué cambia. Omite el par si la evidencia es insuficiente. "
    "Las propuestas se revisarán antes de incorporarse al catálogo."
)
REQUIRED_FIELDS = {"from", "to", "use", "reason", "limitations", "sources"}
RESPONSE_FORMAT = {
    "type": "json_schema",
    "name": "substitution_drafts",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["candidates"],
        "properties": {
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": sorted(REQUIRED_FIELDS | {"adaptation"}),
                    "properties": {
                        **{field: {"type": "string"} for field in sorted(REQUIRED_FIELDS - {"sources"})},
                        "sources": {"type": "array", "items": {"type": "string"}},
                        "adaptation": {"type": ["string", "null"]},
                    },
                },
            },
        },
    },
}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def related_sources(item):
    return set(item["sources"]).union(
        source for claim in item.get("properties", {}).values() for source in claim["sources"]
    )


def requested_pairs(ingredients, uses, known, requests):
    selected = {}
    for request in requests:
        fields = request.split(":")
        if len(fields) not in {2, 3}:
            raise ValueError(f"Usa origen:uso u origen:destino:uso ({request}).")
        origin, use = fields[0], fields[-1]
        if origin not in ingredients or use not in uses:
            raise ValueError(f"El ingrediente de origen o el uso no existe ({request}).")
        source = ingredients[origin]
        if len(fields) == 3:
            target = fields[1]
            if target not in ingredients:
                raise ValueError(f"El ingrediente de destino no existe ({request}).")
            candidates = [target]
        else:
            candidates = [
                item["id"] for item in ingredients.values()
                if item["category"] == source["category"] and item["sources"]
            ]
        if use in source.get("substitution_gaps", {}):
            raise ValueError(f"El catálogo ya registra una abstención ({request}).")
        for target in candidates:
            pair = (origin, target, use)
            if origin == target or pair in known:
                if len(fields) == 3:
                    raise ValueError(f"El par es reflexivo o ya existe ({request}).")
                continue
            selected[pair] = None
    if not selected:
        raise ValueError("No hay pares nuevos para evaluar.")
    return selected.keys()


def prepare(catalog, pairs, source_ids):
    ingredients = {item["id"]: item for item in catalog["ingredients"]}
    known = {(rel["from"], rel["to"], rel.get("use")) for rel in catalog["relations"]}
    if set(source_ids) - catalog["sources"].keys():
        raise ValueError("Uno de los IDs de fuente no existe en el catálogo.")
    rows = []
    sources = set()
    for origin, target, use in requested_pairs(ingredients, catalog["uses"], known, pairs):
        valid_sources = related_sources(ingredients[origin]) | related_sources(ingredients[target]) | set(source_ids)
        if not valid_sources:
            raise ValueError(f"El par necesita fuentes para poder evaluarse ({origin}:{target}:{use}).")
        sources.update(valid_sources)
        rows.append({"from": origin, "to": target, "use": use, "sources": sorted(valid_sources)})
    ingredient_ids = {row[key] for row in rows for key in ("from", "to")}
    return {
        "task": TASK,
        "pairs": rows,
        "ingredients": {key: ingredients[key] for key in sorted(ingredient_ids)},
        "uses": {key: catalog["uses"][key] for key in sorted({row["use"] for row in rows})},
        "sources": {key: catalog["sources"][key] for key in sorted(sources)},
    }


def check(batch, draft):
    if not isinstance(draft, dict) or set(draft) != {"candidates"} or not isinstance(draft["candidates"], list):
        raise ValueError("El documento debe contener solo una lista candidates.")
    allowed = {
        (row["from"], row["to"], row["use"]): set(row["sources"]) & batch["sources"].keys()
        for row in batch["pairs"]
    }
    seen = set()
    for candidate in draft["candidates"]:
        if (
            not isinstance(candidate, dict)
            or not REQUIRED_FIELDS <= candidate.keys()
            or candidate.keys() - REQUIRED_FIELDS - {"adaptation"}
        ):
            raise ValueError("El candidato contiene campos desconocidos o incompletos.")
        for field in candidate.keys() - {"sources"}:
            if not isinstance(candidate[field], str) or not candidate[field].strip():
                raise ValueError(f"El campo {field} necesita texto.")
        key = (candidate["from"], candidate["to"], candidate["use"])
        if key not in allowed or key in seen:
            raise ValueError(f"El par no estaba en el lote o ya se propuso ({key}).")
        seen.add(key)
        refs = candidate["sources"]
        if (
            not isinstance(refs, list)
            or not refs
            or any(not isinstance(ref, str) or ref not in allowed[key] for ref in refs)
            or len(set(refs)) != len(refs)
        ):
            raise ValueError(f"Fuentes ausentes, duplicadas o ajenas al par ({key}).")
    return len(seen)


def generate(batch, model, api_key):
    payload = {
        "model": model,
        "instructions": TASK + " Incluye adaptation con valor null si no hace falta un ajuste.",
        "input": json.dumps({key: value for key, value in batch.items() if key != "task"}, ensure_ascii=False),
        "text": {"format": RESPONSE_FORMAT},
        "max_output_tokens": 8000,
        "store": False,
    }
    request = Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=120) as response:
        result = json.load(response)
    if result.get("status") != "completed":
        raise ValueError("El modelo no completó la respuesta. Prueba con un lote más pequeño.")
    messages = [
        part["text"]
        for item in result["output"] if item["type"] == "message"
        for part in item["content"] if part["type"] == "output_text"
    ]
    if not messages:
        raise ValueError("El modelo no devolvió propuestas en JSON.")
    draft = json.loads("".join(messages))
    for candidate in draft["candidates"]:
        if candidate.get("adaptation") is None:
            candidate.pop("adaptation", None)
    check(batch, draft)
    return draft


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    create = actions.add_parser("prepare")
    create.add_argument("pairs", nargs="+", help="origen:uso u origen:destino:uso")
    create.add_argument("--source", action="append", default=[], help="ID de fuente adicional.")
    create.add_argument("--output", type=Path, required=True)
    validate = actions.add_parser("check")
    validate.add_argument("batch", type=Path)
    validate.add_argument("draft", type=Path)
    infer = actions.add_parser("generate")
    infer.add_argument("batch", type=Path)
    infer.add_argument("--model", required=True)
    infer.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        data = ROOT / "data"
        if args.action != "check":
            protected = {"catalog.json", "annotations.json", "ingredients.csv", "recipes.json", "wikidata_snapshot.json", "evaluation.csv", "photos.json"}
            if args.output.resolve() in {data / name for name in protected}:
                raise ValueError("Elige un archivo de trabajo separado de los datos de la app.")
        if args.action == "prepare":
            catalog = read_json(data / "catalog.json")
            write_json(args.output, prepare(catalog, args.pairs, args.source))
            print(f"Lote preparado en {args.output}")
        elif args.action == "generate":
            if args.output.resolve() == args.batch.resolve():
                raise ValueError("La salida de propuestas debe ser distinta del lote de entrada.")
            if not (api_key := os.environ.get("OPENAI_API_KEY")):
                raise ValueError("Configura OPENAI_API_KEY para ejecutar la generación automática.")
            draft = generate(read_json(args.batch), args.model, api_key)
            write_json(args.output, draft)
            print(f"{len(draft['candidates'])} propuestas guardadas en {args.output}")
        else:
            count = check(read_json(args.batch), read_json(args.draft))
            print(f"{count} propuestas con JSON valido, pendientes de revision culinaria.")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"No se pudo procesar el lote: {exc}\n")


if __name__ == "__main__":
    main()
