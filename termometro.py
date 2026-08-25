"""
Termómetro de actividad — el dashboard de la segunda pestaña de la app.

Para el día que se elija, muestra cuántos autodiagnósticos se ejecutaron en cada
hora y avisa cuando el volumen se sale de lo normal. Este módulo solo se ocupa de
PRESENTAR: los cálculos y la regla de alerta viven en `analisis.py`, compartidos
con el correo de alerta (`alertas.py`), para que la pantalla y el correo nunca
digan cosas distintas.

Sirve para dos cosas:
  1. Ver de un vistazo en qué horas se concentran los autodiagnósticos (los picos).
  2. Ver una alerta cuando hay más actividad de la habitual, que suele significar
     más clientes con problemas de internet, con el desglose de a qué se debió.

Se alimenta de los mismos datos de Redash que usa el chatbot.
"""

import datetime as dt

import pandas as pd
import streamlit as st

from analisis import (DIAS_BASE, HORAS, MINIMO_CASOS_CAUSA, MINIMO_CASOS_DIM,
                      MINIMO_DIAS_BASE, PCT_CONCENTRADO, PCT_DOMINANTE,
                      PISO_MINIMO, analizar, bonito, crecio, en_palabras,
                      fecha_larga, fechas, perfil_de_la_hora)

# Rampa de un solo tono (azul, claro→oscuro): más autodiagnósticos = más oscuro.
# Estos 4 pasos son los que se distinguen entre sí Y se leen bien tanto en tema
# claro como en tema oscuro (validados con el verificador de paletas).
RAMPA = ["#86b6ef", "#5598e7", "#2a78d6", "#184f95"]

# Color de estado para las horas en alerta. Nunca va solo: siempre con el 🔥 y
# el texto, para que se entienda también sin distinguir colores.
COLOR_PICO = "#d03b3b"      # crítico

_CSS = (
    "<style>"
    ".td{font-size:.86rem;line-height:1.3}"
    ".td-hero{font-size:2.2rem;font-weight:700;letter-spacing:-.02em;margin-bottom:-2px}"
    ".td-sub{opacity:.65;font-size:.78rem;margin-bottom:10px}"
    ".td-chip{display:flex;gap:7px;align-items:flex-start;padding:8px 10px;"
    "border-radius:8px;margin:0 0 12px 0;background:rgba(128,128,128,.10)}"
    ".td-chip .td-txt{opacity:.8;font-size:.78rem}"
    ".td-medidor{position:relative;height:9px;border-radius:5px;"
    "background:rgba(128,128,128,.16);margin:14px 0 3px 0}"
    ".td-medidor i{position:absolute;left:0;top:0;bottom:0;border-radius:5px}"
    ".td-marca{position:absolute;top:-4px;bottom:-4px;width:2px;background:rgba(128,128,128,.8)}"
    ".td-esc{display:flex;opacity:.6;font-size:.7rem;margin-bottom:14px}"
    ".td-esc span{flex:1}"  # tercios iguales: así "lo habitual" queda justo bajo la marca
    ".td-esc span:nth-child(2){text-align:center}"
    ".td-esc span:nth-child(3){text-align:right}"
    # Filas del gráfico por hora (una por hora del día). Misma retícula en el
    # encabezado y en las filas para que las columnas queden alineadas.
    ".td-rej{display:grid;grid-template-columns:54px 1fr 52px 64px 26px;gap:12px;"
    "align-items:center}"
    ".td-tope{font-size:.68rem;letter-spacing:.06em;text-transform:uppercase;"
    "opacity:.5;padding-bottom:6px;margin-bottom:6px;"
    "border-bottom:1px solid rgba(128,128,128,.22)}"
    ".td-fila{height:26px}"
    ".td-hora{text-align:right;font-size:.8rem;opacity:.75;"
    "font-variant-numeric:tabular-nums}"
    ".td-pista{position:relative;height:14px;border-radius:7px;"
    "background:rgba(128,128,128,.12)}"
    ".td-barra{position:absolute;left:0;top:0;bottom:0;border-radius:0 5px 5px 0}"
    ".td-ref{position:absolute;top:-3px;bottom:-3px;width:2px;border-radius:1px;"
    "background:rgba(128,128,128,.85)}"
    ".td-val{text-align:right;font-size:.86rem;font-weight:600;"
    "font-variant-numeric:tabular-nums}"
    ".td-hab{text-align:right;font-size:.8rem;opacity:.5;"
    "font-variant-numeric:tabular-nums}"
    ".td-ico{font-size:.8rem}"
    ".td-leyenda{display:flex;gap:12px;flex-wrap:wrap;opacity:.7;font-size:.72rem;"
    "margin-top:10px}"
    ".td-pt{display:inline-block;width:9px;height:9px;border-radius:2px;"
    "vertical-align:middle;margin-right:4px}"
    # Bloque de "por qué pasó": causas de falla de una hora marcada.
    ".td-explica{border-left:3px solid rgba(208,59,59,.5);padding:2px 0 2px 10px;"
    "margin:0 0 10px 0}"
    ".td-explica-cabeza{font-size:.78rem;opacity:.7;margin-bottom:6px}"
    ".td-causa{display:flex;gap:8px;align-items:baseline;margin-bottom:5px}"
    ".td-causa-pct{min-width:34px;text-align:right;font-weight:700;font-size:.86rem;"
    "font-variant-numeric:tabular-nums;opacity:.75}"
    ".td-causa-txt{font-size:.82rem;line-height:1.3}"
    ".td-causa-txt small{display:block;opacity:.6;font-size:.72rem}"
    ".td-causa.salta .td-causa-pct{opacity:1;color:#d03b3b}"
    ".td-causa.salta .td-causa-txt{font-weight:600}"
    ".td-sincausa{font-size:.82rem;opacity:.75}"
    # Reparto por canal y por ciudad de una hora marcada.
    ".td-dim{display:flex;gap:6px;align-items:baseline;margin-top:5px}"
    ".td-dim-etq{min-width:42px;font-size:.72rem;opacity:.55;text-transform:uppercase;"
    "letter-spacing:.04em}"
    ".td-dim-val{display:flex;flex-wrap:wrap;gap:4px}"
    ".td-mini{font-size:.75rem;padding:1px 6px;border-radius:4px;"
    "background:rgba(128,128,128,.14);white-space:nowrap}"
    ".td-mini.salta{background:rgba(208,59,59,.16);font-weight:600}"
    "</style>"
)


# --- Piezas de presentación --------------------------------------------------
def _html_dimension(etiqueta: str, items: list[dict]) -> str:
    """Línea compacta con el reparto de canal o ciudad, marcando lo que se concentró."""
    if not items:
        return ""
    trozos = []
    for it in items:
        hab = it["pct_habitual"]
        salta = crecio(it, PCT_CONCENTRADO, MINIMO_CASOS_DIM)
        titulo = (f"{it['casos']} casos"
                  + (f" · habitual {hab:.0f}%" if hab is not None else " · no aparecía"))
        trozos.append(
            f"<span class='td-mini{' salta' if salta else ''}' title='{titulo}'>"
            f"{bonito(it['valor'])} {it['pct']:.0f}%"
            f"{'&nbsp;↑' if salta else ''}</span>"
        )
    return (f"<div class='td-dim'><span class='td-dim-etq'>{etiqueta}</span>"
            f"<span class='td-dim-val'>{''.join(trozos)}</span></div>")


def _html_explicacion(dato: dict, hora: int) -> str:
    """Bloque con la explicación de una hora marcada: causa, canal y ciudad."""
    total, fallidos = dato["total"], dato["fallidos"]
    causas = dato["repartos"].get("causa", [])
    partes = []

    if not causas:
        partes.append(
            "<div class='td-sincausa'>Ninguno de esos autodiagnósticos falló: el pico "
            "fue de procesos que corrieron bien, así que parece más demanda que avería."
            "</div>")
    else:
        if causas[0]["pct"] < PCT_DOMINANTE:
            partes.append(
                "<div class='td-sincausa'>Los fallos están repartidos, sin una causa "
                "que explique el pico por sí sola.</div>")
        for c in causas:
            hab = c["pct_habitual"]
            salto = crecio(c, PCT_DOMINANTE, MINIMO_CASOS_CAUSA)
            ref = "no aparecía a esta hora" if hab is None else f"habitual {hab:.0f}%"
            pct_txt = "<1%" if 0 < c["pct"] < 0.5 else f"{c['pct']:.0f}%"
            casos_txt = "1 caso" if c["casos"] == 1 else f"{c['casos']} casos"
            partes.append(
                f"<div class='td-causa{' salta' if salto else ''}'>"
                f"<span class='td-causa-pct'>{pct_txt}</span>"
                f"<span class='td-causa-txt'>{en_palabras(c['valor'])}"
                f"<small>{casos_txt} · {ref}"
                f"{' · esto es lo que cambió' if salto else ''}</small></span></div>"
            )

    partes.append(_html_dimension("Canal", dato["repartos"].get("canal", [])))
    partes.append(_html_dimension("Ciudad", dato["repartos"].get("ciudad", [])))

    return (
        f"{_CSS}<div class='td td-explica'>"
        f"<div class='td-explica-cabeza'>{hora:02d}:00 · {total} autodiagnósticos, "
        f"{fallidos} con falla</div>{''.join(partes)}</div>"
    )


# --- Dibujo ------------------------------------------------------------------
def _umbrales_color(conteo: pd.Series, picos: set[int]) -> list[float]:
    """Cortes de color: los cuartiles de las horas del día.

    Se dejan fuera las horas vacías y los picos marcados: si un día tuvo una hora
    con 137 casos y el resto con 20, medir el color contra ese máximo pintaría
    todo el día del tono más claro y no se vería dónde estuvo el movimiento."""
    valores = [int(v) for h, v in conteo.items() if v > 0 and h not in picos]
    if len(valores) >= 4:
        s = pd.Series(valores)
        return [float(s.quantile(q)) for q in (0.25, 0.5, 0.75)]
    maximo = float(conteo.max()) if len(conteo) else 0.0
    return [maximo * f for f in (0.25, 0.5, 0.75)]


def _paso_color(valor: int, umbrales: list[float]) -> str:
    """Más autodiagnósticos = azul más oscuro (escala de un solo tono)."""
    idx = sum(1 for u in umbrales if valor > u)
    return RAMPA[min(idx, len(RAMPA) - 1)]


def _html_medidor(desvio: float | None, color: str) -> str:
    """Barra tipo termómetro: la marca gris es 'lo habitual'; el relleno, el día elegido."""
    if desvio is None:
        return ""
    # La escala va de 0 al doble de lo habitual; la marca queda justo a la mitad.
    pct = max(0.0, min(2.0, 1 + desvio)) / 2 * 100
    return (
        f"<div class='td-medidor'><i style='width:{pct:.1f}%;background:{color}'></i>"
        f"<span class='td-marca' style='left:50%'></span></div>"
        "<div class='td-esc'><span>0</span><span>lo habitual</span><span>el doble</span></div>"
    )


def _html_grafico_horas(conteo: pd.Series, habitual: pd.Series | None,
                        picos: set[int], hora_corte: int) -> str:
    """Las 24 horas del día, cada una con su barra y una marca en lo habitual.

    La marca gris es la referencia de esa hora: se ve de un golpe si el día va
    por encima o por debajo, hora por hora, sin tener que leer los números."""
    # La escala incluye lo habitual para que la marca de referencia siempre quepa.
    maximo = int(conteo.max()) if len(conteo) else 0
    if habitual is not None and len(habitual):
        maximo = max(maximo, int(habitual.max()))
    umbrales = _umbrales_color(conteo, picos)

    filas = [
        "<div class='td-rej td-tope'><span style='text-align:right'>Hora</span>"
        "<span>Autodiagnósticos en la hora</span>"
        "<span style='text-align:right'>Hoy</span>"
        "<span style='text-align:right'>Habitual</span><span></span></div>"
    ]
    for h in HORAS:
        etiqueta = f"{h:02d}:00"
        hab = float(habitual[h]) if habitual is not None else None
        marca = ""
        hab_txt = "—" if hab is None else f"{hab:.0f}"
        # Si lo habitual es 0 no se dibuja marca: quedaría pegada al borde y se
        # confundiría con el arranque de la pista.
        if hab and maximo:
            marca = f"<span class='td-ref' style='left:{hab / maximo * 100:.1f}%'></span>"

        if h > hora_corte:  # horas que aún no han ocurrido (día en curso)
            filas.append(
                f"<div class='td-rej td-fila' title='{etiqueta} — todavía no ha ocurrido'>"
                f"<span class='td-hora'>{etiqueta}</span>"
                f"<span class='td-pista'>{marca}</span>"
                f"<span class='td-val' style='opacity:.35'>—</span>"
                f"<span class='td-hab'>{hab_txt}</span>"
                f"<span class='td-ico'></span></div>"
            )
            continue

        valor = int(conteo[h])
        es_pico = h in picos
        color = COLOR_PICO if es_pico else _paso_color(valor, umbrales)
        ancho = (valor / maximo * 100) if maximo else 0
        barra = (f"<span class='td-barra' style='width:{max(ancho, 1.5):.1f}%;"
                 f"background:{color}'></span>") if valor else ""
        casos = "1 autodiagnóstico" if valor == 1 else f"{valor} autodiagnósticos"
        ref = f" · habitual: {hab:.0f}" if hab is not None else ""
        aviso = " · MUY por encima de lo habitual" if es_pico else ""
        filas.append(
            f"<div class='td-rej td-fila' title='{etiqueta} — {casos}{ref}{aviso}'>"
            f"<span class='td-hora'>{etiqueta}</span>"
            f"<span class='td-pista'>{barra}{marca}</span>"
            f"<span class='td-val'>{valor}</span>"
            f"<span class='td-hab'>{hab_txt}</span>"
            f"<span class='td-ico'>{'🔥' if es_pico else ''}</span></div>"
        )
    return "".join(filas)


def _estado_de_la_alerta() -> None:
    """Explica que el aviso también sale por correo.

    OJO: aquí NO se puede comprobar si el envío está configurado. El correo lo
    manda un proceso aparte en GitHub Actions, con sus propios secrets, y esta
    pantalla corre en Streamlit Cloud, que no los ve ni los necesita. La primera
    versión de esta línea consultaba las variables del proceso de la app y por
    eso anunciaba "sin configurar" mientras la alerta llevaba días funcionando.
    Si algún día hay que mostrar el estado real, tiene que venir de un dato que
    el propio proceso de la alerta deje escrito, no de mirar el entorno."""
    st.caption(
        "📧 Cuando una hora entra en 🔥, el equipo de CX recibe un correo con "
        "este mismo desglose. Lo envía un proceso que revisa cada hora por fuera "
        "de esta pantalla, así que llega aunque nadie tenga la app abierta."
    )


# --- Dashboard ---------------------------------------------------------------
def render(df: pd.DataFrame, col_fecha: str | None, col_causa: str | None = None,
           col_canal: str | None = None, col_ciudad: str | None = None) -> None:
    """Dibuja el dashboard del termómetro. 'df' ya viene con los filtros de la
    barra lateral aplicados (menos el de fecha, que lo decide este dashboard).
    Las columnas de causa, canal y ciudad se usan para explicar a qué se debió un
    pico: qué falló, por dónde entró y dónde se concentró."""
    st.caption(
        "Cuántos autodiagnósticos se ejecutaron en cada hora del día elegido, y "
        "aviso cuando el volumen se sale de lo normal. Cada hora se compara con "
        "esa misma hora de los días anteriores. Hora local de Colombia."
    )

    if df is None or df.empty or not col_fecha:
        st.info("Cuando haya datos cargados, aquí verás los picos de actividad por hora.")
        return

    fechas_todas = fechas(df, col_fecha)   # alineada con df, para el desglose
    con_fecha = fechas_todas.dropna()      # solo las válidas, para los conteos
    if con_fecha.empty:
        st.info("Los datos cargados no tienen fechas de inicio para analizar por hora.")
        return

    dia_min, dia_max = con_fecha.min().date(), con_fecha.max().date()
    # Si al cambiar un filtro de la izquierda el día elegido queda fuera del rango
    # disponible (ej. filtrar por una directriz que solo existe desde agosto),
    # lo movemos al último día con datos en vez de dejar que la app falle.
    elegido = st.session_state.get("termometro_dia")
    if not isinstance(elegido, dt.date) or not (dia_min <= elegido <= dia_max):
        st.session_state["termometro_dia"] = dia_max  # arranca en el último día con datos

    # --- Fila superior: día, cifra del día y estado ---
    c_dia, c_hero, c_estado = st.columns([1, 1, 2], gap="large")

    with c_dia:
        dia = st.date_input("Día a analizar",
                            min_value=dia_min, max_value=dia_max,
                            key="termometro_dia",
                            help="Cambia el día para ver cómo se movieron las horas.")
        if isinstance(dia, (list, tuple)):  # por si el control devuelve un rango
            dia = dia[0]

    a = analizar(con_fecha, dia, dia_max)
    total, conteo, habitual, picos = a["total"], a["conteo"], a["habitual"], a["picos"]
    nivel = a["nivel"]

    with c_hero:
        sufijo = f" hasta las {a['hora_corte']:02d}:59" if a["en_curso"] else ""
        st.markdown(
            _CSS + "<div class='td'>"
            f"<div class='td-hero'>{f'{total:,}'.replace(',', '.')}</div>"
            f"<div class='td-sub'>autodiagnósticos el {fecha_larga(dia)}{sufijo}</div>"
            "</div>", unsafe_allow_html=True)

    with c_estado:
        if nivel["desvio"] is None:
            detalle = (f"No hay suficientes días anteriores cargados para comparar "
                       f"(se necesitan {MINIMO_DIAS_BASE}).")
        else:
            signo = "▲" if nivel["desvio"] >= 0 else "▼"
            detalle = (f"{signo} {abs(nivel['desvio']) * 100:.0f}% frente a lo habitual "
                       f"({a['habitual_dia']:.0f} en un día normal de los últimos "
                       f"{a['dias_base']} días"
                       f"{', mismo tramo de horas' if a['en_curso'] else ''}).")
        st.markdown(
            _CSS + "<div class='td'>"
            f"<div class='td-chip'><span>{nivel['icono']}</span><span>"
            f"<b style='color:{nivel['color']}'>{nivel['etiqueta']}</b>"
            f"<span class='td-txt'>{detalle}</span></span></div>"
            + _html_medidor(nivel["desvio"], nivel["color"]) +
            "</div>", unsafe_allow_html=True)

    if not total:
        st.warning("No hubo autodiagnósticos ese día (con los filtros actuales).")
        return

    # --- Cifras del día ---
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Hora con más movimiento", f"{a['hora_pico']:02d}:00",
              f"{int(conteo[a['hora_pico']])} casos", delta_color="off")
    if a["hay_base"]:
        m2.metric("Un día habitual", f"{a['habitual_dia']:,.0f}".replace(",", "."),
                  "el día anterior" if a["dias_base"] == 1
                  else f"mediana de {a['dias_base']} días", delta_color="off")
    else:
        m2.metric("Un día habitual", "—", "sin referencia aún", delta_color="off")
    m3.metric("Horas en alerta", f"{len(picos)}",
              "ninguna fuera de rango" if not picos else "revisar el detalle",
              delta_color="off")
    if col_causa and col_causa in df.columns:
        del_dia = df.loc[fechas_todas.dt.date == dia]
        fallidos = int(del_dia[col_causa].notna().sum())
        m4.metric("Con falla", f"{fallidos:,}".replace(",", "."),
                  f"{fallidos / total * 100:.0f}% del día", delta_color="off")

    st.divider()

    # --- Gráfico por hora + explicación de los picos ---
    c_graf, c_expl = st.columns([2, 1], gap="large")

    with c_graf:
        leyenda = (
            f"<div class='td-leyenda'>"
            f"<span><i class='td-pt' style='background:{RAMPA[3]}'></i>volumen de la "
            f"hora (más oscuro = más)</span>"
            f"<span><i class='td-pt' style='background:{COLOR_PICO}'></i>🔥 pico "
            f"inusual</span>"
            f"<span><i class='td-pt' style='background:rgba(128,128,128,.85);"
            f"width:2px;height:12px'></i>lo habitual de esa hora</span></div>"
        )
        st.markdown(
            _CSS + "<div class='td'>"
            + _html_grafico_horas(conteo, habitual, picos, a["hora_corte"])
            + leyenda + "</div>", unsafe_allow_html=True)

    with c_expl:
        if not picos:
            st.markdown("##### Sin picos hoy")
            st.caption(
                "Ninguna hora llegó al doble de lo habitual, así que el día se movió "
                "dentro de lo esperado. Cuando alguna se salga, aquí aparecerá qué "
                "falló, por dónde entró y en qué ciudad se concentró."
            )
        else:
            st.markdown(f"##### A qué se debió")
            st.caption("La flecha ↑ marca lo que creció frente a lo habitual de esa "
                       "hora (pasa el mouse para ver la cifra).")
            columnas = {"causa": col_causa, "canal": col_canal, "ciudad": col_ciudad}
            hay_columnas = any(c and c in df.columns for c in columnas.values())
            desde = dia - dt.timedelta(days=DIAS_BASE)
            for h in sorted(picos):
                if hay_columnas:
                    perfil = perfil_de_la_hora(df, fechas_todas, dia, h, desde, columnas)
                    st.markdown(_html_explicacion(perfil, h), unsafe_allow_html=True)
                else:
                    st.markdown(f"**{h:02d}:00** — {int(conteo[h])} casos, "
                                f"{habitual[h]:.0f} habituales.")

        _estado_de_la_alerta()

    # --- Tabla (misma información, para quien prefiera leerla en números) ---
    hora_corte, hay_base, dias_base = a["hora_corte"], a["hay_base"], a["dias_base"]
    with st.expander("Ver la tabla de horas"):
        casos = [int(conteo[h]) if h <= hora_corte else None for h in HORAS]
        habituales = [round(float(habitual[h]), 1) if hay_base else None for h in HORAS]
        veces = [
            round(c / hb, 1) if (c is not None and hb) else None
            for c, hb in zip(casos, habituales)
        ]
        st.dataframe(pd.DataFrame({
            "Hora": [f"{h:02d}:00" for h in HORAS],
            "Autodiagnósticos": casos,
            "Lo habitual": habituales,
            "Veces lo habitual": veces,
            "Alerta": ["🔥" if h in picos else "" for h in HORAS],
        }), use_container_width=True, hide_index=True)

    dias_txt = "el día anterior" if dias_base == 1 else f"los últimos {dias_base} días"
    st.caption(
        f"“Lo habitual” = la mediana de esa misma hora en {dias_txt} con datos. "
        f"Una hora se marca 🔥 cuando tuvo **el doble o más** de lo habitual de esa "
        f"hora (con un piso de {PISO_MINIMO} casos para las horas más quietas) y "
        f"quedó fuera de lo que esa hora suele variar."
    )
