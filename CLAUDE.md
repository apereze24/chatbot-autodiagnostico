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
4. **App (`app.py`, Streamlit):** filtros laterales + botón actualizar, y el
   contenido en **dos pestañas** (`st.tabs`): "Chat" y "Termómetro por hora".
   El historial guarda resultados para no re-llamar la IA en cada rerun.
   Ojo: `st.tabs` renderiza ambas pestañas en cada rerun (son pestañas de
   cliente), así que el dashboard se recalcula siempre; son milisegundos.
   `st.chat_input` va DENTRO de la pestaña del chat (soportado desde Streamlit
   1.42): al anidarlo queda en línea en vez de anclado al pie, que es lo que se
   quiere para que no aparezca flotando sobre el dashboard.
5. **Termómetro (`termometro.py`):** dashboard de la segunda pestaña, con los
   autodiagnósticos por hora del día elegido y alerta cuando el volumen se sale
   de lo normal. Tiene su propio selector de día y hereda los demás filtros de la
   barra lateral (`aplicar_filtros(..., incluir_fecha=False)`), porque siempre
   muestra un día completo hora por hora.
   - Estructura: fila superior (día, cifra del día, semáforo + medidor), fila de
     4 cifras, y abajo el gráfico de 24 horas (2/3) junto al detalle de los picos
     (1/3). `_analizar()` hace el cálculo y `render()` solo presenta.
   - Cada hora muestra su barra Y una marca gris en su valor habitual, así se ve
     hora por hora si el día va por encima o por debajo. La escala incluye lo
     habitual para que la marca siempre quepa; es lineal a propósito (en un día
     de falla masiva el resto del día se ve diminuto, y eso es el mensaje).
   - "Lo habitual" = **mediana** de esa misma hora en los 14 días anteriores
     (mediana y no promedio para que un día de falla masiva no desactive la
     alerta las dos semanas siguientes).
   - Una hora se marca 🔥 si cumple dos condiciones: (1) al menos **el doble** de
     lo habitual de esa hora, con piso de 5 casos —el mínimo es proporcional a
     la hora, no fijo, así la madrugada no queda ciega—; y (2) fuera del ruido
     de esa hora: mediana + 3,5 × max(MAD, √mediana). El piso de raíz cuadrada
     es la clave de la madrugada: donde lo habitual es 1 caso, la MAD vale 0 y
     sin ese piso cualquier 2 dispararía alerta.
   - Frecuencia medida sobre 90 días reales: 65 horas marcadas, alguna alerta
     en 39% de los días. (La versión previa, ≥2,5× con piso fijo de 20, daba 39
     horas / 23% de días pero era ciega en la madrugada.) Para bajar el ruido,
     el dial es `K_DISPERSION` (con 4 → 32% de días).
   - **Por qué pasó:** al marcar una hora, el panel muestra tres repartos de esa
     hora —**causa** (`failure_reason`), **canal** (`source`) y **ciudad**
     (`nombre_ciudad`)— cada uno comparado con su peso habitual a esa misma hora,
     y resalta con ↑ lo que creció. Umbrales: una causa se señala si es ≥50% de
     los casos con ≥10 casos; canal y ciudad, si son ≥40% con ≥5 casos. En todos
     los casos se exige además haber crecido (≥1,5× su peso habitual o +15
     puntos), porque `portal` es el 90% del tráfico y ser mayoría no explica nada.
   - La ciudad es la dimensión que más discrimina: concentración en una ciudad =
     evento de red local; reparto normal = problema transversal del sistema. Ver
     el análisis de los dos picos grandes en `conocimiento.md`.
   - El último día con datos está en curso, así que se compara solo el tramo de
     horas ya transcurrido (si no, un día a medias parecería una caída).

6. **Alerta por correo (`alertas.py` + `.github/workflows/`):** cada hora revisa
   la última hora COMPLETA de datos y, si es un pico, manda correo al equipo de
   CX con el desglose. Corre en **GitHub Actions**, no dentro de la app: una app
   de Streamlit solo se ejecuta cuando alguien tiene la página abierta, así que
   no puede vigilar nada por su cuenta.
   - Usa la misma regla que el dashboard (`analisis.py`), por eso la refactorización.
   - `requirements-alertas.txt` es una lista aparte con solo 3 librerías: la
     alerta no necesita Streamlit ni la IA, y así cada corrida horaria tarda
     ~15 s de instalación en vez de ~90 s (cabe en la capa gratuita).
   - **Fuerza un refresco de Redash** (`ALERTA_REFRESCAR_REDASH=1`). Es
     indispensable: la consulta está programada para recalcularse **una vez al
     día** (05:15 UTC), así que el resultado en caché puede tener 12+ horas de
     atraso. Forzando la corrida el dato llega con ~15 min de atraso, y tarda
     ~25 s. Por lo mismo, el botón "Actualizar datos" de la app también fuerza
     el refresco.
   - Si el dato viene con más de `ALERTA_MAX_ATRASO_HORAS` (6) de atraso, no
     envía: sería avisar de algo ya pasado.
   - Anti-spam: en un evento largo no manda un correo por hora. El primero
     siempre, y después cada `ALERTA_CADA_N_HORAS` (3). El asunto distingue
     "Pico" de "Sigue el pico · 3ª hora seguida".
   - `.alerta_estado.json` recuerda la última hora avisada para no repetir si la
     tarea se relanza a mano; en Actions se conserva con `actions/cache`.
   - Probar sin enviar nada: `python alertas.py --dia 2026-08-21 --hora 8 --prueba`
     (escribe `alerta_prueba.html`). Sin `SMTP_CLAVE` nunca envía.
   - Comprobar credenciales: `python alertas.py --probar-envio --solo-a x@y.com`
     manda un correo corto de confirmación. `--solo-a` existe para no dispararle
     a las 5 personas mientras se configura.
   - **Guía para el usuario en `ALERTA-CORREO.md`** (paso a paso, sin tecnicismos:
     contraseña de aplicación, secrets de GitHub, cómo verificar). Si cambia algo
     de la configuración, actualizar ese archivo también.

**Zona horaria:** Redash entrega `started_at` y compañía en **UTC**;
`redash.py` las pasa a hora de Colombia (UTC−5) al normalizar. Sin eso, el pico
de las 6 p.m. aparecía a las 11 p.m. Se puede ajustar con `HORAS_UTC_A_LOCAL`.

## Configuración (`.env` local / Secrets en Streamlit Cloud)
- IA: `GEMINI_API_KEY` (o `ANTHROPIC_API_KEY`). Opcional `GEMINI_MODEL` / `LLM_PROVIDER`.
- Redash: `REDASH_URL`, `REDASH_QUERY_ID`, `REDASH_API_KEY`.
- Nunca poner claves en el código ni en el chat. `.env` está en `.gitignore`.

## Filtros del chatbot (barra lateral)
Estado del ticket (stages), Canal (Portal/Whatsapp/Sysbrazo), Fecha inicio, Hasta,
Ciudad. Botón "Actualizar". Se detectan por nombre de columna automáticamente
(`buscar_columna`), así que se adaptan a lo que devuelva la consulta de Redash.

## Ejecutar y publicar
- Local, para el usuario: doble clic en **`Abrir chatbot.bat`** (hace el `cd` a la
  carpeta y lanza streamlit; deja una ventana de consola abierta que es el motor).
  Ojo al editar ese .bat: cmd.exe rompe los bloques `if (...)` y los `echo` que
  contengan paréntesis, por eso usa `goto` en vez de bloques.
- Local, por terminal: `.venv\Scripts\streamlit run app.py`
  (`streamlit.exe` no se puede abrir con doble clic: necesita el argumento `run app.py`.)
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
- [x] Fase 2: datos reales vía **API de Redash** (82.623 filas, 29 columnas).
- [x] Filtros ajustados a los valores reales (directriz, estado, canal, ciudad, fecha).
- [x] Termómetro de actividad por hora, con alerta de picos y explicación por
  causa/canal/ciudad, en su propia pestaña.
- [x] Correo de alerta al equipo de CX, corriendo en GitHub Actions cada hora.
  Secrets creados y **envío verificado desde Actions** (24-ago-2026) con
  `modo: probar-envio`. Envía desde una cuenta de Gmail externa con contraseña
  de aplicación, porque Workspace de Fibrazo tiene bloqueadas las contraseñas de
  aplicación en las cuentas de la empresa. **Pendiente**: pedirle a TI una cuenta
  interna o un relay SMTP, y que entre tanto los 5 destinatarios marquen el
  remitente como "no es spam" — un remitente externo automático es candidato a
  filtro.
- [~] **Rutina viva, no tarea cerrada:** el repo es público, así que GitHub
  desactiva el workflow programado si pasa 60 días sin actividad, y la alerta
  dejaría de enviarse EN SILENCIO. Mitigación: editar `MANTENIMIENTO.md` cada 45
  días (una edición = actividad = reloj a cero). El instructivo y la bitácora
  están en ese archivo. Se decidió mantener el repo público a pedido del usuario;
  la alternativa definitiva era hacerlo privado (los privados están exentos de
  esa regla), a costa de consumir ~720 de los 2.000 minutos gratis de Actions.
- La lista de destinatarios NO va en el código (repo público): vive en el secret
  `ALERTA_DESTINATARIOS`. Si falta, `alertas.py` falla en vez de enviar a nadie
  en silencio.
- [ ] Pendiente técnico: `use_container_width` está deprecado en Streamlit
  (reemplazar por `width="stretch"` / `width="content"` en `app.py`).

## Archivos
`app.py` (UI: pestañas + filtros), `redash.py` (fuente de datos),
`analisis.py` (**cálculos y regla de alerta, sin Streamlit**: lo comparten el
dashboard y el correo), `termometro.py` (dashboard por hora, solo presentación),
`alertas.py` (correo de alerta), `ai_analyst.py` (text-to-SQL),
`llm.py` (Gemini/Claude), `data_source.py` (Excel de respaldo),
`autodiagnosticos.xlsx`, `conocimiento.md` (contexto de negocio que lee la IA,
editable por el usuario), `Abrir chatbot.bat` (lanzador para el usuario).
Regla: si se toca la lógica de "¿esta hora es rara?", se toca **solo en
`analisis.py`**, para que la pantalla y el correo no se desincronicen.
Nota: `README.md`, `chatbot.py`, `metrics.py` y `sample_data.py` son de la Fase 1
(prototipo con datos de ejemplo) y ya no los usa la app.
