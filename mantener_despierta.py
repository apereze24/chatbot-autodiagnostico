"""
Mantiene despierta la app de Streamlit Community Cloud.

¿Por qué hace falta un navegador y no un simple "ping"? Porque una petición HTTP
normal a la app dormida devuelve la cáscara HTML de la página con código 200,
pero NO arranca el programa de Python que está detrás. Streamlit solo se
considera "usada" cuando un navegador abre la conexión viva con el servidor. Por
eso aquí se abre de verdad con un navegador sin ventana (Chromium headless).

Si la app está dormida, la página muestra un botón para reactivarla; el programa
lo busca y lo pulsa. Después espera a que aparezca el contenedor de la app, que
es la señal de que quedó realmente arriba.

Se usa así:
    python mantener_despierta.py https://mi-app.streamlit.app/

Requiere:  pip install playwright  &&  playwright install chromium
"""

import sys

from playwright.sync_api import sync_playwright

# Textos con los que Streamlit ofrece reactivar una app dormida. Se prueban
# varios porque el mensaje ha cambiado entre versiones.
TEXTOS_DESPERTAR = [
    "get this app back up",
    "Yes, get this app back up!",
    "back up",
]

# Cuando la app está realmente cargada, existe este contenedor.
SELECTOR_APP = '[data-testid="stAppViewContainer"]'


def despertar(url: str) -> bool:
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        pagina = navegador.new_page()
        try:
            print(f"Abriendo {url}")
            pagina.goto(url, wait_until="domcontentloaded", timeout=60_000)

            # Si está dormida, pulsar el botón de reactivar.
            for texto in TEXTOS_DESPERTAR:
                boton = pagina.get_by_text(texto, exact=False)
                if boton.count():
                    print(f"La app estaba dormida. Pulsando «{texto}».")
                    boton.first.click()
                    break
            else:
                print("No aparece el botón de reactivar: la app ya estaba arriba.")

            # Esperar a que el programa de Python realmente responda.
            pagina.wait_for_selector(SELECTOR_APP, timeout=180_000)
            titulo = pagina.title()
            print(f"App arriba y respondiendo. Título de la página: {titulo!r}")
            return True
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
