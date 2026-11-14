import streamlit as st

from ingredient_views import get_catalog, load_photos, show_alternatives, show_ingredient
from search import normalize

EXAMPLES = ("Jitomate", "Chile poblano", "Masa harina")


def set_query(value):
    st.session_state["ingredient_query"] = value


st.title("Búsqueda")
catalog, search_index = get_catalog()
sources = catalog["sources"]
uses = catalog.get("uses", {})
photos = load_photos()

if "home_search_query" in st.session_state:
    set_query(st.session_state.pop("home_search_query"))

query = st.text_input(
    "Busca un ingrediente", key="ingredient_query", persist_state="session",
    icon=":material/search:", max_chars=160,
    placeholder="Ej. chile poblano para rajas",
    help="Puedes indicar el uso con «para» en español o «per» en italiano.",
)
with st.container(horizontal=True):
    st.caption("Prueba con")
    for example in EXAMPLES:
        st.button(example, key=f"example-{example}", on_click=set_query, args=(example,))

if query and query.strip():
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
