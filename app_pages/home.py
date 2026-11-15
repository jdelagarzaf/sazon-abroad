"""Home page with a search entry point and example lookups."""

import streamlit as st

from ingredient_views import show_photo, show_photo_credit

SEARCH_PAGE = "app_pages/find.py"
HERO = {
    "thumbnail": "https://thumb.wikimedia.org/wikipedia/commons/thumb/f/fb/Guacamole_tradicional.jpg/960px-Guacamole_tradicional.jpg",
    "author": "Jazz Guy",
    "license": "CC BY 4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "source": "https://commons.wikimedia.org/wiki/File:Guacamole_tradicional.jpg",
}
EXAMPLES = (
    ("Jitomate", "Conoce su nombre en italiano.", "Equivalencia", "green"),
    ("Poblano para rajas", "Encuentra una alternativa para rajas con crema.", "Sustitución", "orange"),
    ("Masa harina", "Identifica la harina adecuada para tortillas.", "Advertencia", "red"),
)


def open_search(query):
    st.session_state["home_search_query"] = query
    st.switch_page(SEARCH_PAGE)


with st.container(border=True, gap="small"):
    welcome, picture = st.columns([3, 2], gap="medium", vertical_alignment="center")
    with welcome:
        st.title("Cocina como en casa, desde Italia")
        st.write("Encuentra ingredientes mexicanos por su nombre en italiano o busca un sustituto para tu platillo.")
        with st.form("home_search", border=False):
            query = st.text_input(
                "Busca un ingrediente", placeholder="Ej. chile poblano para rajas",
                icon=":material/search:", max_chars=160, required=True,
            )
            submitted = st.form_submit_button("Buscar", type="primary", icon=":material/arrow_forward:")
        if submitted and query and query.strip():
            open_search(query.strip())
    with picture:
        show_photo(HERO, "Guacamole preparado en un molcajete de piedra")
        show_photo_credit(HERO)

st.page_link("app_pages/recipes.py", label="Explorar recetas mexicanas", icon=":material/restaurant_menu:")

st.header("Prueba una búsqueda")
for column, (query, description, kind, color) in zip(st.columns(3, gap="medium"), EXAMPLES):
    with column.container(border=True, gap="xsmall", height="stretch"):
        st.badge(kind, color=color)
        st.subheader(query)
        st.write(description)
        st.button(
            "Probar búsqueda", key=f"home-example-{query}",
            icon=":material/arrow_forward:", on_click=open_search, args=(query,),
        )
