"""
Capa de IA intercambiable: el chatbot puede usar Google Gemini o Claude, según
la clave de API que esté configurada. Así no dependemos de un solo proveedor.

Selección del proveedor (en este orden):
  1. Variable LLM_PROVIDER = "gemini" o "claude" (si se fija a mano).
  2. Si hay GEMINI_API_KEY (o GOOGLE_API_KEY)  -> Gemini.
  3. Si hay ANTHROPIC_API_KEY                  -> Claude.

Expone dos funciones que el resto del chatbot usa:
  - generar_json(system, user, schema) -> objeto Pydantic (salida estructurada)
  - generar_texto(system, user, max_tokens) -> str
"""

import os

from pydantic import BaseModel


def proveedor() -> str | None:
    forzado = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if forzado in ("gemini", "google"):
        return "gemini"
    if forzado in ("claude", "anthropic"):
        return "claude"
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return "gemini"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude"
    return None


def disponible() -> bool:
    return proveedor() is not None


def listar_modelos() -> list[str]:
    """Devuelve los modelos de Gemini que la clave actual puede usar para chat."""
    if proveedor() != "gemini":
        return []
    client = _gemini_client()
    nombres = []
    for m in client.models.list():
        acciones = getattr(m, "supported_actions", None) or []
        if "generateContent" in acciones:
            nombres.append(m.name.replace("models/", ""))
    return sorted(nombres)


def nombre_legible() -> str:
    p = proveedor()
    if p == "gemini":
        modelo = os.environ.get("GEMINI_MODEL") or _GEMINI_MODELO_CACHE or "automático"
        return f"Google Gemini ({modelo})"
    if p == "claude":
        return f"Claude ({os.environ.get('CLAUDE_MODEL', 'claude-opus-4-8')})"
    return "sin conectar"


# --- Gemini ------------------------------------------------------------------
_GEMINI_MODELO_CACHE: str | None = None


def _gemini_client():
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    return genai.Client(api_key=api_key)


# Palabras que marcan modelos que NO queremos usar (experimentales, especiales,
# o de otro tipo distinto a chat de texto).
_GEMINI_EXCLUIR = (
    "omni", "exp", "preview", "image", "vision", "tts", "audio", "live",
    "learnlm", "embedding", "aqa", "veo", "imagen", "gemma", "nano", "thinking",
    "native-audio", "dialog",
)


def _puntaje_modelo(nombre: str) -> int:
    """Puntúa un modelo: más alto = más preferido (estable, flash, versión reciente)."""
    n = nombre.lower()
    p = 0
    if "flash" in n:
        p += 10          # flash: rápido y con mejor cuota gratuita
    if "pro" in n:
        p -= 20          # pro: suele tener cuota 0 en la capa gratuita
    if "latest" in n:
        p += 5
    if "2.5" in n:
        p += 4
    if "2.0" in n:
        p += 4
    if "lite" in n:
        p += 2           # 'flash-lite': cuota gratuita generosa
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

    # Ordena por puntaje (mejor primero); desempata por nombre.
    candidatos.sort(key=lambda n: (_puntaje_modelo(n), n), reverse=True)
    # Alias estables como respaldo, por si la lista viene vacía.
    for respaldo in ("gemini-flash-latest", "gemini-2.0-flash"):
        if respaldo not in candidatos:
            candidatos.append(respaldo)
    return candidatos


def _modelo_no_disponible(msg: str) -> bool:
    """El error indica que ESE modelo no se puede usar (probar con otro)."""
    m = msg.lower()
    return ("limit: 0" in m or "not_found" in m or "not available" in m
            or "404" in m or "not supported" in m or "permission" in m)


def _rate_limit_real(msg: str) -> bool:
    """El error es un límite de uso temporal (no cambiar de modelo; esperar)."""
    m = msg.lower()
    return ("resource_exhausted" in m or "429" in m) and "limit: 0" not in m


def _gemini_call(system: str, user: str, extra_config: dict):
    """Intenta generar contenido probando modelos en orden hasta que uno funcione."""
    global _GEMINI_MODELO_CACHE
    client = _gemini_client()

    # Si ya encontramos un modelo que sirve, úsalo primero.
    orden = _candidatos_gemini(client)
    if _GEMINI_MODELO_CACHE and _GEMINI_MODELO_CACHE in orden:
        orden.remove(_GEMINI_MODELO_CACHE)
        orden.insert(0, _GEMINI_MODELO_CACHE)

    config = {"system_instruction": system, "temperature": 0, **extra_config}
    ultimo_error = None
    for modelo in orden:
        try:
            resp = client.models.generate_content(model=modelo, contents=user, config=config)
            _GEMINI_MODELO_CACHE = modelo  # recordamos el que funcionó
            return resp
        except Exception as e:
            msg = str(e)
            if _rate_limit_real(msg):
                raise RuntimeError(
                    "Se alcanzó el límite de uso gratuito por el momento. "
                    "Espera unos segundos y vuelve a preguntar."
                ) from e
            if _modelo_no_disponible(msg):
                ultimo_error = e
                continue  # probar el siguiente modelo
            raise  # error distinto: no seguir probando
    raise RuntimeError(
        "No encontré un modelo de Gemini disponible en tu cuenta para responder. "
        f"Último detalle: {ultimo_error}"
    )


def _gemini_json(system: str, user: str, schema: type[BaseModel]) -> BaseModel:
    resp = _gemini_call(system, user, {
        "response_mime_type": "application/json",
        "response_schema": schema,
        "max_output_tokens": 4096,
    })
    if getattr(resp, "parsed", None) is not None:
        return resp.parsed
    return schema.model_validate_json(resp.text)


def _gemini_texto(system: str, user: str, max_tokens: int) -> str:
    resp = _gemini_call(system, user, {"max_output_tokens": max_tokens})
    return (resp.text or "").strip()


# --- Claude ------------------------------------------------------------------
def _claude_json(system: str, user: str, schema: type[BaseModel]) -> BaseModel:
    import anthropic

    client = anthropic.Anthropic()
    modelo = os.environ.get("CLAUDE_MODEL", "claude-opus-4-8")
    resp = client.messages.parse(
        model=modelo,
        max_tokens=1200,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_format=schema,
    )
    return resp.parsed_output


def _claude_texto(system: str, user: str, max_tokens: int) -> str:
    import anthropic

    client = anthropic.Anthropic()
    modelo = os.environ.get("CLAUDE_MODEL", "claude-opus-4-8")
    resp = client.messages.create(
        model=modelo,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()


# --- API pública -------------------------------------------------------------
def generar_json(system: str, user: str, schema: type[BaseModel]) -> BaseModel:
    p = proveedor()
    if p == "gemini":
        return _gemini_json(system, user, schema)
    if p == "claude":
        return _claude_json(system, user, schema)
    raise RuntimeError("No hay proveedor de IA configurado (falta GEMINI_API_KEY o ANTHROPIC_API_KEY).")


def generar_texto(system: str, user: str, max_tokens: int = 600) -> str:
    p = proveedor()
    if p == "gemini":
        return _gemini_texto(system, user, max_tokens)
    if p == "claude":
        return _claude_texto(system, user, max_tokens)
    raise RuntimeError("No hay proveedor de IA configurado (falta GEMINI_API_KEY o ANTHROPIC_API_KEY).")
