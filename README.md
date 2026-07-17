# Chatbot de Autodiagnóstico — Prototipo (Fase 1)

Página web de chat, para uso interno, que responde preguntas sobre el proceso de
**autodiagnóstico** con cifras y gráficos. Esta Fase 1 usa **datos de ejemplo**
(falsos pero realistas) para poder mostrarlo funcionando sin conectar aún las bases.

## ¿Qué hace?

Escribes una pregunta ("¿cuántos autodiagnósticos hubo por canal?") y el chatbot:
1. Entiende la pregunta.
2. Elige la medición correcta (de las 10 definidas).
3. Calcula el resultado sobre los datos.
4. Responde con texto + un gráfico.

Filtros disponibles (barra lateral): **ciudad**, **fecha** y **canal**.

## Cómo ejecutarlo (Windows)

Desde esta carpeta, en la terminal:

```powershell
.venv\Scripts\streamlit run app.py
```

Se abre solo en el navegador (normalmente en http://localhost:8501).
Para detenerlo: `Ctrl + C` en la terminal.

> Si es la primera vez y no existe el entorno `.venv`, créalo así:
> ```powershell
> py -m venv .venv
> .venv\Scripts\python -m pip install -r requirements.txt
> ```

## (Opcional) Activar la IA para preguntas libres

Sin clave de API, el chatbot ya funciona con preguntas directas. Para entender
preguntas totalmente libres, activa la IA de Claude:

1. Copia `.env.example` como `.env`.
2. Pega tu clave en `ANTHROPIC_API_KEY=` (consíguela en https://console.anthropic.com).
3. Vuelve a ejecutar la app.

> Seguridad: el archivo `.env` nunca se sube ni se comparte. Ya está en `.gitignore`.

## Archivos del proyecto

| Archivo | Qué hace |
|---|---|
| `app.py` | La página de chat (interfaz). |
| `chatbot.py` | El "cerebro": entiende la pregunta y elige la medición. |
| `metrics.py` | Las 10 mediciones, cada una como una función. |
| `sample_data.py` | Genera los datos de ejemplo (se reemplaza en Fase 2). |
| `CLAUDE.md` | Contexto completo del proyecto y las fuentes de datos reales. |

## Siguientes fases

- **Fase 2:** conectar a las bases reales (Postgres: sysbrazo, analytics, odoo).
  Solo se reemplaza `sample_data.py` por consultas reales; el resto no cambia.
- **Fase 3:** afinar las 10 mediciones con los datos reales.
- **Fase 4:** sumar Mixpanel (bot y portal).
- **Fase 5:** publicar para la empresa.
