"""
Alerta por correo cuando los autodiagnósticos se disparan en una hora.

Revisa la última hora COMPLETA de datos y, si se salió de lo normal, manda un
correo al equipo con el desglose: cuántos fueron, qué falló, en qué ciudad y por
qué canal entraron.

Usa la MISMA regla que el termómetro de la app (`analisis.py`), así que la
pantalla y el correo nunca dicen cosas distintas.

Cómo se usa
-----------
  python alertas.py                  revisa y envía si hay pico
  python alertas.py --prueba         no envía nada: escribe el correo en un
                                     archivo HTML para poder revisarlo
  python alertas.py --dia 2026-08-21 --hora 8 --prueba
                                     arma el correo de una hora concreta
                                     (útil para ver cómo queda con un caso real)
  python alertas.py --probar-envio --solo-a tu@correo.com
                                     manda un correo corto de prueba para
                                     comprobar que las credenciales funcionan
  python alertas.py --ignorar-estado vuelve a avisar de una hora ya avisada

  OJO: sin --prueba y sin --solo-a, el correo va a TODA la lista. Al configurar
  por primera vez conviene usar --solo-a con el correo propio.

Configuración (en .env local o en Secrets de GitHub / Streamlit)
---------------------------------------------------------------
  SMTP_HOST                 servidor de correo (por defecto smtp.gmail.com)
  SMTP_PORT                 puerto (por defecto 587)
  SMTP_USUARIO              cuenta desde la que se envía
  SMTP_CLAVE                contraseña de aplicación de esa cuenta
  ALERTA_REMITENTE          opcional; por defecto SMTP_USUARIO
  ALERTA_DESTINATARIOS      correos separados por coma
  ALERTA_URL_APP            enlace al termómetro, para el botón del correo
  ALERTA_CADA_N_HORAS       si el pico sigue, cada cuántas horas repetir el aviso
  ALERTA_MAX_ATRASO_HORAS   si el dato viene más viejo que esto, no avisa
  ALERTA_REFRESCAR_REDASH   "1" para forzar una corrida nueva de la consulta

NUNCA se ponen claves en el código. Si falta SMTP_CLAVE, el script no envía
nada: avisa por consola y termina.
"""

import argparse
import datetime as dt
import json
import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

import analisis
import redash

load_dotenv()

# A quién se le avisa si no se configura otra cosa.
DESTINATARIOS_POR_DEFECTO = [
    "mbustamante@fibrazo.com",
    "busuga@fibrazo.com",
    "jgaravito@fibrazo.com",
    "jmantilla@fibrazo.com",
    "ammunoz@fibrazo.com",
]

ARCHIVO_ESTADO = Path(__file__).with_name(".alerta_estado.json")
ARCHIVO_PRUEBA = Path(__file__).with_name("alerta_prueba.html")

# Columnas que se usan para explicar el pico.
COLUMNAS = {"causa": "failure_reason", "canal": "source", "ciudad": "nombre_ciudad"}
COL_FECHA = "started_at"

ETIQUETAS = {"causa": "Qué falló", "canal": "Por dónde entró", "ciudad": "Dónde"}


# --- Configuración -----------------------------------------------------------
def destinatarios() -> list[str]:
    crudo = os.environ.get("ALERTA_DESTINATARIOS", "").strip()
    if not crudo:
        return list(DESTINATARIOS_POR_DEFECTO)
    return [c.strip() for c in crudo.replace(";", ",").split(",") if c.strip()]


def _entero(nombre: str, defecto: int) -> int:
    try:
        return int(os.environ.get(nombre, defecto))
    except ValueError:
        return defecto


def _si(nombre: str) -> bool:
    return os.environ.get(nombre, "").strip() in ("1", "true", "si", "sí")


def puede_enviar() -> bool:
    """Si hay con qué enviar. Hay dos formas válidas:

    1. Usuario y clave (Gmail con contraseña de aplicación, Office 365, etc.).
    2. Un relay interno de la empresa que autoriza por IP y no pide clave; en ese
       caso basta el servidor y SMTP_SIN_LOGIN=1."""
    if _si("SMTP_SIN_LOGIN"):
        return bool(os.environ.get("SMTP_HOST"))
    return bool(os.environ.get("SMTP_USUARIO") and os.environ.get("SMTP_CLAVE"))


# --- Qué hora revisar --------------------------------------------------------
def ultima_hora_completa(serie_fechas: pd.Series) -> tuple[dt.date, int] | None:
    """La última hora que ya terminó y de la que hay datos completos.

    Si el último dato es de las 08:20, la última hora completa es la de las 07:00:
    la de las 08:00 todavía está a medias y avisaría con la mitad de los casos."""
    if serie_fechas.empty:
        return None
    fin = serie_fechas.max().floor("h") - pd.Timedelta(hours=1)
    return fin.date(), int(fin.hour)


def atraso_del_dato(serie_fechas: pd.Series) -> dt.timedelta:
    """Cuánto tiempo pasó desde el último autodiagnóstico registrado."""
    ahora = (dt.datetime.now(dt.UTC).replace(tzinfo=None)
             + dt.timedelta(hours=analisis.horas_a_local()))
    return ahora - serie_fechas.max().to_pydatetime()


def posicion_en_racha(picos: set[int], hora: int) -> int:
    """Si el pico viene de horas seguidas, en qué número de hora vamos.

    Sirve para no mandar un correo por hora durante un evento largo: el primero
    se manda siempre, y después solo cada ALERTA_CADA_N_HORAS."""
    pos = 1
    h = hora - 1
    while h >= 0 and h in picos:
        pos += 1
        h -= 1
    return pos


def toca_avisar(pos: int) -> bool:
    cada = max(1, _entero("ALERTA_CADA_N_HORAS", 3))
    return pos == 1 or pos % cada == 0


# --- Estado (para no repetir el mismo aviso) ---------------------------------
def estado_leer() -> dict:
    try:
        return json.loads(ARCHIVO_ESTADO.read_text(encoding="utf-8"))
    except Exception:
        return {}


def estado_guardar(dia: dt.date, hora: int) -> None:
    try:
        ARCHIVO_ESTADO.write_text(
            json.dumps({"ultima_hora_avisada": f"{dia.isoformat()}T{hora:02d}"}),
            encoding="utf-8")
    except Exception as e:  # no es crítico: en el peor caso se repite un aviso
        print(f"  (no pude guardar el estado: {e})")


# --- Resumen de lo que está pasando ------------------------------------------
def armar_resumen(df: pd.DataFrame, dia: dt.date, hora: int) -> dict | None:
    """Junta todo lo que va en el correo. Devuelve None si esa hora no es un pico."""
    serie = analisis.fechas(df, COL_FECHA)
    con_fecha = serie.dropna()
    dia_max = con_fecha.max().date()

    a = analisis.analizar(con_fecha, dia, dia_max)
    if not a["hay_base"]:
        return None
    base = float(a["habitual"][hora])
    casos = int(a["conteo"][hora])
    if not analisis.es_pico(casos, base, a["previos"][hora]):
        return None

    desde = dia - dt.timedelta(days=analisis.DIAS_BASE)
    perfil = analisis.perfil_de_la_hora(df, serie, dia, hora, desde, COLUMNAS)

    # Las últimas horas, para ver la forma del evento.
    ultimas = []
    for h in range(max(0, hora - 5), hora + 1):
        ultimas.append({
            "hora": h,
            "casos": int(a["conteo"][h]),
            "habitual": float(a["habitual"][h]),
            "pico": h in a["picos"],
        })

    # "El día hasta ahora" se corta en la hora que se está avisando: el correo no
    # puede hablar de horas que, en el momento del aviso, todavía no habían pasado.
    tramo = [h for h in analisis.HORAS if h <= hora]
    dia_total = int(a["conteo"][tramo].sum())
    dia_habitual = float(a["previos"][tramo].sum(axis=1).median())

    return {
        "dia": dia, "hora": hora, "casos": casos, "habitual": base,
        "veces": casos / base if base else None,
        "perfil": perfil,
        "cambios": analisis.lo_que_cambio(perfil),
        "dia_total": dia_total, "dia_habitual": dia_habitual,
        "dia_nivel": analisis.nivel(dia_total, dia_habitual),
        "dia_picos": sorted(h for h in a["picos"] if h <= hora),
        "ultimas": ultimas,
        "posicion": posicion_en_racha(a["picos"], hora),
    }


def interpretacion(r: dict) -> str:
    """Una frase que ayude a leer el pico, sin afirmar más de lo que se sabe."""
    porc = {clave: item for clave, item in r["cambios"]}
    causa = porc.get("causa")
    ciudad = porc.get("ciudad")
    canal = porc.get("canal")

    if causa and ciudad:
        return (f"El {causa['pct']:.0f}% de los casos falló por "
                f"«{analisis.en_palabras(causa['valor'])}» y el "
                f"{ciudad['pct']:.0f}% viene de {analisis.bonito(ciudad['valor'])}. "
                f"Un patrón así apunta a un problema localizado en esa zona, no a "
                f"algo general del sistema.")
    if ciudad and not causa:
        return (f"El {ciudad['pct']:.0f}% de los casos viene de "
                f"{analisis.bonito(ciudad['valor'])} (lo habitual a esta hora es "
                f"{ciudad['pct_habitual']:.0f}%), pero los fallos están repartidos "
                f"entre varias causas.")
    if causa and not ciudad:
        return (f"El {causa['pct']:.0f}% de los casos falló por "
                f"«{analisis.en_palabras(causa['valor'])}», y está repartido entre "
                f"varias ciudades: apunta a algo transversal del sistema más que a "
                f"una zona.")
    if canal:
        return (f"El aumento entró sobre todo por "
                f"{analisis.bonito(canal['valor'])} ({canal['pct']:.0f}% de los "
                f"casos), sin una causa ni una ciudad que destaque.")
    return ("El aumento no se concentra en ninguna causa, ciudad ni canal en "
            "particular: parece más demanda que una falla puntual.")


# --- Redacción del correo ----------------------------------------------------
def asunto(r: dict) -> str:
    veces = f"{r['veces']:.0f}×" if r["veces"] and r["veces"] >= 2 else "por encima de"
    donde = ""
    for clave, item in r["cambios"]:
        if clave == "ciudad":
            donde = f" · {analisis.bonito(item['valor'])}"
            break
    if r["posicion"] > 1:
        return (f"🔥 Sigue el pico de autodiagnósticos · {r['hora']:02d}:00 · "
                f"{r['casos']} casos · {r['posicion']}ª hora seguida{donde}")
    return (f"🔥 Pico de autodiagnósticos · {r['hora']:02d}:00 · {r['casos']} casos "
            f"({veces} lo habitual){donde}")


def _fila_cambio(clave: str, items: list[dict], total: int) -> str:
    """Una fila de la tabla 'qué está pasando', resaltando lo que creció."""
    if not items:
        return ""
    it = items[0]
    hab = it["pct_habitual"]
    pct_min = (analisis.PCT_DOMINANTE if clave == "causa" else analisis.PCT_CONCENTRADO)
    casos_min = (analisis.MINIMO_CASOS_CAUSA if clave == "causa"
                 else analisis.MINIMO_CASOS_DIM)
    subio = analisis.crecio(it, pct_min, casos_min)
    valor = (analisis.en_palabras(it["valor"]) if clave == "causa"
             else analisis.bonito(it["valor"]))
    ref = "no aparecía a esta hora" if hab is None else f"habitual {hab:.0f}%"
    color = "#b3261e" if subio else "#3c4043"
    peso = "700" if subio else "400"
    marca = (" &nbsp;<span style='background:#fce8e6;color:#b3261e;font-size:11px;"
             "padding:2px 6px;border-radius:10px'>esto cambió</span>") if subio else ""
    return (
        f"<tr>"
        f"<td style='padding:8px 12px 8px 0;color:#80868b;font-size:12px;"
        f"white-space:nowrap;vertical-align:top'>{ETIQUETAS[clave]}</td>"
        f"<td style='padding:8px 0;color:{color};font-weight:{peso};font-size:14px'>"
        f"{valor}{marca}"
        f"<div style='color:#80868b;font-weight:400;font-size:12px;padding-top:2px'>"
        f"{it['pct']:.0f}% de los casos · {it['casos']} de {total} · {ref}</div>"
        f"</td></tr>"
    )


def cuerpo_html(r: dict) -> str:
    nivel = r["dia_nivel"]
    url = os.environ.get("ALERTA_URL_APP", "").strip()
    veces_txt = (f"{r['veces']:.1f} veces lo habitual".replace(".0 ", " ")
                 if r["veces"] else "por encima de lo habitual")

    filas_cambio = "".join(
        _fila_cambio(clave, r["perfil"]["repartos"].get(clave, []), r["casos"])
        for clave in ("causa", "ciudad", "canal"))

    filas_horas = ""
    for u in r["ultimas"]:
        fondo = "#fce8e6" if u["pico"] else "#ffffff"
        marca = "🔥" if u["pico"] else ""
        filas_horas += (
            f"<tr style='background:{fondo}'>"
            f"<td style='padding:6px 10px;font-size:13px;color:#3c4043'>"
            f"{u['hora']:02d}:00</td>"
            f"<td style='padding:6px 10px;font-size:13px;text-align:right;"
            f"font-weight:600;color:#202124'>{u['casos']}</td>"
            f"<td style='padding:6px 10px;font-size:13px;text-align:right;"
            f"color:#80868b'>{u['habitual']:.0f}</td>"
            f"<td style='padding:6px 10px;font-size:13px'>{marca}</td></tr>"
        )

    picos_txt = ", ".join(f"{h:02d}:00" for h in r["dia_picos"])
    boton = ""
    if url:
        boton = (
            f"<tr><td style='padding:24px 0 0'>"
            f"<a href='{url}' style='background:#1a73e8;color:#ffffff;"
            f"text-decoration:none;padding:12px 20px;border-radius:6px;"
            f"font-size:14px;font-weight:600;display:inline-block'>"
            f"Ver el detalle en el termómetro</a></td></tr>")

    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f1f3f4;
             font-family:-apple-system,'Segoe UI',Roboto,Arial,sans-serif">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:#f1f3f4;padding:24px 12px">
<tr><td align="center">
  <table role="presentation" width="600" cellpadding="0" cellspacing="0"
         style="max-width:600px;background:#ffffff;border-radius:12px;
                overflow:hidden;box-shadow:0 1px 3px rgba(60,64,67,.2)">

    <tr><td style="background:{nivel['color']};padding:18px 24px">
      <div style="color:#ffffff;font-size:18px;font-weight:700">
        🔥 Pico de autodiagnósticos</div>
      <div style="color:#ffffff;opacity:.9;font-size:13px;padding-top:2px">
        {analisis.fecha_larga(r['dia'])} · {r['hora']:02d}:00 a {r['hora']:02d}:59
        (hora de Colombia)</div>
    </td></tr>

    <tr><td style="padding:24px 24px 8px">
      <div style="font-size:40px;font-weight:700;color:#202124;line-height:1">
        {r['casos']}</div>
      <div style="font-size:14px;color:#3c4043;padding-top:4px">
        autodiagnósticos en esa hora — <b>{veces_txt}</b>
        <span style="color:#80868b">({r['habitual']:.0f} en un día normal a esa
        hora)</span></div>
      <div style="font-size:14px;color:#3c4043;padding:16px 0 0;line-height:1.5">
        {interpretacion(r)}</div>
    </td></tr>

    <tr><td style="padding:16px 24px 0">
      <div style="font-size:11px;font-weight:700;color:#80868b;
                  letter-spacing:.08em;text-transform:uppercase;
                  border-bottom:1px solid #e8eaed;padding-bottom:8px">
        Qué está pasando</div>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
             style="margin-top:4px">{filas_cambio}</table>
    </td></tr>

    <tr><td style="padding:20px 24px 0">
      <div style="font-size:11px;font-weight:700;color:#80868b;
                  letter-spacing:.08em;text-transform:uppercase;
                  border-bottom:1px solid #e8eaed;padding-bottom:8px">
        Las últimas horas</div>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
             style="margin-top:6px;border-collapse:collapse">
        <tr>
          <td style="padding:0 10px 6px;font-size:11px;color:#80868b">Hora</td>
          <td style="padding:0 10px 6px;font-size:11px;color:#80868b;
                     text-align:right">Casos</td>
          <td style="padding:0 10px 6px;font-size:11px;color:#80868b;
                     text-align:right">Habitual</td>
          <td style="padding:0 10px 6px"></td>
        </tr>
        {filas_horas}
      </table>
    </td></tr>

    <tr><td style="padding:20px 24px 0">
      <div style="background:#f8f9fa;border-radius:8px;padding:14px 16px">
        <div style="font-size:13px;color:#3c4043">
          <b>El día hasta ahora:</b> {r['dia_total']} autodiagnósticos hasta las
          {r['hora']:02d}:59, cuando un día normal llevaría
          {r['dia_habitual']:.0f}.
          {nivel['icono']} {nivel['etiqueta']}
          ({r['dia_nivel']['desvio'] * 100:+.0f}%).</div>
        <div style="font-size:13px;color:#3c4043;padding-top:6px">
          <b>Horas en alerta hoy:</b> {picos_txt}.</div>
      </div>
    </td></tr>

    {boton}

    <tr><td style="padding:24px 24px 24px">
      <div style="border-top:1px solid #e8eaed;padding-top:14px;font-size:12px;
                  color:#80868b;line-height:1.6">
        Este aviso es automático y <b>solo se envía cuando pasa algo</b>: no hay
        correos periódicos. Se dispara cuando una hora tiene <b>el doble o más</b>
        de los autodiagnósticos que suele tener <i>esa misma hora</i> (mediana de
        los últimos {analisis.DIAS_BASE} días) y además se sale de su rango
        normal. En los últimos 90 días eso habría ocurrido 57 veces, y en 6 de
        cada 10 días no habría llegado ningún correo.
        <br><br>
        Si el pico continúa, el aviso se repite cada
        {max(1, _entero('ALERTA_CADA_N_HORAS', 3))} horas, no cada hora.
      </div>
    </td></tr>
  </table>
</td></tr></table>
</body></html>"""


def cuerpo_texto(r: dict) -> str:
    """Versión en texto plano, para clientes de correo que no muestran HTML."""
    lineas = [
        f"PICO DE AUTODIAGNOSTICOS",
        f"{analisis.fecha_larga(r['dia'])}, {r['hora']:02d}:00 a {r['hora']:02d}:59 "
        f"(hora de Colombia)",
        "",
        f"{r['casos']} autodiagnosticos en esa hora "
        f"({r['habitual']:.0f} en un dia normal a esa hora).",
        "",
        interpretacion(r),
        "",
        "QUE ESTA PASANDO",
    ]
    for clave in ("causa", "ciudad", "canal"):
        items = r["perfil"]["repartos"].get(clave, [])
        if not items:
            continue
        it = items[0]
        valor = (analisis.en_palabras(it["valor"]) if clave == "causa"
                 else analisis.bonito(it["valor"]))
        hab = ("no aparecia a esta hora" if it["pct_habitual"] is None
               else f"habitual {it['pct_habitual']:.0f}%")
        lineas.append(f"  {ETIQUETAS[clave]}: {valor} — {it['pct']:.0f}% "
                      f"de los casos ({hab})")

    lineas += ["", "LAS ULTIMAS HORAS"]
    for u in r["ultimas"]:
        caso_txt = "caso " if u["casos"] == 1 else "casos"
        lineas.append(f"  {u['hora']:02d}:00  {u['casos']:>4} {caso_txt} "
                      f"(habitual {u['habitual']:.0f})"
                      + ("   <-- en alerta" if u["pico"] else ""))

    lineas += [
        "",
        f"El dia hasta ahora: {r['dia_total']} autodiagnosticos hasta las "
        f"{r['hora']:02d}:59, cuando un dia normal llevaria "
        f"{r['dia_habitual']:.0f} ({r['dia_nivel']['desvio'] * 100:+.0f}%).",
        f"Horas en alerta hoy: "
        f"{', '.join(f'{h:02d}:00' for h in r['dia_picos'])}.",
    ]
    url = os.environ.get("ALERTA_URL_APP", "").strip()
    if url:
        lineas += ["", f"Ver el detalle: {url}"]
    lineas += [
        "",
        "-- ",
        "Aviso automatico. Se envia cuando una hora tiene el doble o mas de los "
        "autodiagnosticos que suele tener esa misma hora.",
    ]
    return "\n".join(lineas)


# --- Envío -------------------------------------------------------------------
def enviar(asunto_txt: str, html: str, texto: str, destinos: list[str]) -> None:
    """Manda el correo. Aguanta las tres formas que suele haber en una empresa:
    Gmail/Office con usuario y clave, un relay interno sin clave (SMTP_SIN_LOGIN),
    y un relay interno sin cifrado en el puerto 25 (SMTP_SIN_TLS)."""
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    puerto = _entero("SMTP_PORT", 587)
    usuario = os.environ.get("SMTP_USUARIO", "")
    clave = os.environ.get("SMTP_CLAVE", "")
    remitente = os.environ.get("ALERTA_REMITENTE") or usuario
    sin_login = _si("SMTP_SIN_LOGIN")

    msg = EmailMessage()
    msg["Subject"] = asunto_txt
    msg["From"] = f"Termómetro de Autodiagnóstico <{remitente}>"
    msg["To"] = ", ".join(destinos)
    msg.set_content(texto)
    msg.add_alternative(html, subtype="html")

    if puerto == 465:
        with smtplib.SMTP_SSL(host, puerto, timeout=60) as s:
            if not sin_login:
                s.login(usuario, clave)
            s.send_message(msg)
        return

    with smtplib.SMTP(host, puerto, timeout=60) as s:
        if not _si("SMTP_SIN_TLS"):
            s.starttls()
        if not sin_login:
            s.login(usuario, clave)
        s.send_message(msg)


def correo_de_prueba() -> tuple[str, str, str]:
    """Un correo corto para comprobar que las credenciales quedaron bien.

    Existe porque, si no, la única forma de saber si el envío funciona es esperar
    a que haya un pico de verdad, y eso puede tardar días."""
    cada = max(1, _entero("ALERTA_CADA_N_HORAS", 3))
    asunto_txt = "✅ Prueba de la alerta de autodiagnósticos"
    texto = (
        "Prueba de configuracion\n\n"
        "Si estas leyendo esto, el envio de la alerta quedo funcionando.\n\n"
        "ESTE ES EL UNICO CORREO QUE LLEGA SIN QUE ESTE PASANDO NADA. No hay "
        "envios periodicos ni resumenes diarios: de aqui en adelante solo llega "
        "correo cuando hay algo que mirar.\n\n"
        "Que lo dispara: que en una hora se ejecuten el doble o mas de los "
        "autodiagnosticos que suele haber a esa misma hora (mediana de los "
        f"ultimos {analisis.DIAS_BASE} dias) y que ademas se salga de su rango "
        "normal.\n\n"
        "Para dar una idea de cada cuanto: mirando los ultimos 90 dias, habrian "
        "salido 57 avisos, y en 6 de cada 10 dias no habria llegado ninguno.\n\n"
        "Cada aviso trae cuantos fueron, que falla predomino, en que ciudad se "
        "concentro y por que canal entraron.\n\n"
        "Si un pico se alarga varias horas, tampoco llega un correo por hora: "
        f"llega el primero y despues un recordatorio cada {cada} horas mientras "
        "siga.\n\n"
        "-- \nEste es un correo de prueba: no hay ningun pico en curso."
    )
    html = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"></head>
<body style="margin:0;padding:24px 12px;background:#f1f3f4;
             font-family:-apple-system,'Segoe UI',Roboto,Arial,sans-serif">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center">
  <table role="presentation" width="600" cellpadding="0" cellspacing="0"
         style="max-width:600px;background:#ffffff;border-radius:12px;overflow:hidden">
    <tr><td style="background:#0ca30c;padding:18px 24px;color:#ffffff;
                   font-size:18px;font-weight:700">
      ✅ La alerta quedó configurada</td></tr>
    <tr><td style="padding:24px;font-size:14px;color:#3c4043;line-height:1.6">
      <p style="margin:0 0 14px">Si estás leyendo esto, el envío funciona.</p>
      <p style="margin:0 0 16px;background:#e6f4ea;border-radius:8px;
                padding:12px 14px"><b>Este es el único correo que llega sin que
      esté pasando nada.</b> No hay envíos periódicos ni resúmenes diarios: de
      aquí en adelante solo llega correo cuando hay algo que mirar.</p>
      <p style="margin:0 0 14px"><b>Qué lo dispara:</b> que en una hora se
      ejecuten <b>el doble o más</b> de los autodiagnósticos que suele haber a esa
      misma hora (mediana de los últimos {analisis.DIAS_BASE} días) y que además
      se salga de su rango normal.</p>
      <p style="margin:0 0 14px"><b>Cada cuánto, en la práctica:</b> mirando los
      últimos 90 días, habrían salido 57 avisos — y en <b>6 de cada 10 días no
      habría llegado ninguno</b>.</p>
      <p style="margin:0 0 14px">Cada aviso trae cuántos fueron, qué falla
      predominó, <b>en qué ciudad</b> se concentró y por qué canal entraron.</p>
      <p style="margin:0">Si un pico se alarga varias horas, tampoco llega un
      correo por hora: llega el primero y después un recordatorio cada
      {cada} horas mientras siga.</p>
    </td></tr>
    <tr><td style="padding:0 24px 24px">
      <div style="border-top:1px solid #e8eaed;padding-top:14px;font-size:12px;
                  color:#80868b">
        Este es un correo de prueba: no hay ningún pico en curso.</div>
    </td></tr>
  </table>
</td></tr></table></body></html>"""
    return asunto_txt, html, texto


# --- Programa ----------------------------------------------------------------
def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Avisa por correo si los autodiagnósticos se disparan en una hora.")
    p.add_argument("--prueba", action="store_true",
                   help="no envía nada; escribe el correo en un archivo HTML")
    p.add_argument("--dia", help="revisar un día concreto (AAAA-MM-DD)")
    p.add_argument("--hora", type=int, help="revisar una hora concreta (0-23)")
    p.add_argument("--ignorar-estado", action="store_true",
                   help="avisar aunque esa hora ya se hubiera avisado")
    p.add_argument("--solo-a", metavar="CORREOS",
                   help="enviar solo a estos correos (separados por coma), en vez "
                        "de a toda la lista. Para probar sin molestar al equipo.")
    p.add_argument("--probar-envio", action="store_true",
                   help="manda un correo corto de prueba para comprobar que las "
                        "credenciales funcionan, sin revisar si hay pico")
    args = p.parse_args(argv)

    destinos = ([c.strip() for c in args.solo_a.replace(";", ",").split(",")
                 if c.strip()] if args.solo_a else destinatarios())

    if args.probar_envio:
        asunto_txt, html, texto = correo_de_prueba()
        if not puede_enviar():
            print("No puedo enviar: faltan SMTP_USUARIO y SMTP_CLAVE.")
            print("Ponlos en el archivo .env (local) o en los Secrets de GitHub.")
            return 1
        try:
            enviar(asunto_txt, html, texto, destinos)
        except Exception as e:
            print(f"ERROR enviando el correo de prueba: {e}")
            print("Si usas Gmail, revisa que la clave sea una CONTRASEÑA DE "
                  "APLICACIÓN y no la contraseña normal de la cuenta.")
            return 1
        print(f"Correo de prueba enviado a: {', '.join(destinos)}")
        return 0

    forzado = bool(args.dia or args.hora is not None)
    refrescar = os.environ.get("ALERTA_REFRESCAR_REDASH", "1") == "1" and not forzado

    print("Trayendo los datos de Redash"
          + (" (forzando una corrida nueva)…" if refrescar else " (resultado en caché)…"))
    df = redash.obtener_datos(refrescar=refrescar, timeout_seg=240)
    serie = analisis.fechas_validas(df, COL_FECHA)
    if serie.empty:
        print("No hay datos con fecha. No hay nada que revisar.")
        return 0

    atraso = atraso_del_dato(serie)
    print(f"Último autodiagnóstico registrado: {serie.max():%Y-%m-%d %H:%M} "
          f"(hace {atraso})")

    if args.dia or args.hora is not None:
        dia = (dt.date.fromisoformat(args.dia) if args.dia else serie.max().date())
        hora = args.hora if args.hora is not None else int(serie.max().hour)
    else:
        tope = _entero("ALERTA_MAX_ATRASO_HORAS", 6)
        if atraso > dt.timedelta(hours=tope):
            print(f"El dato viene con más de {tope} horas de atraso: no aviso, "
                  f"porque sería una alerta sobre algo ya pasado.")
            return 0
        objetivo = ultima_hora_completa(serie)
        if objetivo is None:
            return 0
        dia, hora = objetivo

    print(f"Revisando {dia} a las {hora:02d}:00…")

    estado = estado_leer()
    marca = f"{dia.isoformat()}T{hora:02d}"
    if not args.ignorar_estado and estado.get("ultima_hora_avisada") == marca:
        print("Esa hora ya se había avisado. No repito.")
        return 0

    r = armar_resumen(df, dia, hora)
    if r is None:
        print("Esa hora está dentro de lo normal. No hay nada que avisar.")
        return 0

    print(f"PICO: {r['casos']} casos vs {r['habitual']:.0f} habituales "
          f"({r['veces']:.1f}×) · hora {r['posicion']}ª de la racha")

    if not toca_avisar(r["posicion"]):
        cada = max(1, _entero("ALERTA_CADA_N_HORAS", 3))
        print(f"El pico ya se avisó y sigue; el próximo recordatorio va cada "
              f"{cada} horas. No envío.")
        return 0

    asunto_txt = asunto(r)
    html = cuerpo_html(r)
    texto = cuerpo_texto(r)

    if args.prueba:
        ARCHIVO_PRUEBA.write_text(html, encoding="utf-8")
        print("\n--- MODO PRUEBA: no se envió ningún correo ---")
        print(f"Asunto: {asunto_txt}")
        print(f"Iría a: {', '.join(destinos)}")
        print(f"Vista previa: {ARCHIVO_PRUEBA}")
        print("\n" + texto)
        return 0

    if not puede_enviar():
        print("\nHay un pico, pero el correo NO está configurado "
              "(faltan SMTP_USUARIO y SMTP_CLAVE), así que no envío nada.")
        print(f"Asunto que se habría enviado: {asunto_txt}")
        return 0

    try:
        enviar(asunto_txt, html, texto, destinos)
    except Exception as e:
        print(f"ERROR enviando el correo: {e}")
        return 1

    print(f"Correo enviado a {len(destinos)} personas: {', '.join(destinos)}")
    estado_guardar(dia, hora)
    return 0


if __name__ == "__main__":
    sys.exit(main())
