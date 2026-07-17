"""
El "cerebro" del chatbot: entiende la pregunta en lenguaje natural y decide
cuál de las 10 mediciones responderla.

- Si hay una clave de API de Claude configurada (ANTHROPIC_API_KEY), usa la IA
  para entender preguntas libres ("¿cuántos autodiagnósticos hubo en Cali por el bot?").
- Si NO hay clave, usa un detector simple por palabras clave, para que el
  prototipo funcione igual (con frases más directas).

En ambos casos, el NÚMERO siempre lo calcula metrics.py sobre los datos: la IA
solo elige la pregunta y los filtros, nunca inventa cifras.
"""

import os

from metrics import CATALOGO

# Claves de métrica válidas (las 10 mediciones).
CLAVES = list(CATALOGO.keys())

# Descripción de cada métrica para que la IA (o el usuario) sepa cuál elegir.
DESCRIPCIONES = {
    "total_clientes": "cuántos clientes o autodiagnósticos en total (volumen general)",
    "por_canal": "cuántos por canal (Portal, Bot, Sysbrazo)",
    "por_ciudad": "cuántos por ciudad",
    "por_hora": "distribución por hora del día",
    "por_dia_semana": "distribución por día de la semana",
    "tiempo_por_funnel": "tiempos de resolución por etapa/funnel, duración del proceso",
    "tipo_resolucion": "en qué terminaron los tickets: Resuelto, NOC, OPS y tipo de cierre",
    "clientes_repetidores": "clientes que repiten el autodiagnóstico varias veces",
    "percentiles_resolucion": "percentiles P10..P90 del tiempo de resolución",
    "reopen_fallidos": "reopen: cuántos con error repiten a las 24/48/72 horas",
    "por_hora_y_ciudad": "autodiagnósticos cruzados por hora y ciudad",
}

# Palabras clave para el respaldo sin IA.
PALABRAS = {
    "por_canal": ["canal", "portal", "bot", "sysbrazo"],
    "por_ciudad": ["ciudad", "ciudades", "bogotá", "medellín", "cali", "barranquilla"],
    "por_hora_y_ciudad": ["hora y ciudad", "hora por ciudad", "ciudad y hora"],
    "por_hora": ["hora", "horario", "horas"],
    "por_dia_semana": ["día", "dia", "semana", "días", "lunes", "fin de semana"],
    "tiempo_por_funnel": ["funnel", "tiempo", "duración", "duracion", "demora", "tarda"],
    "tipo_resolucion": ["resuelto", "noc", "ops", "ticket", "cierre", "resolución", "resolucion"],
    "clientes_repetidores": ["repite", "repiten", "repetidor", "varias veces", "insiste"],
    "percentiles_resolucion": ["percentil", "percentiles", "p10", "p50", "p90", "porcentaje resuelto"],
    "reopen_fallidos": ["reopen", "reabr", "vuelve", "vuelven", "24", "48", "72", "error"],
    "total_clientes": ["total", "cuántos clientes", "cuantos clientes", "volumen", "general"],
}

CIUDADES = ["Bogotá", "Medellín", "Cali", "Barranquilla", "Cartagena",
            "Bucaramanga", "Pereira", "Cúcuta"]
CANALES = ["Portal", "Bot", "Sysbrazo"]


def _detectar_filtros_texto(pregunta: str) -> dict:
    """Detecta ciudad/canal mencionados directamente en el texto."""
    p = pregunta.lower()
    filtros = {}
    for c in CIUDADES:
        if c.lower() in p:
            filtros["ciudad"] = c
            break
    for c in CANALES:
        if c.lower() in p:
            filtros["canal"] = c
            break
    return filtros


def _rutear_por_palabras(pregunta: str) -> dict:
    """Respaldo sin IA: elige la métrica por palabras clave."""
    p = pregunta.lower()
    for clave, palabras in PALABRAS.items():
        if any(w in p for w in palabras):
            return {"metrica": clave, "filtros": _detectar_filtros_texto(pregunta)}
    return {"metrica": None, "filtros": {}}


def _rutear_con_claude(pregunta: str) -> dict:
    """Usa Claude para elegir la métrica y extraer filtros. Devuelve dict."""
    import anthropic
    from pydantic import BaseModel

    class Ruteo(BaseModel):
        metrica: str        # una de las claves válidas, o "desconocido"
        ciudad: str | None  # ciudad detectada o None
        canal: str | None   # canal detectado o None

    catalogo_txt = "\n".join(f"- {k}: {v}" for k, v in DESCRIPCIONES.items())
    modelo = os.environ.get("CLAUDE_MODEL", "claude-opus-4-8")

    client = anthropic.Anthropic()
    resp = client.messages.parse(
        model=modelo,
        max_tokens=300,
        system=(
            "Eres un enrutador para un chatbot de métricas de un proceso llamado "
            "'autodiagnóstico'. Dada la pregunta del usuario, elige la métrica más "
            "adecuada de esta lista (usa exactamente la clave):\n"
            f"{catalogo_txt}\n\n"
            "Si ninguna aplica, usa 'desconocido'. Detecta si menciona una ciudad "
            f"({', '.join(CIUDADES)}) o un canal ({', '.join(CANALES)}); si no, deja null."
        ),
        messages=[{"role": "user", "content": pregunta}],
        output_format=Ruteo,
    )
    r = resp.parsed_output
    filtros = {}
    if r and r.ciudad in CIUDADES:
        filtros["ciudad"] = r.ciudad
    if r and r.canal in CANALES:
        filtros["canal"] = r.canal
    metrica = r.metrica if r and r.metrica in CLAVES else None
    return {"metrica": metrica, "filtros": filtros}


def entender(pregunta: str) -> dict:
    """
    Punto de entrada. Devuelve:
      {"metrica": <clave o None>, "filtros": {"ciudad":..., "canal":...}, "motor": "IA"|"palabras"}
    """
    tiene_clave = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if tiene_clave:
        try:
            res = _rutear_con_claude(pregunta)
            res["motor"] = "IA"
            return res
        except Exception as e:  # si la IA falla, no rompemos el prototipo
            res = _rutear_por_palabras(pregunta)
            res["motor"] = f"palabras (la IA falló: {e})"
            return res
    res = _rutear_por_palabras(pregunta)
    res["motor"] = "palabras"
    return res
