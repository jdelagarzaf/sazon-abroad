"""Explore Mexican recipes and adapt the shopping list and preparation."""

import streamlit as st

from ingredient_views import get_catalog, show_photo, show_photo_credit, show_relation_details, show_sources
from recipe_plans import load_recipes, make_plan, resolve_ingredients

st.title("Recetas mexicanas")
st.write("Consulta la receta original o adapta la lista de compras y los pasos para cocinar en Italia.")

try:
    recipes = {recipe["id"]: recipe for recipe in load_recipes()}
except (OSError, ValueError, KeyError):
    st.error("No se pudieron cargar las recetas.")
    st.stop()

recipe_id = st.selectbox(
    "Elige una receta", list(recipes),
    format_func=lambda key: recipes[key]["title"],
    key="selected_recipe", persist_state="session",
)
if recipe_id is None:
    st.stop()
recipe = recipes[recipe_id]
catalog, search_index = get_catalog()
rows = resolve_ingredients(recipe, catalog, search_index)
sources = catalog["sources"]

with st.container(border=True):
    details, picture = st.columns([3, 2], gap="medium", vertical_alignment="center")
    with details:
        st.header(recipe["title"])
        st.write(recipe["description"])
        st.caption(f"{recipe['servings']} porciones · {recipe['minutes']} min aprox.")
        with st.expander("Fuentes de la receta"):
            st.caption("Versión de Sazón Abroad con cantidades y pasos propios, basada en estas referencias.")
            show_sources(recipe["sources"], sources)
    with picture:
        show_photo(recipe["photo"], recipe["photo"]["alt"], width=360)
        show_photo_credit(recipe["photo"])

italy = st.radio(
    "Versión", ["Receta original", "Para cocinar en Italia"],
    index=1, horizontal=True, key="recipe_version", persist_state="session",
) == "Para cocinar en Italia"

selection = {}
if italy:
    rows_with_choices = [row for row in rows if row["choices"]]
    if rows_with_choices:
        with st.container(border=True, gap="small"):
            st.subheader("Elige qué sustituir")
            for row in rows_with_choices:
                original = row["id"]
                choices = row["choices"]
                labels = {original: f"Conservar {row['name']}"}
                labels.update({target: rel["target_name_it"] for target, rel in choices.items()})
                picked = st.selectbox(
                    row["name"], list(labels), format_func=labels.__getitem__,
                    key=f"recipe-{recipe_id}-{original}", persist_state="session",
                )
                if picked in choices:
                    selection[original] = picked
                    with st.expander(f"Uso y fuente · {labels[picked]}"):
                        show_relation_details(choices[picked], sources)

shopping, steps = make_plan(recipe, rows, selection)
st.subheader("Ingredientes")
if italy:
    st.dataframe(
        [
            {
                "Ingrediente original": entry["original"],
                "Cantidad original": entry["original_amount"],
                "Qué buscar en Italia": entry["italian"] or "Sin término documentado",
                "Cantidad a usar": entry["amount"],
                "Tipo": "Sustituto elegido" if entry["substitute"] else "Ingrediente original",
            }
            for entry in shopping
        ],
        hide_index=True, alt="Ingredientes originales y lista de compras en Italia",
        column_config={
            "Qué buscar en Italia": st.column_config.TextColumn(width="medium"),
            "Cantidad a usar": st.column_config.TextColumn(width="medium"),
        },
    )
    omitted = {row["name"] for row in rows} - {entry["original"] for entry in shopping}
    if omitted:
        st.caption("Puedes omitir " + ", ".join(sorted(omitted)).lower() + " con las opciones elegidas.")
    with st.expander("Fuentes de los nombres de ingredientes"):
        for row in rows:
            st.markdown(f"**{row['name']}**")
            show_sources(row["sources"], sources)
else:
    for entry in shopping:
        st.markdown(f"- **{entry['original']}** · {entry['original_amount']}")

st.subheader("Preparación")
st.markdown("\n".join(f"{number}. {step}" for number, step in enumerate(steps, start=1)))
