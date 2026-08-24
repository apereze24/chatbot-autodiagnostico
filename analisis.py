"""
Análisis del comportamiento de los autodiagnósticos por hora.

Este módulo es el ÚNICO lugar donde vive la lógica de "¿esta hora es rara?".
Lo usan dos cosas distintas:
  - `termometro.py`, que lo dibuja en el dashboard de la app.
  - `alertas.py`, que lo revisa cada hora y manda correo si hay un pico.

Por eso aquí no se importa Streamlit ni la IA: así la alerta puede correr sola,
en un servidor, sin instalar media aplicación. Y sobre todo: la regla de alerta
es la misma que ve el usuario en pantalla, no una copia que se puede desincronizar.

La idea de fondo: "lo habitual" de una hora es lo que suele pasar en esa MISMA
hora en los días anteriores. Las 8 p.m. se comparan con las 8 p.m., no con el
promedio plano del día (que marcaría alerta todas las noches).
"""

import datetime as dt
import math
import os

import pandas as pd

HORAS = list(range(24))
DIAS_BASE = 14        # con cuántos días anteriores se compara ("lo habitual")
MINIMO_DIAS_BASE = 3  # con menos días que esto, no hay comparación confiable

# Cuándo una hora se marca como pico. Las dos condiciones se piden a la vez:
#   1. Que haya al menos el DOBLE de lo habitual de esa misma hora. El mínimo es
#      proporcional a la hora, no un número fijo: a las 4 a.m., donde lo normal
#      son 2, el doble son 4; a las 8 p.m., donde lo normal son 25, son 50.
#   2. Que además quede fuera del ruido propio de esa hora (ver dispersion).
# Calibrado con 90 días reales: así avisa ~1 vez al día. Si se relaja a "superar
# la mediana" avisaría 13 veces al día, porque por definición la mitad de las
# horas supera la mediana.
FACTOR_PICO = 2.0     # el doble de lo habitual de esa hora
PISO_MINIMO = 5       # piso para las horas más quietas: con 1 o 2 casos no se avisa
K_DISPERSION = 3.5    # margen exigido por encima del ruido normal de la hora

# Cuándo se puede señalar algo como la explicación de un pico. Se exige que pese
# lo suficiente Y que haya crecido frente a su peso habitual: el canal "portal"
# siempre es mayoría, así que ser mayoría por sí solo no explica nada.
MINIMO_CASOS_CAUSA = 10  # con menos casos que esto no se le echa la culpa a una causa
PCT_DOMINANTE = 50       # y tiene que ser mayoría de los casos de esa hora
MINIMO_CASOS_DIM = 5     # para canal y ciudad basta menos volumen...
PCT_CONCENTRADO = 40     # ...y con concentrarse en esta parte de los casos

COLOR_NEUTRO = "#898781"

# Niveles del día: (desvío mínimo, etiqueta, ícono, color).
# Los cortes están puestos con la distribución real de 90 días: más de +50% pasa
# en ~7% de los días y más de +25% en ~21%, así que el rojo sigue significando algo.
NIVELES = [
    (0.50, "Muy por encima de lo habitual", "🔴", "#d03b3b"),
    (0.25, "Por encima de lo habitual", "🟠", "#ec835a"),
    (0.10, "Levemente elevado", "🟡", "#fab219"),
    (-0.10, "Dentro de lo habitual", "🟢", "#0ca30c"),
    (-1.00, "Por debajo de lo habitual", "🔵", "#2a78d6"),
]

DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

# Nombres de canal como se escriben, no como los guarda la base.
NOMBRES = {"portal": "Portal", "whatsapp": "WhatsApp", "sysbrazo": "Sysbrazo"}

# Traducción de códigos técnicos a lenguaje entendible.
TRADUCCIONES = {
    # failure_reason
    "CPE_OFFLINE": "Módem apagado o desconectado",
    "CPE_LOSS_OF_SIGNAL": "Módem sin señal de fibra (LOS)",
    "CPE_NOT_FOUND": "No se encontró el módem del cliente",
    "CPE_GPON_POWER_LOW": "Potencia óptica baja (señal débil)",
    "CPE_STATE_NOT_UP": "Módem no está en estado operativo",
    "CLIENT_HAS_OPEN_INCIDENT": "El cliente ya tenía un incidente abierto",
    "CLIENT_AFFECTED_BY_KRILL_ALARM": "Cliente afectado por una falla masiva",
    "CLIENT_STATUS_INACTIVE": "Cliente inactivo o suspendido",
    "DAILY_CREDIT_LIMIT_REACHED": "Alcanzó el límite diario de crédito",
    "TIMEOUT_EXCEEDED": "El proceso superó el tiempo máximo",
    "PING_BATCH_RETRY_FAILED": "Fallaron los reintentos de ping al módem",
    "KRILL_POST_FAILED": "Falló el registro en el sistema Krill",
    "CREDIT_EXPIRED": "El crédito del cliente estaba vencido",
    "NO_INTERNET_BALANCE": "El cliente no tenía saldo de internet",
    "PING_NOT_COMPLETE": "El ping al módem no se completó",
    "PING_NOT_NEW_OR_INVALID": "El ping no era válido o ya estaba registrado",
    "PING_NO_SUCCESS": "El ping al módem no tuvo respuesta",
    "PING_BATCH_RETRY": "Reintento de ping en curso",
    "CANCELED_FOR_ADVISOR": "El asesor canceló el proceso",
    "AUTO_REPAIR_FAILED": "Falló la reparación automática",
    "RUN_IPPING_DIAGNOSTIC_FAILED": "Falló el diagnóstico de ping al módem",
    "CLIENT_NOT_FOUND": "No se encontró el cliente en el sistema",
    # status del proceso
    "finished": "Completado",
    "failed": "Fallido",
    "canceled": "Escaló a ticket",
    "running": "En curso",
    # final_outcome
    "ALL_OK": "Todo bien, sin problema",
    "ALL_OK_WITH_WARNINGS": "Bien, con advertencias",
    "TICKET_CREATED": "Se generó un ticket",
    "CREDIT_RECHARGED": "Se recargó crédito",
    "BLOCKED": "Proceso bloqueado",
    "CANCELED": "Proceso cancelado",
    "ERROR": "Error técnico",
}


# --- Texto ------------------------------------------------------------------
def fecha_larga(d: dt.date) -> str:
    return f"{DIAS_SEMANA[d.weekday()]} {d.day} de {MESES[d.month - 1]}"


def en_palabras(codigo: str) -> str:
    """Traduce un código técnico a español; si no está en el glosario, lo deja igual."""
    return TRADUCCIONES.get(codigo, codigo)


def bonito(valor: str) -> str:
    """Nombre presentable. Solo toca la inicial, para no romper 'Santa Marta'."""
    return NOMBRES.get(valor.lower(), valor[:1].upper() + valor[1:])


# --- Fechas -----------------------------------------------------------------
def horas_a_local() -> float:
    """Horas a sumar para pasar de UTC a hora local. Ver redash.py."""
    try:
        return float(os.environ.get("HORAS_UTC_A_LOCAL", "-5"))
    except ValueError:
        return -5.0


def fechas(df: pd.DataFrame, col_fecha: str) -> pd.Series:
    """La columna de fecha en hora local, alineada fila por fila con 'df'.

    Las fechas de Redash ya llegan convertidas a hora local; el ajuste de abajo es
    por si la fuente entrega fechas con zona horaria (ej. otro origen de datos),
    porque una hora corrida cambiaría de sitio todos los picos."""
    f = pd.to_datetime(df[col_fecha], errors="coerce")
    if getattr(f.dtype, "tz", None) is not None:
        f = (f.dt.tz_convert("UTC").dt.tz_localize(None)
             + pd.Timedelta(hours=horas_a_local()))
    return f


def fechas_validas(df: pd.DataFrame, col_fecha: str) -> pd.Series:
    """Igual que fechas(), pero descartando las filas sin fecha."""
    return fechas(df, col_fecha).dropna()


# --- Conteos y referencia ---------------------------------------------------
def conteo_por_hora(serie_fechas: pd.Series) -> pd.Series:
    """Cuántos autodiagnósticos por hora del día (0 a 23), con 0 en las horas sin datos."""
    conteo = serie_fechas.dt.hour.value_counts()
    return pd.Series([int(conteo.get(h, 0)) for h in HORAS], index=HORAS)


def matriz_dias_previos(serie_fechas: pd.Series, dia: dt.date) -> pd.DataFrame:
    """Tabla días × horas con los DIAS_BASE días anteriores al día analizado.

    Solo se incluyen los días que realmente tienen datos: contar como "0" un día
    del que no se extrajo información hundiría la referencia y dispararía alertas
    falsas."""
    solo_fecha = serie_fechas.dt.date
    desde = dia - dt.timedelta(days=DIAS_BASE)
    previos = serie_fechas[(solo_fecha >= desde) & (solo_fecha < dia)]
    if previos.empty:
        return pd.DataFrame(columns=HORAS)
    return (previos.groupby([previos.dt.date, previos.dt.hour]).size()
            .unstack(fill_value=0)
            .reindex(columns=HORAS, fill_value=0))


def dispersion(valores: pd.Series) -> float:
    """Qué tanto varía normalmente una hora, de forma resistente a días atípicos.

    Se usa la desviación absoluta mediana (MAD) en vez de la desviación estándar:
    un día con un pico enorme (ej. una falla masiva con 494 autodiagnósticos en
    una hora) inflaría la desviación estándar durante las dos semanas siguientes
    y taparía los picos posteriores. Si la MAD sale 0 (hora muy estable), se usa
    la desviación estándar para no dejar el umbral pegado al valor habitual.

    Además se aplica un piso de ruido: en una hora donde lo habitual es 1 caso,
    ver 2 es puro azar, y ni la MAD ni la desviación estándar lo reflejan porque
    se quedan en 0. Para conteos, la variación esperada por azar es del orden de
    la raíz cuadrada del valor habitual, y eso es lo que se usa como mínimo."""
    mediana = float(valores.median())
    mad = (valores - valores.median()).abs().median() * 1.4826
    ruido = float(mad) if mad > 0 else float(valores.std(ddof=0))
    return max(ruido, math.sqrt(max(mediana, 1.0)))


def es_pico(casos: float, base: float, previos_hora: pd.Series) -> bool:
    """La regla de alerta, en un solo lugar: el doble de lo habitual Y fuera de rango."""
    minimo = max(PISO_MINIMO, FACTOR_PICO * base)
    return casos >= minimo and casos > base + K_DISPERSION * dispersion(previos_hora)


def nivel(actual: float, habitual: float | None) -> dict:
    """Clasifica el día: qué tan por encima (o por debajo) está de lo habitual."""
    if not habitual or pd.isna(habitual):
        return {"etiqueta": "Sin comparación disponible", "icono": "⚪",
                "color": COLOR_NEUTRO, "desvio": None}
    desvio = (actual - habitual) / habitual
    for minimo, etiqueta, icono, color in NIVELES:
        if desvio >= minimo:
            return {"etiqueta": etiqueta, "icono": icono, "color": color, "desvio": desvio}
    # Solo se llega aquí si el día quedó por debajo del último corte de NIVELES.
    minimo, etiqueta, icono, color = NIVELES[-1]
    return {"etiqueta": etiqueta, "icono": icono, "color": color, "desvio": desvio}


def analizar(serie_fechas: pd.Series, dia: dt.date, dia_max: dt.date) -> dict:
    """Todo lo que hay que saber de un día: conteos, referencia y horas en alerta.

    Se separa del dibujo para que el dashboard y el correo de alerta presenten
    exactamente el mismo análisis."""
    del_dia = serie_fechas[serie_fechas.dt.date == dia]
    conteo = conteo_por_hora(del_dia)
    total = int(conteo.sum())

    # Si es el último día con datos, todavía está en curso: solo comparamos las
    # horas que ya transcurrieron (si no, un día a medias parecería una caída).
    if dia == dia_max and total:
        hora_corte = int(del_dia.dt.hour.max())
        en_curso = True
    else:
        hora_corte = 23
        en_curso = False

    previos = matriz_dias_previos(serie_fechas, dia)
    dias_base = len(previos)
    hay_base = dias_base >= MINIMO_DIAS_BASE
    # Usamos la MEDIANA (el día del medio) y no el promedio: así un día con una
    # falla masiva no arrastra la referencia hacia arriba y desactiva la alerta.
    habitual = previos.median() if hay_base else None

    # "Lo habitual" del día: el mismo tramo de horas, en los días anteriores.
    habitual_dia = None
    if hay_base:
        tramo = [h for h in HORAS if h <= hora_corte]
        habitual_dia = float(previos[tramo].sum(axis=1).median())

    picos: set[int] = set()
    if hay_base:
        for h in HORAS:
            if h > hora_corte:
                continue
            if es_pico(conteo[h], float(habitual[h]), previos[h]):
                picos.add(h)

    return {
        "conteo": conteo, "total": total, "hora_corte": hora_corte, "en_curso": en_curso,
        "previos": previos, "dias_base": dias_base, "hay_base": hay_base,
        "habitual": habitual, "habitual_dia": habitual_dia,
        "nivel": nivel(total, habitual_dia),
        "picos": picos, "hora_pico": int(conteo.idxmax()) if total else None,
    }


# --- Desglose de una hora (por qué pasó) ------------------------------------
def reparto(filas_hoy: pd.DataFrame, filas_previas: pd.DataFrame,
            columna: str, tope: int = 3) -> list[dict]:
    """Cómo se reparte una columna en una hora, y cómo se repartía habitualmente.

    Comparar los dos pesos es lo que señala QUÉ cambió: una causa que pasa del 5%
    al 90% de los casos, o una ciudad que pasa del 36% al 94%, es la explicación
    del pico. Los porcentajes son sobre el total de la hora, no sobre los que
    tienen dato, para que "98%" se lea como 98% de lo que pasó esa hora."""
    total = len(filas_hoy)
    total_previo = len(filas_previas)
    pesos_previos = {}
    if total_previo:
        conteo = filas_previas[columna].dropna().astype(str).value_counts()
        pesos_previos = {v: n / total_previo * 100 for v, n in conteo.items()}

    salida = []
    conteo_hoy = filas_hoy[columna].dropna().astype(str).value_counts()
    for i, (valor, casos) in enumerate(conteo_hoy.head(tope).items()):
        # Las colas de 1 caso no explican nada; se conserva siempre la principal.
        if i > 0 and casos < 2:
            continue
        salida.append({
            "valor": valor,
            "casos": int(casos),
            "pct": casos / total * 100 if total else 0.0,
            "pct_habitual": pesos_previos.get(valor),
        })
    return salida


def perfil_de_la_hora(df: pd.DataFrame, serie_fechas: pd.Series, dia: dt.date,
                      hora: int, previos_desde: dt.date, columnas: dict) -> dict:
    """Retrato de una hora marcada: cuántos casos, cuántos fallaron, y cómo se
    repartieron la causa, el canal y la ciudad frente a lo habitual."""
    filas = df.loc[(serie_fechas.dt.date == dia) & (serie_fechas.dt.hour == hora)]
    previas = df.loc[(serie_fechas.dt.date >= previos_desde)
                     & (serie_fechas.dt.date < dia)
                     & (serie_fechas.dt.hour == hora)]
    col_causa = columnas.get("causa")
    fallidos = int(filas[col_causa].notna().sum()) if col_causa else 0
    repartos = {
        clave: reparto(filas, previas, col)
        for clave, col in columnas.items() if col and col in df.columns
    }
    return {"total": len(filas), "fallidos": fallidos, "repartos": repartos}


def crecio(item: dict, pct_minimo: float, casos_minimos: int) -> bool:
    """¿Este valor pesa mucho Y además creció frente a lo habitual de esa hora?"""
    hab = item["pct_habitual"]
    return (hab is not None and item["casos"] >= casos_minimos
            and item["pct"] >= pct_minimo
            and item["pct"] >= max(hab * 1.5, hab + 15))


def lo_que_cambio(perfil: dict) -> list[tuple[str, dict]]:
    """Las dimensiones que se dispararon en una hora, para titular la alerta.

    Devuelve pares (dimensión, item) solo de lo que de verdad creció, en orden:
    la causa primero, porque es el 'qué', y después dónde y por dónde entró."""
    salida = []
    for clave, pct_min, casos_min in (
        ("causa", PCT_DOMINANTE, MINIMO_CASOS_CAUSA),
        ("ciudad", PCT_CONCENTRADO, MINIMO_CASOS_DIM),
        ("canal", PCT_CONCENTRADO, MINIMO_CASOS_DIM),
    ):
        for item in perfil["repartos"].get(clave, []):
            if crecio(item, pct_min, casos_min):
                salida.append((clave, item))
                break  # solo la principal de cada dimensión
    return salida
