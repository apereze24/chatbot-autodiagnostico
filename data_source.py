"""
Carga el archivo de autodiagnósticos y lo deja listo para consultar.

- Lee 'autodiagnosticos.xlsx'.
- Renombra las columnas a nombres simples (sin tildes ni espacios) para que sea
  más fácil consultarlas.
- Agrega algunas columnas derivadas útiles (duración en segundos, hora numérica,
  horas de resolución del ticket).

En la Fase 2 real, este archivo se reemplazaría por una consulta a Postgres,
pero la idea del chatbot (preguntar en lenguaje natural) es la misma.
"""

from datetime import time, datetime

import pandas as pd

ARCHIVO = "autodiagnosticos.xlsx"

# Mapeo: nombre original en el Excel -> nombre simple para consultar.
RENOMBRAR = {
    "Fecha": "fecha",
    "Día de la semana": "dia_semana",
    "Hora": "hora",
    "Canal": "canal",
    "Ciudad": "ciudad",
    "ID Cliente": "id_cliente",
    "Nombre y Apellido": "nombre",
    "Resultado del Proceso": "resultado",
    "Tiempo que tardó": "tiempo_txt",
    "¿Generó ticket?": "genero_ticket",
    "Número de ticket": "numero_ticket",
    "Área Responsable": "area_responsable",
    "Estado de ticket": "estado_ticket",
    "Fecha y hora de apertura de ticket": "apertura_ticket",
    "Fecha y hora de cierre de ticket": "cierre_ticket",
}


def _a_segundos(valor) -> float | None:
    """Convierte un valor de hora/duración (HH:MM:SS) a segundos totales."""
    if pd.isna(valor):
        return None
    if isinstance(valor, time):
        return valor.hour * 3600 + valor.minute * 60 + valor.second
    if isinstance(valor, datetime):
        return valor.hour * 3600 + valor.minute * 60 + valor.second
    return None


def cargar() -> pd.DataFrame:
    df = pd.read_excel(ARCHIVO)
    df = df.rename(columns=RENOMBRAR)

    # Fecha como fecha simple.
    df["fecha"] = pd.to_datetime(df["fecha"]).dt.date

    # Hora numérica (0-23) a partir de la columna 'hora'.
    df["hora_num"] = df["hora"].map(
        lambda v: v.hour if isinstance(v, time) else None
    ).astype("Int64")

    # Duración del proceso en segundos (y en minutos, más legible).
    df["duracion_seg"] = df["tiempo_txt"].map(_a_segundos)
    df["duracion_min"] = (df["duracion_seg"] / 60).round(2)

    # Texto de hora y de duración como string (para mostrar).
    df["hora_txt"] = df["hora"].map(
        lambda v: v.strftime("%H:%M:%S") if isinstance(v, time) else None
    )
    df["tiempo_txt"] = df["tiempo_txt"].map(
        lambda v: v.strftime("%H:%M:%S") if isinstance(v, time) else None
    )

    # Horas que tardó en resolverse el ticket (cierre - apertura).
    df["apertura_ticket"] = pd.to_datetime(df["apertura_ticket"], errors="coerce")
    df["cierre_ticket"] = pd.to_datetime(df["cierre_ticket"], errors="coerce")
    df["resol_horas"] = (
        (df["cierre_ticket"] - df["apertura_ticket"]).dt.total_seconds() / 3600
    ).round(2)

    # Columnas que ya no necesitamos como objeto 'time' (quedan sus versiones texto).
    df = df.drop(columns=["hora"])

    return df


# Descripción de cada columna, para que la IA sepa qué contiene la tabla.
DESCRIPCION_COLUMNAS = {
    "fecha": "Fecha del autodiagnóstico (tipo fecha).",
    "dia_semana": "Día de la semana en español: Lunes, Martes, ... Domingo.",
    "hora_txt": "Hora del autodiagnóstico como texto HH:MM:SS.",
    "hora_num": "Hora del día como número entero 0-23 (útil para agrupar por hora).",
    "canal": "Canal del proceso. Valores: 'Sysbrazo', 'Portal web', 'Botmaker'.",
    "ciudad": "Ciudad. Valores: Barranquilla, Montería, Turbaco, Sincelejo, Santa Marta, Cartagena.",
    "id_cliente": "ID único del cliente (entero).",
    "nombre": "Nombre y apellido del cliente.",
    "resultado": "Resultado del proceso. Valores: 'Completado ok', 'Escalado', 'Fallido'.",
    "tiempo_txt": "Cuánto tardó el proceso, como texto HH:MM:SS.",
    "duracion_seg": "Cuánto tardó el proceso, en segundos (número). Úsalo para promedios/percentiles de duración.",
    "duracion_min": "Cuánto tardó el proceso, en minutos (número).",
    "genero_ticket": "Si el proceso generó ticket. Valores: 'Sí', 'No'.",
    "numero_ticket": "Número del ticket generado (solo si genero_ticket='Sí'; si no, está vacío).",
    "area_responsable": "Área que atiende el ticket. Valores: 'Customer', 'Operaciones', 'NOC'.",
    "estado_ticket": "Estado del ticket. Valores: 'Abierto', 'En Gestión', 'Solucionado'.",
    "apertura_ticket": "Fecha y hora de apertura del ticket (tipo fecha-hora).",
    "cierre_ticket": "Fecha y hora de cierre del ticket (tipo fecha-hora).",
    "resol_horas": "Horas que tardó en resolverse el ticket (cierre - apertura). Vacío si no hay ticket. Úsalo para tiempos de resolución.",
}


if __name__ == "__main__":
    d = cargar()
    print("Filas:", len(d), "| Columnas:", list(d.columns))
    print(d[["fecha", "canal", "ciudad", "resultado", "duracion_min",
             "genero_ticket", "area_responsable", "resol_horas"]].head(8).to_string())
