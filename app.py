"""
Chatbot de Autodiagnóstico — versión IA con datos de Redash.

Página web de chat, para uso interno, que responde preguntas LIBRES sobre el
proceso de autodiagnóstico. Los datos vienen de una consulta en Redash (vía su
API); si Redash no está configurado, usa el Excel de ejemplo como respaldo.

Cómo ejecutar (desde la carpeta del proyecto):
    .venv\\Scripts\\streamlit run app.py
"""

import hmac
import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import ai_analyst
import llm
import redash
import termometro

load_dotenv()

st.set_page_config(page_title="Chatbot Autodiagnóstico", page_icon="🤖", layout="wide")


# --- Control de acceso (usuario + clave) -------------------------------------
def _control_acceso() -> bool:
    """Muestra una pantalla de login. Devuelve True si el acceso está permitido.

    Las credenciales se leen de APP_USER / APP_PASSWORD (en .env local o en
    Secrets de Streamlit). Si no están configuradas, el acceso queda abierto
    (para no bloquear durante la configuración inicial)."""
    usuario_ok = os.environ.get("APP_USER", "")
    clave_ok = os.environ.get("APP_PASSWORD", "")

    if not clave_ok:  # sin credenciales configuradas -> acceso abierto
        return True
    if st.session_state.get("acceso_ok"):
        return True

    st.markdown("## 🔒 Acceso al Chatbot de Autodiagnóstico")
    st.caption("Ingresa tus credenciales para continuar.")
    with st.form("login"):
        u = st.text_input("Usuario")
        c = st.text_input("Contraseña", type="password")
        entrar = st.form_submit_button("Entrar")
    if entrar:
        if hmac.compare_digest(u, usuario_ok) and hmac.compare_digest(c, clave_ok):
            st.session_state.acceso_ok = True
            st.rerun()
        else:
            st.error("Usuario o contraseña incorrectos.")
    return False


if not _control_acceso():
    st.stop()


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
    with st.spinner("Actualizando desde Redash… tarda cerca de medio minuto."):
        try:
            # Corre la consulta DE NUEVO en Redash. Es lento, pero es lo que el
            # botón promete: el resultado en caché de Redash se recalcula una vez
            # al día, así que sin esto el termómetro mostraría datos de ayer.
            st.session_state.df = cargar_datos(refrescar=True)
            st.session_state.pop("error_carga", None)
            st.sidebar.success(f"Datos actualizados: {len(st.session_state.df):,} filas.")
            df_full = st.session_state.df
        except Exception as e:
            st.sidebar.error(f"No pude actualizar: {e}")

col_estado = buscar_columna(df_full, ["estado", "stage", "status"])
col_canal = buscar_columna(df_full, ["canal", "origen", "origin", "source", "channel"])
col_ciudad = buscar_columna(df_full, ["ciudad", "city", "locality"])
col_fecha = buscar_columna(df_full, ["fecha", "inicio", "started", "date", "created"])
col_outcome = buscar_columna(df_full, ["final_outcome", "outcome", "directriz"])
col_causa = buscar_columna(df_full, ["failure_reason", "causa"])

# Filtros seleccionados
sel_estado, sel_canal, sel_ciudad, sel_outcome = [], [], [], []
fecha_desde = fecha_hasta = None

if not df_full.empty:
    if col_outcome:
        opciones = sorted(df_full[col_outcome].dropna().astype(str).unique())
        sel_outcome = st.sidebar.multiselect(
            "Directriz entregada al cliente", opciones,
            help="Desenlace final que se le comunicó al cliente (ALL_OK, "
                 "TICKET_CREATED, CREDIT_RECHARGED, BLOCKED, CANCELED, ERROR).")
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
        fechas = pd.to_datetime(df_full[col_fecha], errors="coerce", utc=True)
        fmin = fechas.min()
        fmax = fechas.max()
        if pd.notna(fmin) and pd.notna(fmax):
            c1, c2 = st.sidebar.columns(2)
            fecha_desde = c1.date_input("Fecha inicio", value=fmin.date(),
                                        min_value=fmin.date(), max_value=fmax.date())
            fecha_hasta = c2.date_input("Hasta", value=fmax.date(),
                                        min_value=fmin.date(), max_value=fmax.date())
            st.sidebar.caption(
                "El rango de fechas aplica al chat. El termómetro siempre muestra "
                "un día completo, y ese día se elige en su propia pestaña."
            )

st.sidebar.markdown("---")


@st.cache_data(show_spinner=False)
def _modelo_en_uso() -> str | None:
    try:
        return llm.modelo_preferido()
    except Exception:
        return None


if llm.disponible():
    modelo = _modelo_en_uso() or "el más reciente disponible"
    st.sidebar.success(f"🧠 IA: ACTIVA\n\nGoogle Gemini ({modelo})")
else:
    st.sidebar.error("🧠 IA: SIN CONECTAR. Falta la clave GEMINI_API_KEY.")

st.sidebar.caption(f"Fuente de datos: {st.session_state.get('fuente', '—')}")


def aplicar_filtros(df: pd.DataFrame, incluir_fecha: bool = True) -> pd.DataFrame:
    """Aplica los filtros de la barra lateral. Con incluir_fecha=False se omite el
    rango de fechas (lo usa el termómetro, que tiene su propio selector de día)."""
    d = df
    if col_outcome and sel_outcome:
        d = d[d[col_outcome].astype(str).isin(sel_outcome)]
    if col_estado and sel_estado:
        d = d[d[col_estado].astype(str).isin(sel_estado)]
    if col_canal and sel_canal:
        d = d[d[col_canal].astype(str).isin(sel_canal)]
    if col_ciudad and sel_ciudad:
        d = d[d[col_ciudad].astype(str).isin(sel_ciudad)]
    if incluir_fecha and col_fecha and fecha_desde and fecha_hasta:
        try:
            # Normalizamos todo a UTC para evitar choques de tipo/zona horaria.
            f = pd.to_datetime(d[col_fecha], errors="coerce", utc=True)
            desde = pd.Timestamp(fecha_desde, tz="UTC")
            hasta = pd.Timestamp(fecha_hasta, tz="UTC") + pd.Timedelta(days=1)
            en_rango = (f >= desde) & (f < hasta)
            # Mantener filas sin fecha válida (no descartarlas en silencio).
            d = d[en_rango | f.isna()]
        except Exception:
            pass  # ante cualquier problema con fechas, no filtramos por fecha (no rompemos la app)
    return d


# --- Encabezado --------------------------------------------------------------
st.title("🤖 Chatbot de Autodiagnóstico")

if "error_carga" in st.session_state:
    st.error(f"No pude cargar los datos: {st.session_state.error_carga}")

df_filtrado = aplicar_filtros(df_full) if not df_full.empty else df_full

# Dos pestañas: el chat de preguntas libres y el dashboard por hora.
tab_chat, tab_termometro = st.tabs(["💬  Chat", "🌡️  Termómetro por hora"])


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


# --- Pestaña 1: chat ---------------------------------------------------------
if "historial" not in st.session_state:
    st.session_state.historial = []

with tab_chat:
    col_intro, col_reset = st.columns([4, 1])
    with col_intro:
        st.caption(
            "Pregúntame lo que quieras sobre los autodiagnósticos. Entiendo preguntas "
            "libres y respondo con cifras y gráficos consultando los datos."
        )
        if not df_full.empty:
            st.caption(f"Registros tras filtros: **{len(df_filtrado):,}** "
                       f"de {len(df_full):,}")
    with col_reset:
        if st.button("🔄 Reiniciar chat", use_container_width=True,
                     help="Borra la conversación y empieza de cero (sin recargar la página)."):
            st.session_state.historial = []
            st.rerun()

    for turno in st.session_state.historial:
        with st.chat_message(turno["rol"]):
            if turno["rol"] == "user":
                st.markdown(turno["texto"])
            else:
                render_resultado(turno["resultado"])

    pregunta = st.chat_input("Escribe tu pregunta sobre los autodiagnósticos…")
    if pregunta:
        historial_previo = list(st.session_state.historial)  # memoria de turnos anteriores
        with st.chat_message("user"):
            st.markdown(pregunta)
        st.session_state.historial.append({"rol": "user", "texto": pregunta})
        with st.chat_message("assistant"):
            with st.spinner("Consultando los datos…"):
                res = ai_analyst.responder(pregunta, df_filtrado, historial=historial_previo)
            render_resultado(res)
        st.session_state.historial.append({"rol": "assistant", "resultado": res})

# --- Pestaña 2: termómetro por hora ------------------------------------------
# Hereda los filtros de la barra lateral MENOS el de fecha: el día lo elige el
# propio dashboard, porque siempre muestra un día completo hora por hora.
with tab_termometro:
    termometro.render(aplicar_filtros(df_full, incluir_fecha=False),
                      col_fecha, col_causa, col_canal, col_ciudad)
