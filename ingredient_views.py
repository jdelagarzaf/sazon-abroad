"""Catalog data and display labels shared by the Flask pages."""

from functools import lru_cache
import json
from pathlib import Path

from search import IngredientSearch

CATALOG_PATH = Path(__file__).resolve().parent / "data" / "catalog.json"
PHOTOS_PATH = CATALOG_PATH.with_name("photos.json")
VERIFICATION_LABELS = {
    "retrieved": "Recuperado de Wikidata",
    "source_supported": "Documentado en las fuentes",
    "pending": "Pendiente de revisión",
}
REFERENCE_LABELS = {
    "description": "Término descriptivo",
    "scientific": "Nombre científico",
    "documented": "Nombre en italiano",
}
EVIDENCE_LABELS = {
    "direct": "La fuente respalda este uso",
    "inferred": "Sugerencia inferida de las fuentes",
}


@lru_cache(maxsize=1)
def _load_catalog(modified_ns):
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return catalog, IngredientSearch(catalog["ingredients"], catalog["relations"], catalog.get("uses"))


@lru_cache(maxsize=1)
def _load_photos(modified_ns):
    return json.loads(PHOTOS_PATH.read_text(encoding="utf-8"))


def get_catalog():
    return _load_catalog(CATALOG_PATH.stat().st_mtime_ns)


def load_photos():
    try:
        return _load_photos(PHOTOS_PATH.stat().st_mtime_ns)
    except (OSError, ValueError):
        return {}
