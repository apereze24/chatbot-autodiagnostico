"""
Chatbot de Autodiagnóstico — Prototipo (Fase 1, datos de ejemplo).

Página web de chat para uso interno: escribes una pregunta sobre el proceso de
autodiagnóstico y responde con texto + un gráfico, consultando los datos.

Cómo ejecutar (desde la carpeta del proyecto):
    .venv\\Scripts\\streamlit run app.py
"""

import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import metrics
from chatbot import entender
from sample_data import generar_clientes, generar_runs

load_dotenv()  # lee ANTHROPIC_API_KEY desde un archivo .env si existe

st.set_page_config(page_title="Chatbot Autodiagnóstico", page_icon="🤖", layout="wide")


# --- Datos (se generan una sola vez y se cachean) ----------------------------
@st.cache_data
def cargar_datos():
    runs = generar_runs()
    clientes = generar_clientes(runs)
    return runs, clientes


runs, clientes = cargar_datos()


# --- Barra lateral: filtros --------------------------------------------------
st.sidebar.title("🔎 Filtros")

ciudades_sel = st.sidebar.multiselect(
    "Ciudad", sorted(runs["ciudad"].unique()), default=[]
)
canales_sel = st.sidebar.multiselect(
    "Canal", ["Portal", "Bot", "Sysbrazo"], default=[]
)
fecha_min, fecha_max = runs["fecha"].min(), runs["fecha"].max()
rango = st.sidebar.date_input(
    "Rango de fechas", value=(fecha_min, fecha_max),
    min_value=fecha_min, max_value=fecha_max,
)

st.sidebar.markdown("---")
if os.environ.get("ANTHROPIC_API_KEY"):
    st.sidebar.success("🧠 IA de Claude: ACTIVA (preguntas libres)")
else:
    st.sidebar.info(
        "🧠 IA de Claude: sin conectar.\n\n"
        "El chatbot funciona con preguntas directas. Para preguntas totalmente "
        "libres, agrega tu clave en un archivo `.env` (ver README)."
    )


def aplicar_filtros(df: pd.DataFrame) -> pd.DataFrame:
    d = df
    if ciudades_sel:
        d = d[d["ciudad"].isin(ciudades_sel)]
    if canales_sel:
        d = d[d["canal"].isin(canales_sel)]
    if isinstance(rango, (list, tuple)) and len(rango) == 2:
        ini, fin = rango
        d = d[(d["fecha"] >= ini) & (d["fecha"] <= fin)]
    return d


# --- Encabezado --------------------------------------------------------------
st.title("🤖 Chatbot de Autodiagnóstico")
st.caption(
    "Prototipo con datos de ejemplo. Pregunta sobre el proceso de autodiagnóstico "
    "y te respondo con cifras y gráficos."
)

PREGUNTAS_EJEMPLO = [
    "¿Cuántos autodiagnósticos hubo por canal?",
    "¿Cuántos por ciudad?",
    "¿A qué horas se hacen más autodiagnósticos?",
    "¿Cuántos terminaron en Resuelto, NOC u OPS?",
    "¿Cuál es el tiempo de resolución por funnel?",
    "Percentiles del tiempo de resolución",
    "¿Cuántos vuelven a intentar a las 24, 48 y 72 horas?",
    "¿Qué clientes repiten el proceso?",
]

with st.expander("💡 Ejemplos de preguntas que puedes hacer"):
    for q in PREGUNTAS_EJEMPLO:
        st.markdown(f"- {q}")


# --- Render de cada métrica --------------------------------------------------
def responder(pregunta: str, df: pd.DataFrame):
    """Enruta la pregunta a una métrica y muestra el resultado."""
    ruta = entender(pregunta)
    metrica = ruta["metrica"]
    filtros = ruta["filtros"]

    # Filtros adicionales detectados en la pregunta (ciudad/canal).
    if filtros.get("ciudad"):
        df = df[df["ciudad"] == filtros["ciudad"]]
    if filtros.get("canal"):
        df = df[df["canal"] == filtros["canal"]]

    if metrica is None:
        st.markdown(
            "No estoy seguro de qué medición quieres. Prueba con una de las "
            "preguntas de ejemplo de arriba 👆, o menciona: canal, ciudad, hora, "
            "funnel, resolución, percentiles, reopen o repetidores."
        )
        return

    titulo = metrics.CATALOGO[metrica][0]
    contexto = []
    if filtros.get("ciudad"):
        contexto.append(f"ciudad = {filtros['ciudad']}")
    if filtros.get("canal"):
        contexto.append(f"canal = {filtros['canal']}")
    sub = f"  ·  {', '.join(contexto)}" if contexto else ""
    st.markdown(f"### 📊 {titulo}{sub}")

    if df.empty:
        st.warning("No hay datos para esos filtros.")
        return

    # --- Presentación específica por métrica ---
    if metrica == "total_clientes":
        r = metrics.total_clientes(df)
        c1, c2 = st.columns(2)
        c1.metric("Clientes únicos", f"{r['clientes_unicos']:,}")
        c2.metric("Autodiagnósticos", f"{r['total_autodiagnosticos']:,}")

    elif metrica == "por_canal":
        g = metrics.por_canal(df)
        st.bar_chart(g["autodiagnosticos"])
        st.dataframe(g, use_container_width=True)

    elif metrica == "por_ciudad":
        g = metrics.por_ciudad(df)
        st.bar_chart(g["autodiagnosticos"])
        st.dataframe(g, use_container_width=True)

    elif metrica == "por_hora":
        s = metrics.por_hora(df)
        st.bar_chart(s)
        st.caption("Cantidad de autodiagnósticos por hora del día (0–23).")

    elif metrica == "por_dia_semana":
        s = metrics.por_dia_semana(df)
        st.bar_chart(s)

    elif metrica == "tiempo_por_funnel":
        g = metrics.tiempo_por_funnel(df)
        st.dataframe(g, use_container_width=True)
        st.bar_chart(g["duracion_promedio_min"])
        st.caption("Duración promedio del proceso (minutos) según cómo terminó el run.")

    elif metrica == "tipo_resolucion":
        r = metrics.tipo_resolucion(df)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Por tipo de resolución**")
            st.bar_chart(r["por_resolucion"])
        with c2:
            st.markdown("**Tipos de cierre (Resuelto)**")
            if not r["tipos_de_cierre"].empty:
                st.bar_chart(r["tipos_de_cierre"])
            else:
                st.info("Sin cierres para estos filtros.")

    elif metrica == "clientes_repetidores":
        g = metrics.clientes_repetidores(df)
        st.metric("Clientes que repiten (≥3) y quedaron resueltos", f"{len(g):,}")
        st.dataframe(g.head(50), use_container_width=True)
        st.caption(
            "Estos clientes repitieron el proceso y en algún momento quedó resuelto. "
            "Vale la pena investigar por qué siguen intentando."
        )

    elif metrica == "percentiles_resolucion":
        g = metrics.percentiles_resolucion(df)
        st.dataframe(g, use_container_width=True)
        st.line_chart(g.set_index("percentil")["horas"])
        st.caption("Horas hasta resolver el ticket, por percentil.")

    elif metrica == "reopen_fallidos":
        g = metrics.reopen_fallidos(df)
        st.dataframe(g, use_container_width=True)
        st.bar_chart(g.set_index("ventana")["reopens"])
        st.caption("Clientes con 'error' que repiten el autodiagnóstico en cada ventana.")

    elif metrica == "por_hora_y_ciudad":
        tabla = metrics.por_hora_y_ciudad(df)
        st.dataframe(tabla, use_container_width=True)
        st.line_chart(tabla)
        st.caption("Autodiagnósticos por hora del día, una línea por ciudad.")

    # Nota del motor usado.
    st.caption(f"_Interpretado con: {ruta['motor']}_")


# --- Chat --------------------------------------------------------------------
if "historial" not in st.session_state:
    st.session_state.historial = []

# Reproduce el historial.
for turno in st.session_state.historial:
    with st.chat_message(turno["rol"]):
        if turno["rol"] == "user":
            st.markdown(turno["texto"])
        else:
            responder(turno["texto"], aplicar_filtros(runs))

pregunta = st.chat_input("Escribe tu pregunta sobre el autodiagnóstico…")
if pregunta:
    with st.chat_message("user"):
        st.markdown(pregunta)
    with st.chat_message("assistant"):
        responder(pregunta, aplicar_filtros(runs))
    st.session_state.historial.append({"rol": "user", "texto": pregunta})
    st.session_state.historial.append({"rol": "assistant", "texto": pregunta})
