"""
Chatbot de Autodiagnóstico — versión IA con datos de Redash.

Página web de chat, para uso interno, que responde preguntas LIBRES sobre el
proceso de autodiagnóstico. Los datos vienen de una consulta en Redash (vía su
API); si Redash no está configurado, usa el Excel de ejemplo como respaldo.

Cómo ejecutar (desde la carpeta del proyecto):
    .venv\\Scripts\\streamlit run app.py
"""

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import ai_analyst
import llm
import redash

load_dotenv()

st.set_page_config(page_title="Chatbot Autodiagnóstico", page_icon="🤖", layout="wide")


# --- Carga de datos ----------------------------------------------------------
def cargar_datos(refrescar: bool = False) -> pd.DataFrame:
    """Trae los datos desde Redash; si no está configurado, usa el Excel de ejemplo."""
    if redash.configurado():
        return redash.obtener_datos(refrescar=refrescar)
    from data_source import cargar  # respaldo: datos de ejemplo
    return cargar()


if "df" not in st.session_state:
    with st.spinner("Cargando datos…"):
        try:
            st.session_state.df = cargar_datos()
            st.session_state.fuente = "Redash" if redash.configurado() else "Excel de ejemplo"
        except Exception as e:
            st.session_state.df = pd.DataFrame()
            st.session_state.error_carga = str(e)

df_full = st.session_state.get("df", pd.DataFrame())


# --- Utilidad: encontrar una columna por posibles nombres --------------------
def buscar_columna(df: pd.DataFrame, candidatos: list[str]) -> str | None:
    cols_lower = {c.lower(): c for c in df.columns}
    for cand in candidatos:
        for low, original in cols_lower.items():
            if cand in low:
                return original
    return None


# --- Barra lateral: filtros + actualizar -------------------------------------
st.sidebar.title("🔎 Filtros")

if st.sidebar.button("🔄 Actualizar datos", use_container_width=True):
    with st.spinner("Actualizando desde Redash…"):
        try:
            st.session_state.df = cargar_datos(refrescar=True)
            st.session_state.pop("error_carga", None)
            st.sidebar.success("Datos actualizados.")
            df_full = st.session_state.df
        except Exception as e:
            st.sidebar.error(f"No pude actualizar: {e}")

col_estado = buscar_columna(df_full, ["estado", "stage", "status"])
col_canal = buscar_columna(df_full, ["canal", "origen", "origin", "source", "channel"])
col_ciudad = buscar_columna(df_full, ["ciudad", "city", "locality"])
col_fecha = buscar_columna(df_full, ["fecha", "inicio", "started", "date", "created"])

# Filtros seleccionados
sel_estado, sel_canal, sel_ciudad = [], [], []
fecha_desde = fecha_hasta = None

if not df_full.empty:
    if col_estado:
        opciones = sorted(df_full[col_estado].dropna().astype(str).unique())
        sel_estado = st.sidebar.multiselect("Estado del ticket", opciones)
    if col_canal:
        opciones = sorted(df_full[col_canal].dropna().astype(str).unique())
        sel_canal = st.sidebar.multiselect("Canal", opciones)
    if col_ciudad:
        opciones = sorted(df_full[col_ciudad].dropna().astype(str).unique())
        sel_ciudad = st.sidebar.multiselect("Ciudad", opciones)
    if col_fecha:
        fechas = pd.to_datetime(df_full[col_fecha], errors="coerce")
        fmin = fechas.min()
        fmax = fechas.max()
        if pd.notna(fmin) and pd.notna(fmax):
            c1, c2 = st.sidebar.columns(2)
            fecha_desde = c1.date_input("Fecha inicio", value=fmin.date(),
                                        min_value=fmin.date(), max_value=fmax.date())
            fecha_hasta = c2.date_input("Hasta", value=fmax.date(),
                                        min_value=fmin.date(), max_value=fmax.date())

st.sidebar.markdown("---")
if llm.disponible():
    st.sidebar.success(f"🧠 IA: ACTIVA\n\n{llm.nombre_legible()}")
else:
    st.sidebar.error(
        "🧠 IA: SIN CONECTAR. Falta GEMINI_API_KEY o ANTHROPIC_API_KEY."
    )
st.sidebar.caption(f"Fuente de datos: {st.session_state.get('fuente', '—')}")


def aplicar_filtros(df: pd.DataFrame) -> pd.DataFrame:
    d = df
    if col_estado and sel_estado:
        d = d[d[col_estado].astype(str).isin(sel_estado)]
    if col_canal and sel_canal:
        d = d[d[col_canal].astype(str).isin(sel_canal)]
    if col_ciudad and sel_ciudad:
        d = d[d[col_ciudad].astype(str).isin(sel_ciudad)]
    if col_fecha and fecha_desde and fecha_hasta:
        f = pd.to_datetime(d[col_fecha], errors="coerce").dt.date
        d = d[(f >= fecha_desde) & (f <= fecha_hasta)]
    return d


# --- Encabezado --------------------------------------------------------------
st.title("🤖 Chatbot de Autodiagnóstico")
st.caption(
    "Pregúntame lo que quieras sobre los autodiagnósticos. Entiendo preguntas "
    "libres y respondo con cifras y gráficos consultando los datos."
)

if "error_carga" in st.session_state:
    st.error(f"No pude cargar los datos: {st.session_state.error_carga}")

if not df_full.empty:
    df_filtrado = aplicar_filtros(df_full)
    st.caption(f"Registros tras filtros: **{len(df_filtrado):,}** de {len(df_full):,}")
else:
    df_filtrado = df_full


# --- Render de un resultado --------------------------------------------------
def render_resultado(res: dict):
    if res.get("error"):
        st.error(res["error"])
        if res.get("sql"):
            with st.expander("Ver la consulta que se intentó"):
                st.code(res["sql"], language="sql")
        return
    if res.get("texto"):
        st.markdown(res["texto"])
    tabla = res.get("tabla")
    if tabla is not None and not tabla.empty:
        tipo = res.get("tipo_grafico", "ninguno")
        col_x = res.get("columna_x")
        try:
            if tipo in ("barras", "lineas") and col_x in tabla.columns:
                num = [c for c in tabla.select_dtypes(include="number").columns if c != col_x]
                if num:
                    datos = tabla.set_index(col_x)[num]
                    (st.bar_chart if tipo == "barras" else st.line_chart)(datos)
        except Exception:
            pass
        st.dataframe(tabla, use_container_width=True, hide_index=True)
    if res.get("sql"):
        with st.expander("🔍 Cómo lo calculé (consulta a los datos)"):
            st.code(res["sql"], language="sql")


# --- Chat --------------------------------------------------------------------
if "historial" not in st.session_state:
    st.session_state.historial = []

for turno in st.session_state.historial:
    with st.chat_message(turno["rol"]):
        if turno["rol"] == "user":
            st.markdown(turno["texto"])
        else:
            render_resultado(turno["resultado"])

pregunta = st.chat_input("Escribe tu pregunta sobre los autodiagnósticos…")
if pregunta:
    with st.chat_message("user"):
        st.markdown(pregunta)
    st.session_state.historial.append({"rol": "user", "texto": pregunta})
    with st.chat_message("assistant"):
        with st.spinner("Consultando los datos…"):
            res = ai_analyst.responder(pregunta, df_filtrado)
        render_resultado(res)
    st.session_state.historial.append({"rol": "assistant", "resultado": res})
