"""
Alerta por correo cuando los autodiagnósticos se disparan en una hora.

Revisa cada hora completa de datos que quede pendiente y, si alguna se salió de
lo normal, avisa al equipo con el desglose: cuántos fueron, qué falló, en qué
ciudad y por qué canal entraron. Avisa por Google Chat y/o por correo.

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
import requests
from dotenv import load_dotenv

import analisis
import redash

load_dotenv()

# A quién se le avisa. Deliberadamente VACÍA en el código: este repositorio es
# público, y una lista de correos corporativos a la vista es material para spam y
# phishing dirigido. La lista real vive en el secret ALERTA_DESTINATARIOS de
# GitHub (correos separados por coma), que GitHub nunca muestra.
# Si el secret falta, el programa NO envía a nadie en silencio: falla y lo dice.
DESTINATARIOS_POR_DEFECTO: list[str] = []

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


def hay_destinatarios(destinos: list[str]) -> bool:
    """Comprueba que haya a quién escribirle, y si no, explica cómo arreglarlo.

    Existe para que el peor caso posible no ocurra: que la alerta se crea enviada
    cuando en realidad no le llegó a nadie."""
    if destinos:
        return True
    print("NO HAY DESTINATARIOS, así que no envío nada.")
    print("La lista vive en el secret ALERTA_DESTINATARIOS de GitHub, con los")
    print("correos separados por coma. Revisa que exista y que el nombre esté")
    print("escrito exacto: ALERTA_DESTINATARIOS.")
    return False


def _texto(nombre: str, defecto: str = "") -> str:
    """Lee una variable de entorno tratando el texto vacío como "no está".

    Esto importa de verdad: en GitHub Actions, un secret que no existe NO llega
    ausente, llega como cadena vacía. Con os.environ.get(nombre, defecto) el
    valor por defecto nunca se aplicaba, y el envío fallaba con un servidor
    vacío y un error incomprensible."""
    return os.environ.get(nombre, "").strip() or defecto


def _entero(nombre: str, defecto: int) -> int:
    try:
        return int(_texto(nombre, str(defecto)))
    except ValueError:
        return defecto


def _si(nombre: str) -> bool:
    return os.environ.get(nombre, "").strip() in ("1", "true", "si", "sí")


def _tapado(valor: str, correo: bool = False) -> str:
    """Muestra que un valor llegó, sin revelarlo.

    Se imprime en el registro para poder diagnosticar sin exponer nada: la
    LONGITUD es el dato clave, porque el error más común es pegar la contraseña
    normal en vez de la de aplicación, que tiene exactamente 16 caracteres."""
    if not valor:
        return "FALTA"
    if correo and "@" in valor:
        usuario, dominio = valor.split("@", 1)
        return f"{usuario[:2]}{'*' * max(len(usuario) - 2, 1)}@{dominio}"
    return f"sí, {len(valor)} caracteres"


def diagnostico() -> None:
    """Imprime qué configuración llegó, para no adivinar cuando algo falla.

    Muestra el valor QUE SE VA A USAR, no el que llegó: si un secret viene vacío
    y se aplica el valor por defecto, hay que verlo, porque confundir esas dos
    cosas ya costó una falla difícil de leer."""
    # Lo primero: por dónde va a salir el aviso. Es lo que uno quiere saber al
    # abrir el registro, y antes no aparecía: se podía revisar una corrida
    # entera sin enterarse de si el canal de Chat estaba armado o no.
    print("Canales de aviso:")
    print(f"  {'Google Chat':18s}: "
          + ("configurado" if hay_chat() else "sin configurar (falta CHAT_WEBHOOK_URL)"))
    if puede_enviar():
        cuantos = len(destinatarios())
        print(f"  {'Correo':18s}: configurado, "
              + (f"{cuantos} destinatarios" if cuantos
                 else "PERO SIN DESTINATARIOS (falta ALERTA_DESTINATARIOS)"))
    else:
        print(f"  {'Correo':18s}: sin configurar")
    if not hay_chat() and not puede_enviar():
        print("  >>> No hay ningún canal: si aparece un pico, NO se podrá avisar.")
    print()

    print("Configuración detectada:")
    # El servidor y el puerto no son secretos: se muestran completos porque un
    # error de dedo ahí es casi imposible de ver de otro modo.
    print(f"  {'SMTP_HOST':18s}: {_texto('SMTP_HOST', 'smtp.gmail.com')}"
          f"{'' if _texto('SMTP_HOST') else '   (no configurado, se usa este)'}")
    print(f"  {'SMTP_PORT':18s}: {_entero('SMTP_PORT', 587)}"
          f"{'' if _texto('SMTP_PORT') else '   (no configurado, se usa este)'}")
    for nombre, correo in (("SMTP_USUARIO", True), ("SMTP_CLAVE", False),
                           ("REDASH_URL", False), ("REDASH_API_KEY", False)):
        print(f"  {nombre:18s}: {_tapado(_texto(nombre), correo)}")
    print(f"  {'REDASH_QUERY_ID':18s}: {_tapado(_texto('REDASH_QUERY_ID'))}")
    # Con qué dirección sale el correo. Se muestra completa (no es un secreto) y
    # es importante verla: en los servicios de correo transaccional el usuario de
    # conexión NO es la dirección del remitente, y si se deja igual el proveedor
    # rechaza el envío por remitente no verificado.
    remitente = _texto("ALERTA_REMITENTE")
    if remitente:
        print(f"  {'remitente (de:)':18s}: {remitente}")
    else:
        print(f"  {'remitente (de:)':18s}: {_tapado(_texto('SMTP_USUARIO'), True)}"
              f"   (ALERTA_REMITENTE no está, se usa SMTP_USUARIO)")
    print(f"  {'destinatarios':18s}: {len(destinatarios())}")
    print()


def puede_enviar() -> bool:
    """Si hay con qué enviar. Hay dos formas válidas:

    1. Usuario y clave (Gmail con contraseña de aplicación, Office 365, etc.).
    2. Un relay interno de la empresa que autoriza por IP y no pide clave; en ese
       caso basta el servidor y SMTP_SIN_LOGIN=1."""
    if _si("SMTP_SIN_LOGIN"):
        return bool(_texto("SMTP_HOST"))
    return bool(_texto("SMTP_USUARIO") and _texto("SMTP_CLAVE"))


# --- Qué hora revisar --------------------------------------------------------
def ultima_hora_completa(serie_fechas: pd.Series) -> pd.Timestamp | None:
    """La última hora que ya terminó y de la que hay datos completos.

    Si el último dato es de las 08:20, la última hora completa es la de las 07:00:
    la de las 08:00 todavía está a medias y avisaría con la mitad de los casos."""
    if serie_fechas.empty:
        return None
    return serie_fechas.max().floor("h") - pd.Timedelta(hours=1)


def horas_pendientes(serie_fechas: pd.Series, estado: dict) -> list[pd.Timestamp]:
    """Todas las horas completas que faltan por revisar, de la más vieja a la más nueva.

    Antes se revisaba SOLO la última hora completa, y eso dejaba un hueco por el
    que se cayó una alerta real (el pico del 28-ago-2026 a las 06:00): el atraso
    con que llegan los datos de Redash varía entre corridas, así que la corrida de
    las 07:10 miró las 05:00 y la de las 08:10 ya miraba las 07:00. Las 06:00 no
    las revisó nadie. Lo mismo pasaría si GitHub retrasa o se salta una corrida,
    que es algo que sí ocurre.

    Ahora se avanza sobre un puntero guardado, así que ninguna hora se pierde y
    una corrida se pone al día con las que quedaron atrás."""
    fin = ultima_hora_completa(serie_fechas)
    if fin is None:
        return []

    # Nunca mirar más atrás que la ventana de atraso aceptable: si algo quedó
    # sin revisar por más tiempo que eso, avisarlo ahora sería avisar de algo
    # ya pasado.
    ventana = max(1, _entero("ALERTA_MAX_ATRASO_HORAS", 6))
    mas_viejo = fin - pd.Timedelta(hours=ventana - 1)

    inicio = None
    guardado = estado.get("ultima_hora_revisada")
    if guardado:
        try:
            inicio = pd.Timestamp(guardado) + pd.Timedelta(hours=1)
        except Exception:
            inicio = None
    if inicio is None or inicio > fin:
        # Sin puntero (primera corrida, o caché perdida): solo la última hora.
        # Así una instalación nueva no dispara una ráfaga de avisos viejos.
        inicio = fin
    inicio = max(inicio, mas_viejo)

    return list(pd.date_range(inicio, fin, freq="h"))


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


def estado_guardar(hasta: pd.Timestamp) -> None:
    """Recuerda hasta qué hora se revisó, para que la próxima corrida siga desde ahí."""
    try:
        ARCHIVO_ESTADO.write_text(
            json.dumps({"ultima_hora_revisada": hasta.isoformat()}),
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
    veces_txt = veces_en_palabras(r["veces"])

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


# --- Envío por Google Chat ---------------------------------------------------
# Se agregó después de que Google bloqueara tres veces el envío por Gmail: una
# cuenta personal no se puede usar para envío automático, y no hay configuración
# que lo arregle. Un webhook de Chat es lo contrario: es la vía que Google
# provee justamente para que un programa publique mensajes. No necesita
# credenciales de correo, ni remitente verificado, ni DNS, no puede caer en
# spam, y todo queda dentro del Workspace de la empresa.
def hay_chat() -> bool:
    """Si hay un espacio de Chat configurado. Los webhooks reales de Google son
    https; se acepta http para poder probar contra un servidor local."""
    return _texto("CHAT_WEBHOOK_URL").startswith("http")


def veces_en_palabras(veces: float | None) -> str:
    """«3,8 veces lo habitual». Con coma decimal, y sin el ,0 cuando es redondo."""
    if not veces:
        return "por encima de lo habitual"
    numero = f"{veces:.1f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{numero} veces lo habitual"


def _umbrales(clave: str) -> tuple[float, int]:
    """Cuánto tiene que pesar algo para señalarlo, según la dimensión.
    A una causa se le exige mayoría; a una ciudad o un canal, concentración."""
    if clave == "causa":
        return analisis.PCT_DOMINANTE, analisis.MINIMO_CASOS_CAUSA
    return analisis.PCT_CONCENTRADO, analisis.MINIMO_CASOS_DIM


def mensaje_chat(r: dict) -> str:
    """El aviso en el formato de Google Chat (*negrita*, viñetas, enlaces)."""
    veces = veces_en_palabras(r["veces"])
    cabeza = (f"🔥 *Sigue el pico · {r['posicion']}ª hora seguida*"
              if r["posicion"] > 1 else "🔥 *Pico de autodiagnósticos*")

    lineas = [
        cabeza,
        f"*{r['hora']:02d}:00 a {r['hora']:02d}:59* · "
        f"{analisis.fecha_larga(r['dia'])}",
        "",
        f"*{r['casos']} autodiagnósticos* en esa hora — {veces} "
        f"({r['habitual']:.0f} en un día normal a esa hora).",
        "",
        interpretacion(r),
        "",
        "*Qué está pasando*",
    ]
    for clave in ("causa", "ciudad", "canal"):
        items = r["perfil"]["repartos"].get(clave, [])
        if not items:
            continue
        it = items[0]
        valor = (analisis.en_palabras(it["valor"]) if clave == "causa"
                 else analisis.bonito(it["valor"]))
        hab = ("no aparecía a esta hora" if it["pct_habitual"] is None
               else f"habitual {it['pct_habitual']:.0f}%")
        marca = " ⬆️" if analisis.crecio(it, *_umbrales(clave)) else ""
        lineas.append(f"• {ETIQUETAS[clave]}: *{valor}* — {it['pct']:.0f}% "
                      f"de los casos ({hab}){marca}")

    lineas += [
        "",
        "*El día hasta ahora*",
        f"{r['dia_total']} autodiagnósticos hasta las {r['hora']:02d}:59, cuando "
        f"un día normal llevaría {r['dia_habitual']:.0f} "
        f"({r['dia_nivel']['desvio'] * 100:+.0f}%).",
        f"Horas en alerta hoy: "
        f"{', '.join(f'{h:02d}:00' for h in r['dia_picos'])}.",
    ]
    url = _texto("ALERTA_URL_APP")
    if url:
        lineas += ["", f"<{url}|Ver el detalle en el termómetro>"]
    return "\n".join(lineas)


def enviar_chat(texto: str) -> None:
    """Publica un mensaje en el espacio de Chat. Lanza excepción si falla."""
    r = requests.post(_texto("CHAT_WEBHOOK_URL"), json={"text": texto}, timeout=30)
    r.raise_for_status()


# --- Envío -------------------------------------------------------------------
def enviar(asunto_txt: str, html: str, texto: str, destinos: list[str]) -> None:
    """Manda el correo. Aguanta las tres formas que suele haber en una empresa:
    Gmail/Office con usuario y clave, un relay interno sin clave (SMTP_SIN_LOGIN),
    y un relay interno sin cifrado en el puerto 25 (SMTP_SIN_TLS)."""
    host = _texto("SMTP_HOST", "smtp.gmail.com")
    puerto = _entero("SMTP_PORT", 587)
    usuario = _texto("SMTP_USUARIO")
    clave = _texto("SMTP_CLAVE")
    remitente = _texto("ALERTA_REMITENTE", usuario)
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


def mensaje_chat_de_prueba() -> str:
    """La versión corta, para comprobar que el webhook del espacio funciona."""
    cada = max(1, _entero("ALERTA_CADA_N_HORAS", 3))
    return "\n".join([
        "✅ *La alerta quedó configurada*",
        "",
        "Si ves este mensaje, el aviso por Chat funciona.",
        "",
        "*Este es el único mensaje que llega sin que esté pasando nada.* De aquí "
        "en adelante solo se publica cuando hay algo que mirar: cuando en una "
        "hora se ejecuten el doble o más de los autodiagnósticos que suele haber "
        f"a esa misma hora (mediana de los últimos {analisis.DIAS_BASE} días) y "
        "además se salga de su rango normal.",
        "",
        "Para dar una idea de cada cuánto: mirando los últimos 90 días habrían "
        "salido 57 avisos, y en 6 de cada 10 días no habría llegado ninguno.",
        "",
        "Cada aviso trae cuántos fueron, qué falla predominó, *en qué ciudad* se "
        "concentró y por qué canal entraron.",
        "",
        f"Si un pico se alarga, el aviso se repite cada {cada} horas, no cada hora.",
    ])


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

    diagnostico()

    destinos = ([c.strip() for c in args.solo_a.replace(";", ",").split(",")
                 if c.strip()] if args.solo_a else destinatarios())

    if args.probar_envio:
        # Prueba TODOS los canales configurados, no solo el correo: si no, no
        # habría forma de comprobar el webhook de Chat sin esperar un pico real.
        resultados: dict[str, bool] = {}

        if hay_chat():
            try:
                enviar_chat(mensaje_chat_de_prueba())
                resultados["Chat"] = True
                print("Mensaje de prueba publicado en el espacio de Google Chat.")
            except Exception as e:
                resultados["Chat"] = False
                print(f"ERROR publicando en Google Chat: {type(e).__name__}: {e}")
                print("Revisa que CHAT_WEBHOOK_URL sea la URL completa que dio "
                      "Google, sin recortar.")

        if puede_enviar() and hay_destinatarios(destinos):
            asunto_txt, html, texto = correo_de_prueba()
            try:
                enviar(asunto_txt, html, texto, destinos)
                resultados["correo"] = True
                print(f"Correo de prueba enviado a: {', '.join(destinos)}")
            except Exception as e:
                resultados["correo"] = False
                print(f"ERROR enviando el correo de prueba: "
                      f"{type(e).__name__}: {e}")
                print("Las causas más comunes, en orden:")
                print("  1. La cuenta no permite envío automático. Una cuenta "
                      "personal de Gmail NO sirve para esto.")
                print("  2. La clave no es una contraseña de aplicación.")
                print("  3. El servidor y el puerto no son los del proveedor.")
                print("  4. SMTP_USUARIO no es el usuario que dio el proveedor.")
        elif puede_enviar():
            resultados["correo"] = False

        if not resultados:
            print("No hay ningún canal configurado: ni Chat (CHAT_WEBHOOK_URL) "
                  "ni correo (SMTP_USUARIO y SMTP_CLAVE).")
            return 1
        return 0 if any(resultados.values()) else 1

    forzado = bool(args.dia or args.hora is not None)
    # Con _texto y no con os.environ.get: si alguien crea el secret vacío, el
    # refresco se apagaría en silencio y la alerta quedaría mirando datos de ayer.
    refrescar = _texto("ALERTA_REFRESCAR_REDASH", "1") == "1" and not forzado

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

    estado = {} if args.ignorar_estado else estado_leer()

    if forzado:
        dia = (dt.date.fromisoformat(args.dia) if args.dia else serie.max().date())
        hora = args.hora if args.hora is not None else int(serie.max().hour)
        pendientes = [pd.Timestamp(dia) + pd.Timedelta(hours=hora)]
    else:
        tope = _entero("ALERTA_MAX_ATRASO_HORAS", 6)
        if atraso > dt.timedelta(hours=tope):
            print(f"El dato viene con más de {tope} horas de atraso: no aviso, "
                  f"porque sería una alerta sobre algo ya pasado.")
            return 0
        pendientes = horas_pendientes(serie, estado)

    if not pendientes:
        print("No hay horas nuevas por revisar.")
        return 0

    print("Horas por revisar: "
          + ", ".join(t.strftime("%d/%m %H:00") for t in pendientes))

    hubo_fallo = False
    ultima_ok = None
    for momento in pendientes:
        print()
        resultado = revisar_hora(df, momento.date(), int(momento.hour),
                                 destinos, args)
        if resultado == "fallo":
            # No se avanza el puntero: así la próxima corrida vuelve a intentar
            # esta hora en vez de dejar el aviso perdido.
            hubo_fallo = True
            break
        ultima_ok = momento

    if ultima_ok is not None and not forzado and not args.prueba:
        estado_guardar(ultima_ok)

    return 1 if hubo_fallo else 0


def revisar_hora(df: pd.DataFrame, dia: dt.date, hora: int,
                 destinos: list[str], args) -> str:
    """Revisa UNA hora y avisa si hace falta.

    Devuelve "normal" si no había nada que avisar o no tocaba, "avisado" si el
    aviso salió por algún canal, y "fallo" si había que avisar y ningún canal
    pudo entregarlo."""
    print(f"Revisando {dia} a las {hora:02d}:00…")

    r = armar_resumen(df, dia, hora)
    if r is None:
        print("  Dentro de lo normal. No hay nada que avisar.")
        return "normal"

    print(f"  PICO: {r['casos']} casos vs {r['habitual']:.0f} habituales "
          f"({r['veces']:.1f}×) · hora {r['posicion']}ª de la racha")

    if not toca_avisar(r["posicion"]):
        cada = max(1, _entero("ALERTA_CADA_N_HORAS", 3))
        print(f"  El pico ya se avisó y sigue; el próximo recordatorio va cada "
              f"{cada} horas. No envío.")
        return "normal"

    asunto_txt = asunto(r)
    html = cuerpo_html(r)
    texto = cuerpo_texto(r)

    if args.prueba:
        ARCHIVO_PRUEBA.write_text(html, encoding="utf-8")
        print("\n--- MODO PRUEBA: no se envió ni publicó nada ---")
        print(f"Asunto: {asunto_txt}")
        print(f"Iría a: {', '.join(destinos) or '(sin destinatarios)'}")
        print(f"Vista previa del correo: {ARCHIVO_PRUEBA}")
        print("\n" + texto)
        print("\n--- Y así se vería en Google Chat ---\n")
        print(mensaje_chat(r))
        return "normal"

    # --- Avisar por todos los canales configurados ---
    # Los canales son independientes a propósito: si uno se cae, el otro sigue
    # avisando. Basta con que UNO entregue para que el equipo se haya enterado,
    # que es lo único que de verdad importa.
    resultados: dict[str, bool] = {}

    if hay_chat():
        try:
            enviar_chat(mensaje_chat(r))
            resultados["Chat"] = True
            print("Publicado en el espacio de Google Chat.")
        except Exception as e:
            resultados["Chat"] = False
            print(f"ERROR publicando en Google Chat: {type(e).__name__}: {e}")

    if puede_enviar():
        if not hay_destinatarios(destinos):
            resultados["correo"] = False
        else:
            try:
                enviar(asunto_txt, html, texto, destinos)
                resultados["correo"] = True
                print(f"Correo enviado a {len(destinos)} personas: "
                      f"{', '.join(destinos)}")
            except Exception as e:
                resultados["correo"] = False
                print(f"ERROR enviando el correo: {type(e).__name__}: {e}")
                print("Causas más comunes: la clave no es una contraseña de "
                      "aplicación, la cuenta no permite envío automático, o el "
                      "servidor y el puerto no corresponden al proveedor.")

    if not resultados:
        print("\nHay un pico, pero NO hay ningún canal configurado: ni Chat "
              "(CHAT_WEBHOOK_URL) ni correo (SMTP_USUARIO y SMTP_CLAVE).")
        print(f"Asunto que se habría enviado: {asunto_txt}")
        return "fallo"

    entregaron = [c for c, ok in resultados.items() if ok]
    fallaron = [c for c, ok in resultados.items() if not ok]

    if entregaron:
        if fallaron:
            # El aviso llegó, así que la corrida NO falla: fallarla cada hora
            # convertiría la notificación de GitHub en ruido. Pero el canal roto
            # queda dicho en el registro.
            print(f"\nAVISO: el pico se avisó por {', '.join(entregaron)}, pero "
                  f"{', '.join(fallaron)} falló. Conviene revisar ese canal.")
        return 0

    # Ningún canal entregó: se grita con todas las letras, porque la corrida
    # falla y GitHub le escribe al dueño del repositorio. Quien lea ese aviso
    # tiene que entender de inmediato que se perdió una alerta real.
    print()
    print("=" * 70)
    print(f"OJO: EL PICO DE LAS {hora:02d}:00 NO SE AVISÓ A NADIE.")
    print(f"     {r['casos']} autodiagnósticos contra {r['habitual']:.0f} "
          f"habituales. Nadie del equipo lo sabe.")
    print(f"     Canales que fallaron: {', '.join(fallaron)}.")
    print("     Revísalos y, si hace falta, avisa a mano mientras se arregla.")
    print("=" * 70)
    return "fallo"


if __name__ == "__main__":
    sys.exit(main())
