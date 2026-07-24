"""
El "cerebro" de IA del chatbot.

Convierte una pregunta en lenguaje natural en una consulta SQL sobre los datos
de autodiagnósticos, la ejecuta de forma segura y redacta una respuesta en
español. Así el chatbot responde preguntas LIBRES, no una lista predefinida.

Flujo:
  1. Claude lee la pregunta + la descripción de la tabla -> genera una consulta SQL.
  2. Se valida que la consulta sea de solo lectura (SELECT) y se ejecuta en DuckDB.
  3. Claude lee el resultado -> redacta la respuesta en español.

El número SIEMPRE sale de los datos (paso 2); la IA solo traduce y explica.
Requiere una clave de API de Claude (ANTHROPIC_API_KEY).
"""

import re

import duckdb
import pandas as pd
from pydantic import BaseModel, Field

import llm

TABLA = "autodiagnosticos"
LIMITE_FILAS = 2000  # tope de filas que puede devolver una consulta

# Palabras prohibidas en la SQL (solo permitimos lectura).
PROHIBIDAS = re.compile(
    r"\b(insert|update|delete|drop|create|alter|attach|copy|install|load|"
    r"pragma|export|import|call|set|system|read_csv|read_parquet|read_json)\b",
    re.IGNORECASE,
)


class ConsultaSQL(BaseModel):
    sql: str = Field(description="Consulta SQL (SELECT) para DuckDB que responde la pregunta. Vacío si no se puede.")
    tipo_grafico: str = Field(description="Tipo de gráfico sugerido: 'barras', 'lineas' o 'ninguno'.")
    columna_x: str = Field(description="Nombre de la columna para el eje X del gráfico, o cadena vacía si no aplica.")
    se_puede_responder: bool = Field(description="True si la pregunta se puede responder con esta tabla; False si no.")


# Descripciones de columnas conocidas (para que la IA no confunda campos parecidos).
# Solo se agregan si la columna existe en los datos.
PISTAS_COLUMNAS = {
    "source": "canal/origen del autodiagnóstico (portal, whatsapp, sysbrazo).",
    "status": "resultado del PROCESO de autodiagnóstico: 'finished'=completado, "
              "'failed'=falló, 'canceled'=escaló a ticket, 'running'=en curso. "
              "NO es el estado del ticket.",
    "duration_seconds": "cuánto duró el proceso, en segundos.",
    "duracion_min": "cuánto duró el proceso, en minutos.",
    "failure_reason": "causa técnica por la que falló el autodiagnóstico.",
    "failed_step": "paso del flujo donde falló.",
    "odoo_ticket_id": "id del ticket (si el proceso escaló).",
    "ticket_ref": "referencia/número del ticket.",
    "ticket_name": "nombre del ticket.",
    "ticket_stage": "ESTADO del ticket: 'New'=abierto, 'In Progress'=en gestión, "
                    "'Solved'=resuelto. Úsalo para saber si un ticket está resuelto.",
    "ticket_team": "equipo/área que atiende el ticket (ej. NOC, Instalaciones y "
                   "Mantenimiento, Customer Experience (CX), Planta externa).",
    "ticket_type": "tipo/categoría del ticket.",
    "ticket_opening_reason": "motivo de apertura del ticket.",
    "ticket_close_reason": "motivo de cierre del ticket.",
    "ticket_create_date": "fecha/hora de apertura del ticket.",
    "ticket_close_date": "fecha/hora de cierre del ticket.",
    "ticket_resolucion_horas": "horas que tardó en resolverse el ticket "
                               "(cierre - apertura). Úsalo para 'qué tan rápido "
                               "resuelven'. Solo tiene valor si el ticket ya cerró.",
    "nombre_ciudad": "ciudad del cliente.",
    "started_at": "fecha/hora de inicio del autodiagnóstico.",
    "finished_at": "fecha/hora de fin del autodiagnóstico.",
    "client_id": "id del cliente.",
    "client_name": "nombre del cliente.",
}


def esquema_texto(df: pd.DataFrame) -> str:
    """Describe la tabla REAL (columnas, tipos y valores) para que la IA sepa consultar."""
    lineas = []
    for c in df.columns:
        dt = str(df[c].dtype)
        info = f"  - \"{c}\" ({dt})"
        if c in PISTAS_COLUMNAS:
            info += f" — {PISTAS_COLUMNAS[c]}"
        try:
            distintos = df[c].nunique(dropna=True)
        except TypeError:
            distintos = None
        if "datetime" in dt:
            try:
                info += f" — rango: {df[c].min()} a {df[c].max()}"
            except Exception:
                pass
        elif df[c].dtype == object or (distintos is not None and distintos <= 25):
            vals = [str(v) for v in df[c].dropna().unique()[:20]]
            if vals:
                info += " — valores: " + ", ".join(vals)
        lineas.append(info)
    columnas = "\n".join(lineas)
    return (
        f"Tabla: {TABLA} (una fila = un autodiagnóstico). Motor: DuckDB (dialecto SQL).\n"
        f"Columnas reales:\n{columnas}\n\n"
        "Notas:\n"
        "- Usa los valores EXACTOS mostrados arriba (respeta tildes y mayúsculas) al filtrar texto.\n"
        "- Los nombres de columna pueden tener espacios/tildes: enciérralos en comillas dobles.\n"
        "- Para percentiles usa QUANTILE_CONT (ej. QUANTILE_CONT(columna, 0.9)).\n"
        "- Devuelve columnas de salida con nombres legibles (alias en español)."
    )


def validar_sql(sql: str) -> str | None:
    """Devuelve un mensaje de error si la SQL no es segura; None si está OK."""
    s = sql.strip().rstrip(";").strip()
    if not re.match(r"^\s*(select|with)\b", s, re.IGNORECASE):
        return "La consulta debe empezar con SELECT o WITH."
    if PROHIBIDAS.search(s):
        return "La consulta contiene una operación no permitida (solo lectura)."
    if ";" in s:
        return "Solo se permite una consulta a la vez."
    return None


def generar_sql(pregunta: str, df: pd.DataFrame) -> dict:
    """Paso 1: la IA traduce la pregunta a SQL. Devuelve dict con sql y metadatos."""
    system = (
        "Eres un analista de datos que responde preguntas sobre un proceso "
        "llamado 'autodiagnóstico' (diagnóstico del módem de wifi de clientes). "
        "Traduce la pregunta del usuario a UNA consulta SQL de solo lectura "
        "(SELECT) sobre la tabla descrita abajo. No inventes columnas.\n\n"
        f"{esquema_texto(df)}\n\n"
        "Si la pregunta NO se puede responder con esta tabla, pon "
        "se_puede_responder=false y deja sql vacío."
    )
    r = llm.generar_json(system, pregunta, ConsultaSQL)
    columna_x = (r.columna_x or "").strip() if r else ""
    return {
        "sql": (r.sql or "").strip() if r else "",
        "tipo_grafico": (r.tipo_grafico or "ninguno") if r else "ninguno",
        "columna_x": columna_x or None,
        "se_puede_responder": bool(r.se_puede_responder) if r else False,
    }


def ejecutar_sql(df: pd.DataFrame, sql: str) -> pd.DataFrame:
    """Paso 2: ejecuta la SQL de solo lectura sobre el DataFrame, con candado."""
    con = duckdb.connect()
    con.execute("SET enable_external_access=false")
    con.register(TABLA, df)
    resultado = con.execute(sql).df()
    if len(resultado) > LIMITE_FILAS:
        resultado = resultado.head(LIMITE_FILAS)
    return resultado


def redactar_respuesta(pregunta: str, resultado: pd.DataFrame) -> str:
    """Paso 3: la IA redacta una respuesta en español a partir del resultado."""
    muestra = resultado.head(50).to_csv(index=False)
    system = (
        "Eres un analista que explica resultados de datos a una persona no "
        "técnica, en español, de forma breve y clara. Te doy la pregunta y el "
        "resultado (en CSV) de una consulta ya ejecutada sobre datos reales. "
        "Responde la pregunta directamente citando las cifras del resultado. "
        "No inventes datos que no estén en el resultado. Si el resultado está "
        "vacío, dilo. Máximo 4 frases; la tabla y el gráfico se muestran aparte."
    )
    user = f"Pregunta: {pregunta}\n\nResultado de la consulta (CSV):\n{muestra}"
    return llm.generar_texto(system, user, max_tokens=600)


def responder(pregunta: str, df: pd.DataFrame) -> dict:
    """
    Punto de entrada. Devuelve un dict:
      {texto, tabla (DataFrame|None), sql, tipo_grafico, columna_x, error}
    """
    salida = {"texto": "", "tabla": None, "sql": "", "tipo_grafico": "ninguno",
              "columna_x": None, "error": None}

    if not llm.disponible():
        salida["error"] = (
            "La IA no está conectada. Falta configurar una clave de API "
            "(GEMINI_API_KEY o ANTHROPIC_API_KEY) en el archivo .env (local) o en "
            "la sección Secrets (Streamlit Cloud)."
        )
        return salida

    try:
        plan = generar_sql(pregunta, df)
    except Exception as e:
        salida["error"] = f"No pude interpretar la pregunta con la IA: {e}"
        return salida

    if not plan["se_puede_responder"] or not plan["sql"]:
        salida["texto"] = (
            "Esa pregunta no la puedo responder con los datos disponibles de "
            "autodiagnósticos. Intenta preguntar sobre canales, ciudades, "
            "resultados, tiempos, tickets o áreas responsables."
        )
        return salida

    salida["sql"] = plan["sql"]
    salida["tipo_grafico"] = plan["tipo_grafico"]
    salida["columna_x"] = plan["columna_x"]

    error_sql = validar_sql(plan["sql"])
    if error_sql:
        salida["error"] = f"La consulta generada no es segura: {error_sql}"
        return salida

    try:
        tabla = ejecutar_sql(df, plan["sql"])
    except Exception as e:
        salida["error"] = f"La consulta falló al ejecutarse: {e}"
        return salida

    salida["tabla"] = tabla

    if tabla.empty:
        salida["texto"] = (
            "La consulta corrió bien, pero **no encontró filas que cumplan la "
            "condición**. Posibles razones:\n"
            "- Hay **filtros activos** en la barra izquierda que dejan 0 registros "
            "(revisa Estado/Canal/Ciudad/Fechas).\n"
            "- En el periodo cargado hay **muy pocos tickets ya resueltos** (los "
            "recientes siguen abiertos), así que no hay datos que promediar aún.\n\n"
            "Tip: amplía el rango de fechas o quita filtros, y vuelve a preguntar."
        )
        return salida

    try:
        salida["texto"] = redactar_respuesta(pregunta, tabla)
    except Exception as e:
        # Si falla la redacción, al menos mostramos la tabla.
        salida["texto"] = f"(No pude redactar el resumen, pero aquí está el resultado.) [{e}]"

    return salida
