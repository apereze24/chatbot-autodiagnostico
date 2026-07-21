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


def _elegir_modelo_gemini(client) -> str:
    """
    Decide qué modelo de Gemini usar:
      1. Si GEMINI_MODEL está fijado a mano, se respeta.
      2. Si no, se listan los modelos disponibles en la cuenta y se elige uno
         que sirva para generar texto (preferimos un 'flash': rápido y económico).
    El resultado se guarda en caché para no listar en cada pregunta.
    """
    global _GEMINI_MODELO_CACHE
    fijado = os.environ.get("GEMINI_MODEL", "").strip()
    if fijado:
        return fijado
    if _GEMINI_MODELO_CACHE:
        return _GEMINI_MODELO_CACHE

    candidatos = []
    for m in client.models.list():
        acciones = getattr(m, "supported_actions", None) or []
        if "generateContent" not in acciones:
            continue
        nombre = m.name.replace("models/", "")
        # Descartamos variantes que no sirven para chat de texto.
        if any(x in nombre for x in ("embedding", "aqa", "imagen", "veo", "tts", "image")):
            continue
        candidatos.append(nombre)

    # Preferimos 'flash' (rápido/barato); dentro de eso, el nombre más "nuevo".
    flash = sorted([c for c in candidatos if "flash" in c], reverse=True)
    otros = sorted(candidatos, reverse=True)
    elegido = (flash or otros or ["gemini-flash-latest"])[0]
    _GEMINI_MODELO_CACHE = elegido
    return elegido


def _gemini_json(system: str, user: str, schema: type[BaseModel]) -> BaseModel:
    client = _gemini_client()
    modelo = _elegir_modelo_gemini(client)
    resp = client.models.generate_content(
        model=modelo,
        contents=user,
        config={
            "system_instruction": system,
            "response_mime_type": "application/json",
            "response_schema": schema,
            "max_output_tokens": 4096,
            "temperature": 0,
        },
    )
    if getattr(resp, "parsed", None) is not None:
        return resp.parsed
    # Respaldo: parsear el texto crudo contra el esquema.
    return schema.model_validate_json(resp.text)


def _gemini_texto(system: str, user: str, max_tokens: int) -> str:
    client = _gemini_client()
    modelo = _elegir_modelo_gemini(client)
    resp = client.models.generate_content(
        model=modelo,
        contents=user,
        config={
            "system_instruction": system,
            "max_output_tokens": max_tokens,
            "temperature": 0,
        },
    )
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
