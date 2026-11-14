import streamlit as st

from ingredient_views import VERIFICATION_LABELS, get_catalog, show_ingredient, show_relation_card
from search import normalize

st.title("Catálogo")
catalog, search_index = get_catalog()
ingredients, sources = catalog["ingredients"], catalog["sources"]

mexican_ingredients = [item for item in ingredients if item["scope"] == "México"]
categories = sorted({item["category"] for item in mexican_ingredients})
statuses = [
    status for status in VERIFICATION_LABELS
    if any(item["verification"] == status for item in mexican_ingredients)
]
with st.container(horizontal=True, vertical_alignment="bottom"):
    selected_category = st.selectbox("Categoría", ["Todas", *categories], key="catalog_category", persist_state="session")
    selected_status = st.selectbox(
        "Estado de la ficha", [None, *statuses],
        format_func=lambda status: VERIFICATION_LABELS.get(status, "Todos"),
        key="catalog_status", persist_state="session",
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
        key="catalog_ingredient", persist_state="session",
    )
    if selected_id in by_id:
        show_ingredient(by_id[selected_id], sources, {})
        for relation in search_index.relations_for(selected_id):
            show_relation_card([relation], sources, {})
