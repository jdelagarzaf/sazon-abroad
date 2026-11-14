"""Streamlit interface for the Sazón Abroad ingredient catalog."""

from collections import defaultdict
import json
from pathlib import Path
import re

import streamlit as st

from evaluation_view import show_evaluation
from search import IngredientSearch, normalize

CATALOG_PATH = Path(__file__).resolve().parent / "data" / "catalog.json"
PHOTOS_PATH = CATALOG_PATH.with_name("photos.json")
EXAMPLES = ("Jitomate", "Chile poblano", "Masa harina")
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

st.set_page_config(page_title="Sazón Abroad", page_icon="🌶️", layout="wide")


@st.cache_data(max_entries=1, show_spinner=False)
def load_catalog(modified_ns):
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return catalog, IngredientSearch(catalog["ingredients"], catalog["relations"], catalog.get("uses"))


@st.cache_data(max_entries=1, show_spinner=False)
def load_photos(modified_ns):
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


def set_query(value):
    st.session_state["ingredient_query"] = value


with st.container(gap="xsmall"):
    st.caption("México → Italia")
    st.title("Sazón Abroad")
    st.write("Encuentra el nombre italiano de un ingrediente o una alternativa para tu platillo.")

try:
    catalog, search_index = load_catalog(CATALOG_PATH.stat().st_mtime_ns)
except (OSError, ValueError):
    st.error("No se pudo leer el catálogo. Genera el archivo con python scripts/fetch_data.py.")
    st.stop()

ingredients = catalog["ingredients"]
sources = catalog["sources"]
uses = catalog.get("uses", {})
photos = load_photos(PHOTOS_PATH.stat().st_mtime_ns) if PHOTOS_PATH.is_file() else {}
search_tab, catalog_tab, evaluation_tab = st.tabs(["Buscar", "Catálogo", "Evaluación"])
with search_tab:
    query = st.text_input(
        "Busca un ingrediente", key="ingredient_query",
        placeholder="Ej. chile poblano para rajas",
        help="Puedes indicar el uso con «para» en español o «per» en italiano.",
    )
    with st.container(horizontal=True):
        st.caption("Prueba con")
        for example in EXAMPLES:
            st.button(example, key=f"example-{example}", on_click=set_query, args=(example,))

    if query.strip():
        lookup = search_index.lookup(query)
        results = lookup.hits
        if results and lookup.use:
            st.caption(f"Uso culinario · {uses[lookup.use]['label']}")
        if not results:
            st.info("No encontramos un ingrediente. Prueba con otro nombre o explora el catálogo.")
        elif results[0].match == "fuzzy":
            st.caption("Coincidencias aproximadas. Comprueba que sea el ingrediente que buscabas.")
        elif results[0].match == "prefix":
            st.caption("Coincidencias por nombre incompleto.")
        elif results[0].match == "bm25":
            st.caption("Coincidencias por palabras. Comprueba el nombre y la presentación en la ficha.")
        if results:
            matches = {hit.ingredient["id"]: hit.ingredient for hit in results}
            ingredient_id = results[0].ingredient["id"]
            if len(matches) > 1:
                selected_match = st.selectbox(
                    "Ingredientes que coinciden", list(matches),
                    format_func=lambda item: matches[item]["name_es"],
                    key=f"result-match-{normalize(query)}",
                )
                if selected_match in matches:
                    ingredient_id = selected_match

            relations = []
            if not lookup.context or lookup.use:
                relations = search_index.relations_for(ingredient_id, lookup.use)
            # Limit the width so the original stays compact on large desktop screens.
            with st.container(width=1120):
                original, alternatives = st.columns([1, 2.65], gap="large")
                with original:
                    show_ingredient(matches[ingredient_id], sources, photos, searched=True)
                with alternatives:
                    context = uses[lookup.use]["label"].lower() if lookup.use else lookup.context
                    show_alternatives(relations, sources, photos, context=context)

with catalog_tab:
    mexican_ingredients = [item for item in ingredients if item["scope"] == "México"]
    categories = sorted({item["category"] for item in mexican_ingredients})
    statuses = [
        status for status in VERIFICATION_LABELS
        if any(item["verification"] == status for item in mexican_ingredients)
    ]
    with st.container(horizontal=True, vertical_alignment="bottom"):
        selected_category = st.selectbox("Categoría", ["Todas", *categories], key="catalog_category")
        selected_status = st.selectbox(
            "Estado de la ficha", [None, *statuses],
            format_func=lambda status: VERIFICATION_LABELS.get(status, "Todos"),
            key="catalog_status",
        )

    options = sorted(
        (
            item for item in mexican_ingredients
            if selected_category in ("Todas", item["category"])
            and selected_status in (None, item["verification"])
        ),
        key=lambda item: normalize(item["name_es"]),
    )
    st.caption(f"{len(options)} de {len(mexican_ingredients)} ingredientes")
    if not options:
        st.info("No hay ingredientes con esos filtros.")
    else:
        overview = [
            {
                "Ingrediente": item["name_es"],
                "Nombre o referencia en Italia": item["name_it"] or item["reference_it"] or "—",
                "Estado": VERIFICATION_LABELS[item["verification"]],
                "Fuente": sources[item["sources"][0]]["url"] if item["sources"] else None,
            }
            for item in options
        ]
        st.dataframe(
            overview, hide_index=True, height=275,
            alt="Ingredientes que coinciden con los filtros del catálogo",
            column_config={"Fuente": st.column_config.LinkColumn(display_text="Abrir fuente")},
        )
        by_id = {item["id"]: item for item in options}
        if st.session_state.get("catalog_ingredient") not in by_id:
            st.session_state["catalog_ingredient"] = None
        selected_id = st.selectbox(
            "Abrir ficha", list(by_id), index=None,
            format_func=lambda item_id: by_id[item_id]["name_es"],
            placeholder="Selecciona un ingrediente",
            key="catalog_ingredient",
        )
        if selected_id in by_id:
            show_ingredient(by_id[selected_id], sources, {})
            for relation in search_index.relations_for(selected_id):
                show_relation_card([relation], sources, {})

with evaluation_tab:
    show_evaluation(catalog)
