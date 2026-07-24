"""
Conector con Redash: trae el resultado de una consulta ya construida en Redash,
vía su API, y lo entrega como DataFrame para el chatbot.

Configuración (en .env local o en Secrets de Streamlit Cloud):
  REDASH_URL       = https://tu-redash.empresa.com   (sin / al final)
  REDASH_QUERY_ID  = 1234                              (el número de la consulta)
  REDASH_API_KEY   = tu_api_key_de_usuario            (NUNCA se comparte por chat)

Dos modos:
  - obtener_datos()            -> resultado ya cacheado en Redash (rápido).
  - obtener_datos(refrescar=True) -> corre la consulta de nuevo y espera (botón "Actualizar").
"""

import os
import time

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()


def _cfg():
    url = os.environ.get("REDASH_URL", "").rstrip("/")
    qid = os.environ.get("REDASH_QUERY_ID", "").strip()
    key = os.environ.get("REDASH_API_KEY", "").strip()
    return url, qid, key


def configurado() -> bool:
    url, qid, key = _cfg()
    return bool(url and qid and key)


def _headers(key: str) -> dict:
    return {"Authorization": f"Key {key}"}


def _normalizar(df: pd.DataFrame) -> pd.DataFrame:
    """Agrega columnas numéricas útiles (guardadas por si el chatbot pregunta cálculos)."""
    if df.empty:
        return df
    if "duration_seconds" in df.columns:
        df["duracion_min"] = (pd.to_numeric(df["duration_seconds"], errors="coerce") / 60).round(2)
    if "ticket_create_date" in df.columns and "ticket_close_date" in df.columns:
        creado = pd.to_datetime(df["ticket_create_date"], errors="coerce")
        cerrado = pd.to_datetime(df["ticket_close_date"], errors="coerce")
        df["ticket_resolucion_horas"] = ((cerrado - creado).dt.total_seconds() / 3600).round(2)
    return df


def _a_dataframe(payload: dict) -> pd.DataFrame:
    data = payload["query_result"]["data"]
    columnas = [c["name"] for c in data["columns"]]
    df = pd.DataFrame(data["rows"])
    if not df.empty:
        orden = [c for c in columnas if c in df.columns]
        df = df[orden]
    return _normalizar(df)


def obtener_datos(refrescar: bool = False, timeout_seg: int = 120) -> pd.DataFrame:
    url, qid, key = _cfg()
    if not (url and qid and key):
        raise RuntimeError(
            "Falta configurar la conexión a Redash: REDASH_URL, REDASH_QUERY_ID y "
            "REDASH_API_KEY (en .env local o en Secrets de Streamlit)."
        )

    if not refrescar:
        # Resultado ya cacheado en Redash (rápido).
        r = requests.get(
            f"{url}/api/queries/{qid}/results.json",
            headers=_headers(key), timeout=60,
        )
        r.raise_for_status()
        return _a_dataframe(r.json())

    # Forzar una corrida nueva y esperar a que termine.
    r = requests.post(
        f"{url}/api/queries/{qid}/refresh",
        headers=_headers(key), timeout=60,
    )
    r.raise_for_status()
    cuerpo = r.json()
    job = cuerpo.get("job", {})
    job_id = job.get("id")
    if not job_id:
        # Algunas versiones devuelven el resultado directo.
        return _a_dataframe(cuerpo)

    esperado = 0
    while esperado < timeout_seg:
        time.sleep(2)
        esperado += 2
        jr = requests.get(f"{url}/api/jobs/{job_id}", headers=_headers(key), timeout=60)
        jr.raise_for_status()
        j = jr.json().get("job", {})
        estado = j.get("status")
        if estado == 3:  # éxito
            result_id = j.get("query_result_id")
            rr = requests.get(
                f"{url}/api/query_results/{result_id}.json",
                headers=_headers(key), timeout=60,
            )
            rr.raise_for_status()
            return _a_dataframe(rr.json())
        if estado == 4:  # error
            raise RuntimeError(f"La consulta falló en Redash: {j.get('error')}")

    raise RuntimeError("La actualización tardó demasiado. Intenta de nuevo en un momento.")
