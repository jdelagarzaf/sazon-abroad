"""Exact minimum-chain cover over found evidence, with explicit manual assignments."""
from hashlib import sha256
from itertools import combinations

from retailers import commercial_result


def product_key(name):
    return sha256(name.encode("utf-8")).hexdigest()[:16]


def purchase_plan(shopping, stored, retailers, pins=None):
    pins = pins or {}
    requested = list(dict.fromkeys((stored or {}).get("requested", [])))
    requested = [name for name in requested if name in {item["name"] for item in shopping}]
    preferred = set((stored or {}).get("preferred", []))
    stores = {store["id"]: store for store in retailers}
    candidates = {name: {} for name in requested}
    for search in (stored or {}).get("searches", []):
        name = search.get("product")
        if name not in candidates:
            continue
        for raw in search.get("results", []):
            hit = commercial_result(raw, name, retailers)
            if not hit:
                continue
            hit["queried_at"] = search.get("queried_at", "")
            previous = candidates[name].get(hit["retailer_id"])
            if not previous or (previous["evidence_type"] == "catalog_listing" and hit["evidence_type"] == "product_page"):
                candidates[name][hit["retailer_id"]] = hit
    eligible = {}
    for name, options in candidates.items():
        primary = {key: hit for key, hit in options.items() if key in preferred}
        eligible[name] = primary or options
    # Manual choices can select any found candidate, including a fallback retailer.
    for name, store_id in pins.items():
        if name not in candidates or store_id not in candidates[name]:
            raise ValueError("La tienda elegida no tiene una ficha pertinente para ese producto. Vuelve a revisar los resultados.")
        eligible[name] = {store_id: candidates[name][store_id]}
    coverable = [name for name in requested if eligible[name]]
    ids = sorted({store_id for name in coverable for store_id in eligible[name]})
    best = ()
    # At most 8 products and 8 configured retailers: exhaustive, not greedy.
    for size in range(1, len(ids) + 1):
        choices = [combo for combo in combinations(ids, size) if all(set(combo) & eligible[name].keys() for name in coverable)]
        if choices:
            def score(combo):
                weak = sum(not any(eligible[name][sid]["evidence_type"] == "product_page" for sid in combo if sid in eligible[name]) for name in coverable)
                return weak, sum(sid not in preferred for sid in combo), combo
            best = min(choices, key=score)
            break
    assignments = {}
    for name in coverable:
        options = [sid for sid in best if sid in eligible[name]]
        assignments[name] = min(options, key=lambda sid: (eligible[name][sid]["evidence_type"] != "product_page", sid not in preferred, sid))
    groups = []
    for sid in best:
        entries = [{**item, "hit": candidates[item["name"]][sid], "key": product_key(item["name"])} for item in shopping if assignments.get(item["name"]) == sid]
        if entries:
            groups.append({"store": stores[sid], "items": entries})
    rows = [{"name": name, "key": product_key(name), "candidates": candidates[name], "selected": assignments.get(name),
             "pinned": pins.get(name), "hit": candidates[name].get(assignments.get(name))} for name in requested]
    return {"groups": groups, "rows": rows, "assignments": assignments, "covered": len(assignments),
            "total": len(requested), "missing": [name for name in requested if not candidates[name]],
            "unsearched": [name for name in dict.fromkeys(item["name"] for item in shopping) if name not in requested],
            "store_count": len(groups)}
