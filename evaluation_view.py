"""Streamlit panel for comparing retrieval methods on the labeled benchmark."""

import streamlit as st

from evaluation import evaluate, load_cases
from search import METHODS

METRICS = {
    "top1": "Top-1 Accuracy",
    "recall_at_3": "Recall@3",
    "no_result": "Abstención correcta",
    "context": "Acierto contextual",
}
KINDS = {
    "exacta": "Nombre exacto",
    "alias": "Alias",
    "prefijo": "Prefijo",
    "errata": "Errata",
    "palabras": "Palabras reordenadas u omitidas",
    "contexto": "Uso culinario",
    "sin resultado": "Fuera del catálogo",
}


@st.cache_data(max_entries=1, show_spinner=False)
def benchmark(catalog, cases):
    return evaluate(catalog, cases)


def show_evaluation(catalog):
    st.header("Evaluación de búsqueda")
    try:
        result = benchmark(catalog, load_cases())
    except (OSError, ValueError, KeyError) as exc:
        st.error(f"No se pudo cargar la evaluación. {exc}")
        return

    coverage = f"{result['source_count']}/{result['catalog_count']}"
    quality = result["accepted_share"]
    with st.container(horizontal=True):
        st.metric("Consultas etiquetadas", result["count"], border=True)
        st.metric("Fichas con fuente", coverage, border=True)
        st.metric("Sustituciones revisadas por personas", f"{result['human_reviewed']}/{result['substitutions']}", border=True)
    st.caption(
        f"Aceptación culinaria: {quality:.0%} de las sustituciones revisadas."
        if quality is not None else "La tasa de aceptación culinaria se calculará cuando haya revisiones humanas."
    )

    metric = st.selectbox(
        "Métrica", list(METRICS), format_func=lambda item: METRICS[item], key="evaluation_metric",
    )
    plot = [
        {"Método": row["method"], "Proporción": row[metric]}
        for row in result["summary"] if row[metric] is not None
    ]
    if plot:
        st.vega_lite_chart(
            plot,
            {
                "mark": {"type": "bar", "cornerRadiusEnd": 3},
                "encoding": {
                    "x": {"field": "Proporción", "type": "quantitative", "scale": {"domain": [0, 1]}, "axis": {"format": ".0%"}},
                    "y": {"field": "Método", "type": "nominal", "sort": list(METHODS.values())},
                    "tooltip": [
                        {"field": "Método"},
                        {"field": "Proporción", "type": "quantitative", "format": ".1%"},
                    ],
                },
            },
            height=160,
            alt=f"Comparación de {METRICS[metric]} entre los tres métodos de búsqueda",
        )
    counts = {
        "top1": result["answerable"],
        "recall_at_3": result["answerable"],
        "no_result": result["count"] - result["answerable"],
        "context": result["contextual"],
    }
    st.caption(f"Consultas incluidas en esta métrica: {counts[metric]}.")
    st.dataframe(
        [
            {"Método": row["method"], **{
                label: f"{row[key]:.1%}" if row[key] is not None else "—"
                for key, label in METRICS.items()
            }}
            for row in result["summary"]
        ],
        hide_index=True, alt="Resultados de las cuatro métricas por método",
    )

    st.subheader("Revisar las consultas")
    with st.container(horizontal=True, vertical_alignment="bottom"):
        method = st.selectbox("Método de búsqueda", list(METHODS.values()), index=2, key="evaluation_method")
        kind = st.selectbox(
            "Tipo de consulta", [None, *KINDS], format_func=lambda item: KINDS.get(item, "Todos"),
            key="evaluation_kind",
        )
        errors_only = st.checkbox("Solo errores", key="evaluation_errors")
    names = {row["id"]: row["name_es"] for row in catalog["ingredients"]}

    def display(ids):
        return ", ".join(names[item] for item in ids) or "—"

    rows = [
        {
            "Consulta": row["query"], "Tipo": KINDS[row["kind"]],
            "Esperado": display(row["expected"]), "Recuperado": display(row["returned"]),
            "Sustitutos esperados": display(row["expected_substitutes"]),
            "Sustitutos mostrados": display(row["substitutes"]),
            "Advertencias esperadas": display(row["expected_warnings"]),
            "Advertencias mostradas": display(row["warnings"]),
            "Evaluación": "Acierto" if row["correct"] else "Error",
        }
        for row in result["details"]
        if row["method"] == method and (kind is None or row["kind"] == kind)
        and (not errors_only or not row["correct"])
    ]
    if rows:
        st.dataframe(rows, hide_index=True, alt="Consultas esperadas y recuperadas por el método elegido")
    else:
        st.info("No hay consultas con estos filtros.")
    st.caption("Las consultas y etiquetas son de elaboración propia. Los resultados describen este conjunto de prueba.")
