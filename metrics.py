"""
Las 10 mediciones del autodiagnóstico, cada una como una función.

Cada función recibe el DataFrame ya FILTRADO (por ciudad/fecha/canal) y devuelve
un resultado listo para mostrar: un número, una tabla (DataFrame) o una serie.

Estas consultas son "pre-validadas": son la lógica confiable que el chatbot usa
para responder las preguntas conocidas, sin que la IA invente números.
"""

import pandas as pd

# Orden de días para gráficos.
ORDEN_DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def total_clientes(df: pd.DataFrame) -> dict:
    """1. Número de clientes que realizan el proceso (y total de autodiagnósticos)."""
    return {
        "clientes_unicos": int(df["client_id"].nunique()),
        "total_autodiagnosticos": int(len(df)),
    }


def por_canal(df: pd.DataFrame) -> pd.DataFrame:
    """2. Número de clientes / autodiagnósticos por canal."""
    g = df.groupby("canal").agg(
        autodiagnosticos=("run_id", "count"),
        clientes=("client_id", "nunique"),
    )
    return g.sort_values("autodiagnosticos", ascending=False)


def por_ciudad(df: pd.DataFrame) -> pd.DataFrame:
    """3. Número de clientes / autodiagnósticos por ciudad."""
    g = df.groupby("ciudad").agg(
        autodiagnosticos=("run_id", "count"),
        clientes=("client_id", "nunique"),
    )
    return g.sort_values("autodiagnosticos", ascending=False)


def por_hora(df: pd.DataFrame) -> pd.Series:
    """4a. Distribución por hora del día."""
    return df.groupby("hora").size().reindex(range(24), fill_value=0)


def por_dia_semana(df: pd.DataFrame) -> pd.Series:
    """4b. Distribución por día de la semana."""
    return df.groupby("dia_semana").size().reindex(ORDEN_DIAS, fill_value=0)


def tiempo_por_funnel(df: pd.DataFrame) -> pd.DataFrame:
    """5. Tiempos por etapa del funnel (según cómo terminó el run)."""
    g = df.groupby("status").agg(
        casos=("run_id", "count"),
        duracion_promedio_min=("duracion_min", "mean"),
        duracion_mediana_min=("duracion_min", "median"),
    ).round(1)
    return g


def tipo_resolucion(df: pd.DataFrame) -> dict:
    """6. En qué terminaron los que generaron ticket: Resuelto / NOC / OPS + cierre."""
    con_ticket = df[df["ticket_ref"].notna()]
    resumen = con_ticket.groupby("resolucion").size().rename("tickets")
    cierres = (
        con_ticket[con_ticket["resolucion"] == "Resuelto"]
        .groupby("tipo_cierre").size().rename("tickets")
        .sort_values(ascending=False)
    )
    return {"por_resolucion": resumen, "tipos_de_cierre": cierres}


def clientes_repetidores(df: pd.DataFrame, umbral: int = 3) -> pd.DataFrame:
    """7. Clientes que hicieron >= 'umbral' autodiagnósticos y terminaron resueltos."""
    conteo = df.groupby("client_id").agg(
        autodiagnosticos=("run_id", "count"),
        alguno_resuelto=("resolucion", lambda s: (s == "Resuelto").any()),
    )
    repetidores = conteo[
        (conteo["autodiagnosticos"] >= umbral) & (conteo["alguno_resuelto"])
    ]
    return repetidores.sort_values("autodiagnosticos", ascending=False)


def percentiles_resolucion(df: pd.DataFrame) -> pd.DataFrame:
    """8. Percentiles P10..P90 del tiempo de resolución del ticket (horas)."""
    horas = df["resol_horas"].dropna()
    if horas.empty:
        return pd.DataFrame({"percentil": [], "horas": []})
    ps = [10, 20, 30, 40, 50, 60, 70, 80, 90]
    valores = [round(horas.quantile(p / 100), 1) for p in ps]
    return pd.DataFrame({"percentil": [f"P{p}" for p in ps], "horas": valores})


def reopen_fallidos(df: pd.DataFrame) -> pd.DataFrame:
    """
    9. Reopen: clientes con resultado 'error' que REPITEN el autodiagnóstico
    dentro de 24 / 48 / 72 horas.
    """
    df_ord = df.sort_values("started_at")
    ventanas = {"24h": 24, "48h": 48, "72h": 72}
    resultado = {v: 0 for v in ventanas}

    # Para cada run con error, ¿hay otro run del mismo cliente dentro de la ventana?
    errores = df_ord[df_ord["resultado"] == "error"]
    for _, fila in errores.iterrows():
        posteriores = df_ord[
            (df_ord["client_id"] == fila["client_id"])
            & (df_ord["started_at"] > fila["started_at"])
        ]
        if posteriores.empty:
            continue
        delta_h = (posteriores["started_at"].min() - fila["started_at"]).total_seconds() / 3600
        for nombre, horas in ventanas.items():
            if delta_h <= horas:
                resultado[nombre] += 1

    total_err = len(errores)
    filas = []
    for nombre in ventanas:
        n = resultado[nombre]
        pct = round(100 * n / total_err, 1) if total_err else 0.0
        filas.append({"ventana": nombre, "reopens": n, "pct_sobre_errores": pct})
    return pd.DataFrame(filas)


def por_hora_y_ciudad(df: pd.DataFrame) -> pd.DataFrame:
    """10. Autodiagnósticos por hora y por ciudad (tabla cruzada)."""
    tabla = pd.crosstab(df["hora"], df["ciudad"])
    return tabla


# Catálogo: clave -> (título legible, función). Lo usa el chatbot para enrutar.
CATALOGO = {
    "total_clientes": ("Total de clientes y autodiagnósticos", total_clientes),
    "por_canal": ("Autodiagnósticos por canal", por_canal),
    "por_ciudad": ("Autodiagnósticos por ciudad", por_ciudad),
    "por_hora": ("Distribución por hora del día", por_hora),
    "por_dia_semana": ("Distribución por día de la semana", por_dia_semana),
    "tiempo_por_funnel": ("Tiempo de resolución por funnel", tiempo_por_funnel),
    "tipo_resolucion": ("Tipo de ticket / resolución", tipo_resolucion),
    "clientes_repetidores": ("Clientes que repiten el proceso", clientes_repetidores),
    "percentiles_resolucion": ("Percentiles de tiempo de resolución", percentiles_resolucion),
    "reopen_fallidos": ("Reopen de autodiagnósticos fallidos", reopen_fallidos),
    "por_hora_y_ciudad": ("Autodiagnósticos por hora y ciudad", por_hora_y_ciudad),
}
