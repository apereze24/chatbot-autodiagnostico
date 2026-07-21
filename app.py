"""
Chatbot de Autodiagnóstico — versión IA (preguntas libres).

Página web de chat, para uso interno, que responde preguntas LIBRES sobre el
proceso de autodiagnóstico consultando los datos del archivo Excel. Usa la IA de
Claude para entender la pregunta, consultar los datos y responder en español.

Cómo ejecutar (desde la carpeta del proyecto):
    .venv\\Scripts\\streamlit run app.py
"""

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import ai_analyst
import llm
from data_source import cargar

load_dotenv()  # lee ANTHROPIC_API_KEY desde un archivo .env si existe

st.set_page_config(page_title="Chatbot Autodiagnóstico", page_icon="🤖", layout="wide")


@st.cache_data
def cargar_datos() -> pd.DataFrame:
    return cargar()


df = cargar_datos()


# --- Barra lateral -----------------------------------------------------------
st.sidebar.title("ℹ️ Sobre los datos")
st.sidebar.markdown(
    f"""
- **Registros:** {len(df):,}
- **Periodo:** {df['fecha'].min()} a {df['fecha'].max()}
- **Canales:** Sysbrazo, Portal web, Botmaker
- **Ciudades:** {df['ciudad'].nunique()}
- **Con ticket:** {(df['genero_ticket'] == 'Sí').sum():,}
"""
)
st.sidebar.markdown("---")
if llm.disponible():
    st.sidebar.success(f"🧠 IA: ACTIVA\n\n{llm.nombre_legible()}")
    with st.sidebar.expander("🔧 Ver modelos disponibles de mi clave"):
        st.caption(
            "Útil para elegir el modelo. Si quieres forzar uno (ej. Pro), agrégalo "
            "en Secrets como `GEMINI_MODEL = \"nombre-del-modelo\"`."
        )
        if st.button("Listar modelos"):
            try:
                modelos = llm.listar_modelos()
                if modelos:
                    st.write(modelos)
                else:
                    st.info("No se obtuvieron modelos (¿es proveedor Gemini?).")
            except Exception as e:
                st.error(f"No pude listar modelos: {e}")
else:
    st.sidebar.error(
        "🧠 IA: SIN CONECTAR.\n\n"
        "Este chatbot necesita una clave (GEMINI_API_KEY o ANTHROPIC_API_KEY) "
        "para entender preguntas libres. Configúrala en `.env` (local) o en "
        "*Secrets* (Streamlit Cloud)."
    )


# --- Encabezado --------------------------------------------------------------
st.title("🤖 Chatbot de Autodiagnóstico")
st.caption(
    "Pregúntame lo que quieras sobre los autodiagnósticos. Entiendo preguntas "
    "libres y respondo con cifras y gráficos consultando los datos."
)

with st.expander("💡 Ejemplos de preguntas (puedes preguntar cualquier cosa)"):
    st.markdown(
        "- ¿Cuántos autodiagnósticos fallidos hubo en Cartagena?\n"
        "- ¿Cuál es el canal con más procesos escalados?\n"
        "- ¿Qué área resuelve más rápido sus tickets?\n"
        "- ¿A qué hora del día hay más actividad en Botmaker?\n"
        "- ¿Cuántos tickets siguen abiertos por ciudad?\n"
        "- ¿Cuál es el tiempo promedio de resolución de los tickets del NOC?\n"
        "- Dame los 5 clientes con más autodiagnósticos"
    )


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
        # Gráfico, si aplica y tiene sentido.
        tipo = res.get("tipo_grafico", "ninguno")
        col_x = res.get("columna_x")
        try:
            if tipo in ("barras", "lineas") and col_x in tabla.columns:
                num = tabla.select_dtypes(include="number").columns.tolist()
                num = [c for c in num if c != col_x]
                if num:
                    datos = tabla.set_index(col_x)[num]
                    if tipo == "barras":
                        st.bar_chart(datos)
                    else:
                        st.line_chart(datos)
        except Exception:
            pass  # si el gráfico falla, igual mostramos la tabla

        st.dataframe(tabla, use_container_width=True, hide_index=True)

    if res.get("sql"):
        with st.expander("🔍 Cómo lo calculé (consulta a los datos)"):
            st.code(res["sql"], language="sql")


# --- Chat --------------------------------------------------------------------
if "historial" not in st.session_state:
    st.session_state.historial = []

# Reproduce el historial (sin volver a llamar a la IA).
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
            res = ai_analyst.responder(pregunta, df)
        render_resultado(res)
    st.session_state.historial.append({"rol": "assistant", "resultado": res})
