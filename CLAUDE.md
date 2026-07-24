# CLAUDE.md — Chatbot de Autodiagnóstico

## Qué es
Chatbot de IA, uso interno, que responde **preguntas libres** en español sobre el
proceso de **Autodiagnóstico** (diagnóstico del módem wifi del cliente) con cifras
y gráficos. Usuario (aperez@fibrazo.com) **no técnico** → explicar simple, paso a paso.

## Cómo funciona (arquitectura actual)
1. **Fuente de datos: Redash.** Una consulta ya construida en Redash arma la tabla
   consolidada del autodiagnóstico. El chatbot la trae vía la **API de Redash**
   (`redash.py`), con botón **"Actualizar"** para refrescar bajo demanda.
   Respaldo: si Redash no está configurado, usa `autodiagnosticos.xlsx` (ejemplo).
2. **Cerebro IA (`ai_analyst.py`, text-to-SQL):** la IA lee el esquema real del
   DataFrame (columnas/valores detectados dinámicamente), traduce la pregunta a
   SQL DuckDB de solo lectura, se valida (candado anti-escritura), se ejecuta, y la
   IA redacta la respuesta. El número SIEMPRE sale de los datos; la IA no lo inventa.
3. **Proveedor de IA (`llm.py`, intercambiable):** Google Gemini o Claude, según la
   clave presente. Gemini auto-detecta un modelo disponible en la cuenta.
4. **App (`app.py`, Streamlit):** chat + filtros laterales + botón actualizar. El
   historial guarda resultados para no re-llamar la IA en cada rerun.

## Configuración (`.env` local / Secrets en Streamlit Cloud)
- IA: `GEMINI_API_KEY` (o `ANTHROPIC_API_KEY`). Opcional `GEMINI_MODEL` / `LLM_PROVIDER`.
- Redash: `REDASH_URL`, `REDASH_QUERY_ID`, `REDASH_API_KEY`.
- Nunca poner claves en el código ni en el chat. `.env` está en `.gitignore`.

## Filtros del chatbot (barra lateral)
Estado del ticket (stages), Canal (Portal/Whatsapp/Sysbrazo), Fecha inicio, Hasta,
Ciudad. Botón "Actualizar". Se detectan por nombre de columna automáticamente
(`buscar_columna`), así que se adaptan a lo que devuelva la consulta de Redash.

## Ejecutar y publicar
- Local: `.venv\Scripts\streamlit run app.py`
- Publicado: GitHub `apereze24/chatbot-autodiagnostico` → Streamlit Cloud.

## Contexto del negocio (resumen)
- Canales/orígenes del autodiagnóstico: **Portal, WhatsApp (Botmaker), Sysbrazo**.
  Hallazgo: la tabla base de runs contiene los 3 orígenes (Portal ~66k, WhatsApp
  ~4k, Sysbrazo ~425).
- Resultado del proceso (status del run): finished→Completado, failed→Fallido,
  canceled→Escalado (=generó ticket). Estados ampliados en el tablero real:
  Creado, En curso, Demorado, Finalizado, Fallido, Cancelado, Pausado, Error.
- Si escala, el ticket vive en Odoo/`sysbrazo.odoo_tickets`: `stage` (Solved=
  resuelto), `team` (área: NOC, Instalaciones y Mantenimiento=OPS, NET Operations
  es distinto a NOC), `create_date`/`close_date`, `close_hours` (tiempo resolución).
- Pendiente que definirá la consulta de Redash: para runs fallidos/escalados,
  reflejar si pasó a ticket, qué pasó, cuánto tardó en resolverse y qué equipo lo
  gestionó.

## Estado del proyecto
- [x] Prototipo IA de preguntas libres funcionando (Gemini), publicado en Streamlit.
- [~] Fase 2: conectar a datos reales vía **API de Redash** (en curso: falta que el
  usuario pegue `REDASH_URL`/`QUERY_ID`/`API_KEY` y validar columnas reales).
- [ ] Ajustar filtros/estados a los valores reales que devuelva Redash.

## Archivos
`app.py` (UI+filtros), `redash.py` (fuente de datos), `ai_analyst.py` (text-to-SQL),
`llm.py` (Gemini/Claude), `data_source.py` (Excel de respaldo), `autodiagnosticos.xlsx`.
