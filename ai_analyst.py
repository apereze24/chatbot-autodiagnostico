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
from pydantic import BaseModel, Field

import llm

TABLA = "autodiagnosticos"
LIMITE_FILAS = 2000  # tope de filas que puede devolver una consulta

# Conocimiento del negocio editable por el usuario (glosario, reglas, métricas).
ARCHIVO_CONOCIMIENTO = "conocimiento.md"


def conocimiento_negocio() -> str:
    """Lee conocimiento.md. Si no existe, no pasa nada (el chatbot sigue igual)."""
    try:
        ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            ARCHIVO_CONOCIMIENTO)
        with open(ruta, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


# Ejemplos de referencia: enseñan a la IA el ESTILO de consulta esperado.
# No son respuestas fijas; guían cómo estructurar SQL para preguntas nuevas.
EJEMPLOS = """
Ejemplos del tipo de consulta esperada (adapta la lógica a la pregunta real):

P: ¿Cuál es la tasa de éxito por canal?
SQL: SELECT source AS canal, COUNT(*) AS total,
       COUNT(*) FILTER (WHERE status='finished') AS completados,
       ROUND(100.0*COUNT(*) FILTER (WHERE status='finished')/COUNT(*),1) AS pct_exito
     FROM autodiagnosticos GROUP BY source ORDER BY pct_exito DESC

P: ¿Qué equipo resuelve más rápido los tickets?
SQL: SELECT ticket_team AS equipo, COUNT(*) AS tickets_resueltos,
       ROUND(AVG(ticket_resolucion_horas),1) AS horas_promedio,
       ROUND(QUANTILE_CONT(ticket_resolucion_horas,0.5),1) AS horas_mediana
     FROM autodiagnosticos
     WHERE ticket_stage='Solved' AND ticket_resolucion_horas IS NOT NULL
     GROUP BY ticket_team ORDER BY horas_promedio ASC

P: ¿Cuántos autodiagnósticos hubo mes a mes?
SQL: SELECT strftime(started_at,'%Y-%m') AS mes, COUNT(*) AS total
     FROM autodiagnosticos WHERE started_at IS NOT NULL
     GROUP BY 1 ORDER BY 1

P: ¿Cuáles son las principales causas de falla?
SQL: SELECT failure_reason AS causa, COUNT(*) AS casos,
       ROUND(100.0*COUNT(*)/SUM(COUNT(*)) OVER (),1) AS pct
     FROM autodiagnosticos WHERE failure_reason IS NOT NULL
     GROUP BY failure_reason ORDER BY casos DESC
""".strip()

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
    "final_outcome": "DIRECTRIZ FINAL entregada al cliente al terminar el "
                     "autodiagnóstico (el desenlace que se le comunicó). Valores: "
                     "'ALL_OK'=todo bien, sin problema; "
                     "'TICKET_CREATED'=se generó un ticket para revisión manual; "
                     "'CREDIT_RECHARGED'=se recargó crédito al cliente; "
                     "'BLOCKED'=proceso bloqueado (ej. incidente abierto); "
                     "'CANCELED'=el proceso se canceló; "
                     "'ERROR'=hubo un error técnico. "
                     "Úsala para preguntas sobre QUÉ SE LE DIJO/ENTREGÓ al cliente, "
                     "o el desenlace/resultado final del autodiagnóstico. "
                     "IMPORTANTE: este registro empezó a capturarse recientemente, "
                     "así que los autodiagnósticos anteriores lo tienen vacío (NULL). "
                     "Al analizarla, filtra 'final_outcome IS NOT NULL' para no "
                     "mezclar los registros que aún no tenían este dato.",
    "nombre_ciudad": "ciudad del cliente.",
    "started_at": "fecha/hora de inicio del autodiagnóstico. ÚSALA para análisis "
                  "temporal (por mes, semana, día, hora).",
    "finished_at": "fecha/hora de fin del autodiagnóstico.",
    "created_at": "fecha/hora de registro de la fila; para análisis temporal prefiere started_at.",
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


def generar_sql(pregunta: str, df: pd.DataFrame, historial=None,
                error_previo: str = "", sql_previo: str = "") -> dict:
    """Paso 1: la IA traduce la pregunta a SQL. Devuelve dict con sql y metadatos.
    Si se pasa error_previo, la IA corrige su intento anterior."""
    conocimiento = conocimiento_negocio()
    bloque_conocimiento = (
        f"\n\n=== CONOCIMIENTO DEL NEGOCIO ===\n{conocimiento}\n"
        if conocimiento else ""
    )
    system = (
        "Eres un analista de datos senior especializado en el proceso de "
        "'autodiagnóstico' (diagnóstico remoto del módem de wifi de clientes de "
        "un operador de internet). Traduce la pregunta del usuario a UNA consulta "
        "SQL de solo lectura (SELECT) sobre la tabla descrita abajo.\n\n"
        "Antes de escribir el SQL, razona: ¿qué está preguntando realmente? "
        "¿qué columnas lo responden? ¿hay que excluir nulos o filtrar algún "
        "estado? ¿conviene mostrar también el conteo o el porcentaje para dar "
        "contexto? Prefiere respuestas que aporten perspectiva (totales, "
        "porcentajes, comparativas) sobre cifras sueltas, sin desviarte de lo "
        "que se preguntó.\n\n"
        f"{esquema_texto(df)}"
        f"{bloque_conocimiento}\n"
        f"{EJEMPLOS}\n\n"
        "Mantienes una conversación: si la pregunta es un seguimiento (ej. "
        "'¿y por ciudad?', 'desglósalo por mes', 'y de esos, cuántos fallaron'), "
        "úsala junto con los turnos anteriores para entender a qué se refiere.\n"
        "No inventes columnas: usa solo las listadas. "
        "Si la pregunta NO se puede responder con esta tabla, pon "
        "se_puede_responder=false y deja sql vacío."
    )
    entrada = pregunta
    if error_previo:
        entrada = (
            f"{pregunta}\n\n"
            f"[Tu consulta anterior falló. Corrígela.]\n"
            f"SQL que falló:\n{sql_previo}\n"
            f"Error de la base de datos:\n{error_previo}\n"
            f"Devuelve una consulta corregida que evite ese error."
        )
    r = llm.generar_json(system, entrada, ConsultaSQL, historial=historial)
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


def redactar_respuesta(pregunta: str, resultado: pd.DataFrame, historial=None) -> str:
    """Paso 3: la IA redacta una respuesta en español a partir del resultado."""
    muestra = resultado.head(50).to_csv(index=False)
    system = (
        "Eres un analista que explica resultados de datos a una persona no "
        "técnica, en español, de forma breve y clara. Te doy la pregunta y el "
        "resultado (en CSV) de una consulta ya ejecutada sobre datos reales. "
        "Responde la pregunta directamente citando las cifras del resultado. "
        "Mantienes una conversación: puedes referirte a lo hablado antes si aporta. "
        "No inventes datos que no estén en el resultado. Si el resultado está "
        "vacío, dilo. Máximo 4 frases; la tabla y el gráfico se muestran aparte."
    )
    user = f"Pregunta: {pregunta}\n\nResultado de la consulta (CSV):\n{muestra}"
    return llm.generar_texto(system, user, max_tokens=600, historial=historial)


def _pares(historial, campo: str, maximo: int = 6):
    """Convierte el historial del chat en turnos (rol, texto) para dar memoria a la IA.
    'campo' = qué usar como respuesta del asistente: 'sql' o 'texto'."""
    msgs = []
    ultimo_user = None
    for t in historial or []:
        if t.get("rol") == "user":
            ultimo_user = t.get("texto")
        elif t.get("rol") == "assistant" and ultimo_user is not None:
            val = (t.get("resultado") or {}).get(campo) or ""
            if val:
                msgs.append(("user", ultimo_user))
                msgs.append(("model", str(val)))
            ultimo_user = None
    return msgs[-(maximo * 2):]


def responder(pregunta: str, df: pd.DataFrame, historial=None) -> dict:
    """
    Punto de entrada. Devuelve un dict:
      {texto, tabla (DataFrame|None), sql, tipo_grafico, columna_x, error}
    'historial' = st.session_state.historial (para memoria de conversación).
    """
    salida = {"texto": "", "tabla": None, "sql": "", "tipo_grafico": "ninguno",
              "columna_x": None, "error": None}

    if not llm.disponible():
        salida["error"] = (
            "La IA no está conectada. Falta configurar la clave GEMINI_API_KEY "
            "en el archivo .env (local) o en la sección Secrets (Streamlit Cloud)."
        )
        return salida

    hist_sql = _pares(historial, "sql")
    hist_txt = _pares(historial, "texto")

    try:
        plan = generar_sql(pregunta, df, historial=hist_sql)
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

    # Auto-corrección: si la consulta falla, la IA ve el error y lo intenta arreglar.
    intento = 0
    while intento < 2:
        try:
            tabla = ejecutar_sql(df, plan["sql"])
            break
        except Exception as e:
            intento += 1
            if intento >= 2:
                salida["error"] = f"La consulta falló al ejecutarse: {e}"
                return salida
            try:
                plan = generar_sql(pregunta, df, historial=hist_sql,
                                   error_previo=str(e), sql_previo=plan["sql"])
                if not plan.get("sql") or validar_sql(plan["sql"]):
                    salida["error"] = f"La consulta falló al ejecutarse: {e}"
                    return salida
                salida["sql"] = plan["sql"]
                salida["tipo_grafico"] = plan["tipo_grafico"]
                salida["columna_x"] = plan["columna_x"]
            except Exception:
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
        salida["texto"] = redactar_respuesta(pregunta, tabla, historial=hist_txt)
    except Exception as e:
        # Si falla la redacción, al menos mostramos la tabla.
        salida["texto"] = f"(No pude redactar el resumen, pero aquí está el resultado.) [{e}]"

    return salida
