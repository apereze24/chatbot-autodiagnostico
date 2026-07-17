"""
Generador de datos de EJEMPLO para el prototipo del chatbot de Autodiagnóstico.

Estos datos son FALSOS pero realistas. Imitan lo que obtendríamos al unir las
tablas reales (sysbrazo.auto_diagnostic_runs + analytics.client/_address + odoo).

En la Fase 2 este archivo se reemplaza por consultas reales a las bases de datos,
pero las columnas se mantienen iguales, así que el resto del prototipo no cambia.
"""

import random
from datetime import datetime, timedelta

import pandas as pd

# Semilla fija -> los datos son siempre los mismos (útil para demos reproducibles).
random.seed(42)

# --- Catálogos ---------------------------------------------------------------

CIUDADES = [
    "Bogotá", "Medellín", "Cali", "Barranquilla", "Cartagena",
    "Bucaramanga", "Pereira", "Cúcuta",
]
# Peso relativo de cada ciudad (más clientes en las grandes).
PESO_CIUDAD = [30, 20, 15, 10, 8, 7, 5, 5]

CANALES = ["Portal", "Bot", "Sysbrazo"]
PESO_CANAL = [45, 40, 15]  # Bot y Portal concentran la mayoría; Sysbrazo es asistido.

# status del run (tabla sysbrazo.auto_diagnostic_runs)
STATUS = ["finished", "failed", "canceled"]
PESO_STATUS = [70, 18, 12]

# Tipo de resolución del ticket en Odoo (solo si se generó ticket).
RESOLUCION = ["Resuelto", "NOC", "OPS"]
PESO_RESOLUCION = [65, 20, 15]

# Tipo de cierre cuando quedó "Resuelto".
TIPO_CIERRE = [
    "Reinicio de módem",
    "Reconfiguración WiFi",
    "Cambio de módem",
    "Corte de drop reparado",
    "Sin falla / cliente educado",
]

# Fecha de referencia del prototipo (hoy).
HOY = datetime(2026, 7, 10, 12, 0, 0)
DIAS_HISTORIA = 90  # generamos ~3 meses de datos


def _fecha_aleatoria() -> datetime:
    """Una fecha/hora aleatoria dentro de la ventana de historia, con sesgo horario."""
    dia = random.randint(0, DIAS_HISTORIA)
    # Horas pico: mañana (8-11) y tarde-noche (18-22).
    hora = random.choices(
        population=list(range(24)),
        weights=[1, 1, 1, 1, 1, 2, 4, 7, 9, 9, 8, 7,
                 6, 6, 6, 6, 7, 8, 9, 9, 8, 6, 3, 2],
    )[0]
    minuto = random.randint(0, 59)
    return HOY - timedelta(days=dia, hours=HOY.hour - hora, minutes=HOY.minute - minuto)


def generar_runs(n: int = 4000) -> pd.DataFrame:
    """Genera un DataFrame de autodiagnósticos (una fila = un intento)."""
    filas = []
    # Universo de clientes: algunos repiten el proceso varias veces.
    clientes = list(range(10001, 10001 + 1200))

    for run_id in range(1, n + 1):
        client_id = random.choice(clientes)
        ciudad = random.choices(CIUDADES, weights=PESO_CIUDAD)[0]
        canal = random.choices(CANALES, weights=PESO_CANAL)[0]
        status = random.choices(STATUS, weights=PESO_STATUS)[0]

        inicio = _fecha_aleatoria()

        # Duración del proceso según cómo terminó.
        if status == "finished":
            dur_min = round(random.uniform(2, 25), 1)
            resultado = random.choices(["ok", "error"], weights=[80, 20])[0]
        elif status == "failed":
            dur_min = round(random.uniform(1, 15), 1)
            resultado = "error"
        else:  # canceled -> generó ticket
            dur_min = round(random.uniform(0.5, 8), 1)
            resultado = "error"

        fin = inicio + timedelta(minutes=dur_min)

        # Ticket: se genera cuando el run fue 'canceled' o el resultado fue 'error'.
        genera_ticket = status == "canceled" or resultado == "error"
        if genera_ticket:
            ticket_ref = str(250000 + run_id)
            resolucion = random.choices(RESOLUCION, weights=PESO_RESOLUCION)[0]
            if resolucion == "Resuelto":
                tipo_cierre = random.choice(TIPO_CIERRE)
                # tiempo de resolución del ticket (horas) después del autodiagnóstico
                resol_horas = round(random.uniform(0.5, 72), 1)
            else:
                tipo_cierre = None
                resol_horas = round(random.uniform(2, 96), 1)
        else:
            ticket_ref = None
            resolucion = None
            tipo_cierre = None
            resol_horas = None

        filas.append({
            "run_id": run_id,
            "client_id": client_id,
            "canal": canal,
            "ciudad": ciudad,
            "started_at": inicio,
            "finished_at": fin,
            "status": status,
            "resultado": resultado,          # ok / error (del autodiagnóstico)
            "duracion_min": dur_min,         # duración del proceso
            "ticket_ref": ticket_ref,
            "resolucion": resolucion,        # Resuelto / NOC / OPS / None
            "tipo_cierre": tipo_cierre,
            "resol_horas": resol_horas,      # horas hasta resolver el ticket
        })

    df = pd.DataFrame(filas)
    df["fecha"] = df["started_at"].dt.date
    df["hora"] = df["started_at"].dt.hour
    # Día de la semana en español.
    dias_es = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    df["dia_semana"] = df["started_at"].dt.weekday.map(lambda i: dias_es[i])
    return df


def generar_clientes(df_runs: pd.DataFrame) -> pd.DataFrame:
    """Dimensión de clientes (imita analytics.client + analytics.client_address)."""
    filas = []
    for client_id in sorted(df_runs["client_id"].unique()):
        # La ciudad del cliente = la más frecuente en sus runs.
        ciudad = df_runs[df_runs["client_id"] == client_id]["ciudad"].mode()[0]
        filas.append({
            "client_id": client_id,
            "tipo_cliente": random.choices(["Persona", "Empresa"], weights=[85, 15])[0],
            "estrato": random.randint(1, 6),
            "ciudad": ciudad,
        })
    return pd.DataFrame(filas)


if __name__ == "__main__":
    runs = generar_runs()
    print(runs.head(10).to_string())
    print(f"\nTotal de autodiagnósticos: {len(runs)}")
    print(f"Clientes únicos: {runs['client_id'].nunique()}")
    print(f"Rango de fechas: {runs['fecha'].min()} a {runs['fecha'].max()}")
