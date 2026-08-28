"""
Mantiene despierta la app de Streamlit Community Cloud.

¿Por qué hace falta un navegador y no un simple "ping"? Porque una petición HTTP
normal a la app dormida devuelve la cáscara HTML de la página con código 200,
pero NO arranca el programa de Python que está detrás. Streamlit solo se
considera "usada" cuando un navegador abre la conexión viva con el servidor. Por
eso aquí se abre de verdad con un navegador sin ventana (Chromium headless).

Cómo decide si hay que reactivarla: no se busca un texto concreto en el botón,
porque ese mensaje ha cambiado entre versiones de Streamlit y quedaría un script
que se rompe en silencio el día que lo vuelvan a cambiar. En vez de eso se mira
lo único que importa: si el contenedor de la app aparece, ya estaba arriba; si no
aparece, se pulsa el botón que haya en la página (en la pantalla de app dormida
no hay otro) y se vuelve a esperar.

Se usa así:
    python mantener_despierta.py https://mi-app.streamlit.app/

Requiere:  pip install playwright  &&  playwright install chromium
(Playwright necesita Python 3.13 o anterior; el workflow usa 3.12.)
"""

import sys

from playwright.sync_api import sync_playwright

# Cuando la app está realmente cargada, existe este contenedor.
SELECTOR_APP = '[data-testid="stAppViewContainer"]'

ESPERA_CORTA = 20_000    # margen para ver si ya estaba arriba
ESPERA_LARGA = 180_000   # despertar de cero puede tardar bastante


def _esta_arriba(pagina, espera: int) -> bool:
    try:
        pagina.wait_for_selector(SELECTOR_APP, timeout=espera)
        return True
    except Exception:
        return False


def despertar(url: str) -> bool:
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        pagina = navegador.new_page()
        try:
            print(f"Abriendo {url}")
            pagina.goto(url, wait_until="domcontentloaded", timeout=60_000)

            if _esta_arriba(pagina, ESPERA_CORTA):
                print("La app ya estaba arriba. Con esta visita se queda despierta.")
                return True

            print("No responde todavía: parece dormida. Busco el botón de reactivar.")
            botones = pagina.locator("button")
            if botones.count() == 0:
                print("No hay ningún botón en la página. No puedo reactivarla.")
                print("Si esto se repite, abre la app a mano y revisa qué muestra.")
                return False

            print(f"Pulsando el botón de la página (hay {botones.count()}).")
            botones.first.click()

            if _esta_arriba(pagina, ESPERA_LARGA):
                print(f"Reactivada. Título de la página: {pagina.title()!r}")
                return True

            print("Pulsé el botón pero la app no acabó de cargar en 3 minutos.")
            return False
        except Exception as e:
            print(f"No pude confirmar que la app quedara arriba: "
                  f"{type(e).__name__}: {e}")
            return False
        finally:
            navegador.close()


if __name__ == "__main__":
    if len(sys.argv) < 2 or not sys.argv[1].startswith("http"):
        print("Falta la dirección de la app.")
        print("Uso: python mantener_despierta.py https://mi-app.streamlit.app/")
        sys.exit(1)
    sys.exit(0 if despertar(sys.argv[1]) else 1)
