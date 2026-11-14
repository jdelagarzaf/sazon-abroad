"""Streamlit interface for the Sazón Abroad ingredient catalog."""

from collections import defaultdict
import json
from pathlib import Path
import re

import streamlit as st

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

@st.cache_data(max_entries=1, show_spinner=False)
def _load_catalog(modified_ns):
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return catalog, IngredientSearch(catalog["ingredients"], catalog["relations"], catalog.get("uses"))


@st.cache_data(max_entries=1, show_spinner=False)
def _load_photos(modified_ns):
    try:
        return json.loads(PHOTOS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def show_photo(photo, alt, width="stretch"):
    st.image(photo["thumbnail"], alt=alt, width=width)


def show_photo_credit(photo):
    license_name = photo["license"]
    if photo["license_url"]:
        license_name = f"[{license_name}]({photo['license_url']})"
    author = re.sub(r"([\\`*_\[\]<>])", r"\\\1", photo["author"] or "Wikimedia Commons")
    st.caption(f"Imagen de referencia · [{author}]({photo['source']}) · {license_name} · Miniatura")


def show_sources(source_ids, sources):
    for source_id in source_ids:
        source = sources[source_id]
        link = f"[{source['label']}]({source['url']})"
        if source.get("revision_url"):
            link += f" · [Revisión {source['revision']}]({source['revision_url']})"
        st.markdown(f"- {link}")


def show_relation_details(relation, sources):
    warning = relation["type"] == "not_equivalent"
    st.markdown(f"**{relation['context']}** {relation['reason']}")
    st.write(relation["limitations"])
    evidence = EVIDENCE_LABELS.get(relation.get("evidence"), VERIFICATION_LABELS[relation["verification"]])
    if not warning:
        review = "Revisión culinaria aceptada" if relation.get("human_review") == "accepted" else "Pendiente de revisión culinaria"
        evidence += f" · {review}"
    st.caption(evidence)
    with st.expander("Fuentes de esta relación"):
        show_sources(relation["sources"], sources)


def show_relation_card(relations, sources, photos):
    first = relations[0]
    warning = first["type"] == "not_equivalent"
    photo = photos.get(first["to"])
    with st.container(border=True, gap="xsmall"):
        if photo:
            thumbnail, body = st.columns([1, 4], gap="medium")
            with thumbnail:
                show_photo(photo, first["target_name_es"], width=136)
            details = body.container(gap="xsmall")
        else:
            details = st.container(gap="xsmall")
        with details:
            if warning:
                st.badge("No equivalente", color="red")
            else:
                st.badge("Sustitución culinaria", color="orange")
            st.subheader(first["target_name_it"])
            st.caption(first["target_name_es"])
            for relation in relations:
                show_relation_details(relation, sources)
            if photo:
                show_photo_credit(photo)


def show_ingredient(ingredient, sources, photos, *, searched=False):
    photo = photos.get(ingredient["id"])
    with st.container(border=True, gap="xsmall"):
        if searched:
            st.caption("Ingrediente buscado")
        if photo:
            show_photo(photo, ingredient["name_es"])
        st.subheader(ingredient["name_es"])
        st.caption(ingredient["category"])
        if ingredient["name_it"]:
            st.badge("Equivalencia de nombre", color="green")
            st.markdown(f"**En italiano** · {ingredient['name_it']}")
        elif ingredient["reference_it"]:
            label = REFERENCE_LABELS[ingredient["reference_kind"]]
            st.markdown(f"**{label}** · {ingredient['reference_it']}")
            if ingredient["note_it"]:
                st.caption(ingredient["note_it"])
        else:
            st.caption("Sin nombre italiano común confirmado en el catálogo.")

        if ingredient["note"]:
            st.write(ingredient["note"])
        st.caption(VERIFICATION_LABELS[ingredient["verification"]])
        with st.expander("Fuentes y nombres alternativos"):
            if ingredient["aliases_es"]:
                st.markdown("**Español** · " + ", ".join(ingredient["aliases_es"]))
            if ingredient["aliases_it"]:
                alias_label = "Italiano" if ingredient["name_it"] else "Términos de búsqueda"
                st.markdown(f"**{alias_label}** · " + ", ".join(ingredient["aliases_it"]))
            show_sources(ingredient["sources"], sources)
            if photo:
                show_photo_credit(photo)


def show_alternatives(relations, sources, photos, *, context=None):
    groups = defaultdict(list)
    for relation in relations:
        key = (relation["type"], relation["to"], relation["target_name_it"], relation["target_name_es"])
        groups[key].append(relation)

    substitutes = [cards for key, cards in groups.items() if key[0] == "culinary_substitute"]
    warnings = [cards for key, cards in groups.items() if key[0] == "not_equivalent"]
    if substitutes:
        st.header("Alternativas sugeridas")
        for cards in substitutes:
            show_relation_card(cards, sources, photos)
    elif not warnings:
        st.header("Alternativas sugeridas")
        message = "Todavía no hay sustitutos registrados para este ingrediente."
        if context:
            message = f"Todavía no hay sustitutos registrados para este uso ({context})."
        st.info(message)

    if warnings:
        st.header("Advertencias")
        for cards in warnings:
            show_relation_card(cards, sources, photos)


def get_catalog():
    try:
        return _load_catalog(CATALOG_PATH.stat().st_mtime_ns)
    except (OSError, ValueError):
        st.error("No se pudo leer el catálogo. Genera el archivo con python scripts/fetch_data.py.")
        st.stop()


def load_photos():
    try:
        return _load_photos(PHOTOS_PATH.stat().st_mtime_ns)
    except OSError:
        return {}
