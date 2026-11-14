"""Streamlit interface for the Sazón Abroad ingredient catalog."""

import json
from pathlib import Path

import streamlit as st

from evaluation_view import show_evaluation
from search import IngredientSearch, normalize

CATALOG_PATH = Path(__file__).resolve().parent / "data" / "catalog.json"
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

st.set_page_config(page_title="Sazón Abroad", page_icon="🌶️", layout="centered")


@st.cache_data(max_entries=1, show_spinner=False)
def load_catalog(modified_ns):
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return catalog, IngredientSearch(catalog["ingredients"], catalog["relations"], catalog.get("uses"))


def show_sources(source_ids, sources):
    for source_id in source_ids:
        source = sources[source_id]
        link = f"[{source['label']}]({source['url']})"
        if source.get("revision_url"):
            link += f" · [Revisión {source['revision']}]({source['revision_url']})"
        st.markdown(f"- {link}")


def show_relation(relation, sources):
    warning = relation["type"] == "not_equivalent"
    with st.container(border=True):
        if warning:
            st.warning("No equivalente")
        else:
            st.info("Sustitución culinaria")
        st.markdown(f"**{relation['target_name_it']}** · {relation['target_name_es']}")
        st.markdown(f"**{relation['context']}** {relation['reason']}")
        st.write(relation["limitations"])
        evidence = EVIDENCE_LABELS.get(relation.get("evidence"), VERIFICATION_LABELS[relation["verification"]])
        if not warning:
            review = "Revisión culinaria aceptada" if relation.get("human_review") == "accepted" else "Pendiente de revisión culinaria"
            evidence += f" · {review}"
        st.caption(evidence)
        with st.expander("Fuentes de esta relación"):
            show_sources(relation["sources"], sources)


def show_ingredient(ingredient, relations, sources):
    with st.container(border=True):
        st.caption(ingredient["category"])
        st.markdown(f"### {ingredient['name_es']}")
        if ingredient["name_it"]:
            st.success("Equivalencia de nombre")
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
    for relation in relations:
        show_relation(relation, sources)


def set_query(value):
    st.session_state["ingredient_query"] = value


st.html("""
<style>
.stApp .block-container { max-width: 830px; padding-top: 3rem; }
.sazon-route {
    color: #476048;
    font-size: 0.82rem;
    font-weight: 700;
    letter-spacing: 0.13em;
    text-transform: uppercase;
    margin-bottom: 0.35rem;
}
.sazon-hero {
    border-bottom: 1px solid #DECCB5;
    padding-bottom: 1.15rem;
    margin-bottom: 0.8rem;
}
.sazon-hero h1 {
    color: #263727;
    font-size: clamp(2.5rem, 7vw, 4rem);
    line-height: 1.04;
    letter-spacing: -0.045em;
    padding: 0;
    margin: 0 0 0.7rem;
}
.sazon-hero p { margin: 0; max-width: 44ch; color: #41463B; }
</style>
<header class="sazon-hero">
  <div class="sazon-route">México → Italia</div>
  <h1>Sazón Abroad</h1>
  <p>Encuentra el nombre italiano de un ingrediente o una alternativa para tu platillo.</p>
</header>
""")

try:
    catalog, search_index = load_catalog(CATALOG_PATH.stat().st_mtime_ns)
except (OSError, ValueError):
    st.error("No se pudo leer el catálogo. Genera el archivo con python scripts/fetch_data.py.")
    st.stop()

ingredients = catalog["ingredients"]
sources = catalog["sources"]
uses = catalog.get("uses", {})
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
        elif results and lookup.context:
            st.info(f"No tenemos recomendaciones para ese uso ({lookup.context}).")
        if not results:
            st.info("No encontramos un ingrediente. Prueba con otro nombre o explora el catálogo.")
        elif results[0].match == "fuzzy":
            st.caption("Coincidencias aproximadas. Comprueba que sea el ingrediente que buscabas.")
        elif results[0].match == "prefix":
            st.caption("Coincidencias por nombre incompleto.")
        elif results[0].match == "bm25":
            st.caption("Coincidencias por palabras. Comprueba el nombre y la presentación en la ficha.")
        for result in results:
            ingredient = result.ingredient
            relations = search_index.relations_for(ingredient["id"], lookup.use)
            if lookup.context and not lookup.use:
                relations = []
            show_ingredient(ingredient, relations, sources)
            if lookup.use and not relations:
                st.caption("La ficha todavía no tiene relaciones registradas para este uso.")

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
            show_ingredient(by_id[selected_id], search_index.relations_for(selected_id), sources)

with evaluation_tab:
    show_evaluation(catalog)
