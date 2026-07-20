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

import os
import re

import duckdb
import pandas as pd

from data_source import DESCRIPCION_COLUMNAS

TABLA = "autodiagnosticos"
LIMITE_FILAS = 2000  # tope de filas que puede devolver una consulta

# Palabras prohibidas en la SQL (solo permitimos lectura).
PROHIBIDAS = re.compile(
    r"\b(insert|update|delete|drop|create|alter|attach|copy|install|load|"
    r"pragma|export|import|call|set|system|read_csv|read_parquet|read_json)\b",
    re.IGNORECASE,
)


def _modelo() -> str:
    return os.environ.get("CLAUDE_MODEL", "claude-opus-4-8")


def esquema_texto() -> str:
    """Descripción de la tabla para que la IA sepa qué columnas consultar."""
    cols = "\n".join(f"  - {c}: {d}" for c, d in DESCRIPCION_COLUMNAS.items())
    return (
        f"Tabla: {TABLA} (una fila = un autodiagnóstico). Motor: DuckDB (dialecto SQL).\n"
        f"Columnas:\n{cols}\n\n"
        "Notas importantes:\n"
        "- Los datos cubren mayo y junio de 2026.\n"
        "- Usa los valores EXACTOS (con tildes) al filtrar texto: "
        "canal ∈ {'Sysbrazo','Portal web','Botmaker'}; "
        "resultado ∈ {'Completado ok','Escalado','Fallido'}; "
        "genero_ticket ∈ {'Sí','No'}; "
        "estado_ticket ∈ {'Abierto','En Gestión','Solucionado'}; "
        "area_responsable ∈ {'Customer','Operaciones','NOC'}.\n"
        "- Para tiempos de resolución de tickets usa 'resol_horas' (solo tiene "
        "valor cuando hubo ticket).\n"
        "- Para percentiles usa QUANTILE_CONT (ej. QUANTILE_CONT(resol_horas, 0.9)).\n"
        "- Devuelve columnas con nombres legibles (usa alias en español)."
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


def generar_sql(pregunta: str) -> dict:
    """Paso 1: Claude traduce la pregunta a SQL. Devuelve dict con sql y metadatos."""
    import anthropic
    from pydantic import BaseModel, Field

    class ConsultaSQL(BaseModel):
        sql: str = Field(description="Consulta SQL (SELECT) para DuckDB que responde la pregunta.")
        tipo_grafico: str = Field(description="Tipo de gráfico sugerido: 'barras', 'lineas' o 'ninguno'.")
        columna_x: str | None = Field(description="Nombre de la columna a usar como eje X del gráfico, o null.")
        se_puede_responder: bool = Field(description="True si la pregunta se puede responder con esta tabla; False si no.")

    client = anthropic.Anthropic()
    resp = client.messages.parse(
        model=_modelo(),
        max_tokens=1000,
        system=(
            "Eres un analista de datos que responde preguntas sobre un proceso "
            "llamado 'autodiagnóstico' (diagnóstico del módem de wifi de clientes). "
            "Traduce la pregunta del usuario a UNA consulta SQL de solo lectura "
            "(SELECT) sobre la tabla descrita abajo. No inventes columnas.\n\n"
            f"{esquema_texto()}\n\n"
            "Si la pregunta NO se puede responder con esta tabla, pon "
            "se_puede_responder=false y deja sql vacío."
        ),
        messages=[{"role": "user", "content": pregunta}],
        output_format=ConsultaSQL,
    )
    r = resp.parsed_output
    return {
        "sql": (r.sql or "").strip() if r else "",
        "tipo_grafico": (r.tipo_grafico or "ninguno") if r else "ninguno",
        "columna_x": r.columna_x if r else None,
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
    """Paso 3: Claude redacta una respuesta en español a partir del resultado."""
    import anthropic

    muestra = resultado.head(50).to_csv(index=False)
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=_modelo(),
        max_tokens=600,
        system=(
            "Eres un analista que explica resultados de datos a una persona no "
            "técnica, en español, de forma breve y clara. Te doy la pregunta y el "
            "resultado (en CSV) de una consulta ya ejecutada sobre datos reales. "
            "Responde la pregunta directamente citando las cifras del resultado. "
            "No inventes datos que no estén en el resultado. Si el resultado está "
            "vacío, dilo. Máximo 4 frases; la tabla y el gráfico se muestran aparte."
        ),
        messages=[{
            "role": "user",
            "content": f"Pregunta: {pregunta}\n\nResultado de la consulta (CSV):\n{muestra}",
        }],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def responder(pregunta: str, df: pd.DataFrame) -> dict:
    """
    Punto de entrada. Devuelve un dict:
      {texto, tabla (DataFrame|None), sql, tipo_grafico, columna_x, error}
    """
    salida = {"texto": "", "tabla": None, "sql": "", "tipo_grafico": "ninguno",
              "columna_x": None, "error": None}

    if not os.environ.get("ANTHROPIC_API_KEY"):
        salida["error"] = (
            "La IA no está conectada. Falta configurar la clave ANTHROPIC_API_KEY "
            "(en local: archivo .env; en Streamlit Cloud: sección Secrets)."
        )
        return salida

    try:
        plan = generar_sql(pregunta)
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

    try:
        salida["texto"] = redactar_respuesta(pregunta, tabla)
    except Exception as e:
        # Si falla la redacción, al menos mostramos la tabla.
        salida["texto"] = f"(No pude redactar el resumen, pero aquí está el resultado.) [{e}]"

    return salida
