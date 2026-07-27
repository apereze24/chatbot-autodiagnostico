"""
Capa de IA (Google Gemini) con memoria de conversación.

- Usa Google Gemini. El modelo se fija con GEMINI_MODEL (recomendado, ej.
  "gemini-3.1-pro"); si no se fija, elige automáticamente el mejor disponible
  (prefiere Pro y la versión más reciente).
- Soporta historial: se le pasan los turnos previos para que "recuerde" la
  conversación y entienda preguntas de seguimiento ("¿y por ciudad?").

Funciones que usa el resto del chatbot:
  - generar_json(system, user, schema, historial) -> objeto Pydantic
  - generar_texto(system, user, max_tokens, historial) -> str
  historial: lista de tuplas (rol, texto) con rol "user" o "model".
"""

import os

from pydantic import BaseModel

_GEMINI_MODELO_CACHE: str | None = None


def _api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def disponible() -> bool:
    return bool(_api_key())


def nombre_legible() -> str:
    if not disponible():
        return "sin conectar"
    modelo = os.environ.get("GEMINI_MODEL") or _GEMINI_MODELO_CACHE or "automático"
    return f"Google Gemini ({modelo})"


def _gemini_client():
    from google import genai
    return genai.Client(api_key=_api_key())


def listar_modelos() -> list[str]:
    """Modelos que la clave actual puede usar para chat (para elegir el Pro correcto)."""
    if not disponible():
        return []
    nombres = []
    for m in _gemini_client().models.list():
        acciones = getattr(m, "supported_actions", None) or []
        if "generateContent" in acciones:
            nombres.append(m.name.replace("models/", ""))
    return sorted(nombres)


# Modelos que NO sirven para chat de texto (se descartan en la auto-detección).
_GEMINI_EXCLUIR = (
    "image", "vision", "tts", "audio", "live", "learnlm", "embedding",
    "aqa", "veo", "imagen", "gemma", "nano", "native-audio", "dialog",
)


def _puntaje_modelo(nombre: str) -> int:
    """Puntúa un modelo: más alto = más preferido (Pro y versión más reciente)."""
    n = nombre.lower()
    p = 0
    if "pro" in n:
        p += 20
    elif "flash" in n:
        p += 8
    if "latest" in n:
        p += 5
    if "3.1" in n:
        p += 14
    elif "gemini-3" in n or "-3-" in n or n.endswith("-3"):
        p += 12
    elif "2.5" in n:
        p += 6
    elif "2.0" in n:
        p += 4
    return p


def _candidatos_gemini(client) -> list[str]:
    """Lista ordenada de modelos a intentar. Si GEMINI_MODEL está fijado, solo ese."""
    fijado = os.environ.get("GEMINI_MODEL", "").strip()
    if fijado:
        return [fijado]
    candidatos = []
    for m in client.models.list():
        acciones = getattr(m, "supported_actions", None) or []
        if "generateContent" not in acciones:
            continue
        nombre = m.name.replace("models/", "")
        if any(x in nombre.lower() for x in _GEMINI_EXCLUIR):
            continue
        candidatos.append(nombre)
    candidatos.sort(key=lambda n: (_puntaje_modelo(n), n), reverse=True)
    for respaldo in ("gemini-flash-latest", "gemini-2.0-flash"):
        if respaldo not in candidatos:
            candidatos.append(respaldo)
    return candidatos


def _modelo_no_disponible(msg: str) -> bool:
    m = msg.lower()
    return ("limit: 0" in m or "not_found" in m or "not available" in m
            or "404" in m or "not supported" in m or "permission" in m)


def _rate_limit_real(msg: str) -> bool:
    m = msg.lower()
    return ("resource_exhausted" in m or "429" in m) and "limit: 0" not in m


def _contenidos(user: str, historial) -> list:
    """Arma la conversación (turnos previos + pregunta actual) para Gemini."""
    contents = []
    for rol, texto in (historial or []):
        r = "model" if rol in ("model", "assistant") else "user"
        contents.append({"role": r, "parts": [{"text": str(texto)}]})
    contents.append({"role": "user", "parts": [{"text": user}]})
    return contents


def _gemini_call(system: str, user: str, extra_config: dict, historial=None):
    """Genera contenido probando modelos en orden hasta que uno funcione."""
    global _GEMINI_MODELO_CACHE
    client = _gemini_client()

    orden = _candidatos_gemini(client)
    if _GEMINI_MODELO_CACHE and _GEMINI_MODELO_CACHE in orden:
        orden.remove(_GEMINI_MODELO_CACHE)
        orden.insert(0, _GEMINI_MODELO_CACHE)

    config = {"system_instruction": system, "temperature": 0, **extra_config}
    contents = _contenidos(user, historial)
    ultimo_error = None
    for modelo in orden:
        try:
            resp = client.models.generate_content(model=modelo, contents=contents, config=config)
            _GEMINI_MODELO_CACHE = modelo
            return resp
        except Exception as e:
            msg = str(e)
            if _rate_limit_real(msg):
                raise RuntimeError(
                    "Se alcanzó el límite de uso por el momento. "
                    "Espera unos segundos y vuelve a preguntar."
                ) from e
            if _modelo_no_disponible(msg):
                ultimo_error = e
                continue
            raise
    raise RuntimeError(
        "No encontré un modelo de Gemini disponible en tu cuenta. "
        f"Fija GEMINI_MODEL con uno válido. Último detalle: {ultimo_error}"
    )


# --- API pública -------------------------------------------------------------
def generar_json(system: str, user: str, schema: type[BaseModel], historial=None) -> BaseModel:
    if not disponible():
        raise RuntimeError("No hay clave de Gemini configurada (GEMINI_API_KEY).")
    resp = _gemini_call(system, user, {
        "response_mime_type": "application/json",
        "response_schema": schema,
        "max_output_tokens": 4096,
    }, historial)
    if getattr(resp, "parsed", None) is not None:
        return resp.parsed
    return schema.model_validate_json(resp.text)


def generar_texto(system: str, user: str, max_tokens: int = 600, historial=None) -> str:
    if not disponible():
        raise RuntimeError("No hay clave de Gemini configurada (GEMINI_API_KEY).")
    resp = _gemini_call(system, user, {"max_output_tokens": max_tokens}, historial)
    return (resp.text or "").strip()
