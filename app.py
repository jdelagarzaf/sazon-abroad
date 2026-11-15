"""Entry point and shared navigation for Sazón Abroad."""

import streamlit as st

st.set_page_config(
    page_title="Sazón Abroad",
    page_icon=":material/soup_kitchen:",
    layout="wide",
    initial_sidebar_state="auto",
)

pages = [
    st.Page("app_pages/home.py", title="Inicio", default=True, icon=":material/home:"),
    st.Page("app_pages/find.py", title="Búsqueda", url_path="busqueda", icon=":material/search:"),
    st.Page("app_pages/recipes.py", title="Recetas", url_path="recetas", icon=":material/restaurant_menu:"),
    st.Page("app_pages/catalog.py", title="Catálogo", url_path="catalogo", icon=":material/menu_book:"),
    st.Page(
        "app_pages/evaluation.py", title="Evaluación", url_path="evaluacion",
        icon=":material/bar_chart:",
    ),
]
page = st.navigation(pages, position="hidden")

with st.sidebar:
    with st.container(gap="xsmall"):
        st.subheader("Sazón Abroad", icon=":material/soup_kitchen:")
        st.caption("México → Italia")
    st.space("small")
    with st.container(gap="xsmall"):
        for item in pages:
            st.page_link(item, width="stretch")

page.run()
