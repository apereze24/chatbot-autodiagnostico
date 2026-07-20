# CLAUDE.md — Proyecto Chatbot de Autodiagnóstico

## Agente: Creador de Chatbots con IA

Actúa como un desarrollador especializado en crear chatbots con IA que responden
preguntas basándose en bases de datos (RAG / consultas estructuradas). Diseña e
implementa estas soluciones como páginas web para uso interno dentro de compañías,
priorizando una interfaz simple, respuestas precisas basadas en los datos disponibles,
y facilidad de despliegue/mantenimiento en un entorno corporativo.

**Nota sobre el usuario:** No es muy técnico. Explicar el paso a paso de forma sencilla
y clara durante todo el desarrollo del proyecto.

---

## Contexto del negocio: ¿Qué es el Autodiagnóstico?

Proceso que diagnostica el módem de wifi en el hogar del cliente. Identifica el estado
del router: si replica wifi, si tiene luz roja, o si definitivamente no funciona.

### Canales (3)
1. **Portal Web** — El cliente entra al portal "Mi Fibrazo", se loguea y ejecuta el
   autodiagnóstico, que arroja un resultado según el estado del módem.
2. **Bot** — Línea de WhatsApp donde el cliente interactúa de forma autónoma con un bot
   hasta llegar a la instancia de hacer un autodiagnóstico.
3. **Sysbrazo** — El autodiagnóstico lo hace un agente asesor humano desde el CRM,
   cuando el cliente (vía bot) pide hablar con un asesor por fallas de internet, o por
   insistencia del cliente. Da mayor confianza al cliente.

> Diagrama del flujo: archivo **"Flujo Autodiagnóstico"** (pendiente de agregar).

---

## Mediciones requeridas

1. Nº de clientes que piden soporte de autodiagnóstico (los que realizan el proceso).
2. Nº de clientes por canal (Portal, Bot, Sysbrazo).
3. Nº de clientes por ciudad.
4. Nº de clientes por distribución horaria (horas, días de la semana).
5. Tiempo de resolución por funnel (tiempo de resolución por funnel, tiempo de corte de
   drop, tiempo del proceso sin retraso/sin problemas, tiempo de resolución de tickets).
6. Tipo de ticket/resolución: de los que entraron al proceso, cuántos terminaron en
   **Resuelto**, **NOC**, **OPS**, y ¿con qué tipo de cierre quedaron resueltos?
7. ¿Cuántos clientes hicieron X autodiagnósticos en X tiempo y concluyó como resuelto?
   ¿Por qué siguen haciéndolo?
8. Porcentaje de autodiagnósticos resueltos en X tiempo, reflejado en percentiles
   (P10, P20, P30, ... P70, P80, P90).
9. Reopen de fallidos: de los clientes con resultado "error", ¿cuántos repiten el
   proceso? Con temporalidad de reopen de 24, 48 y 72h.
10. Cantidad de autodiagnósticos por hora y por ciudad.

### Filtros transversales
- Ciudad
- Fecha (semana y mes)
- Canal (Bot, Portal, Sysbrazo)

---

## Fuentes de información

### Bot → Mixpanel
Archivo **`auto-diagnostic-mixpanel.md`** (pendiente): eventos trackeables del bot.

### Portal → Mixpanel
Archivo **`mixpanel-autodiagnostico-dashboard-guide.md`** (pendiente): eventos del portal.

### Sysbrazo → Redash / Postgres

**`sysbrazo.auto_diagnostic_run_logs`**
- `id` BIGINT — recuento de filas.
- `run_id` BIGINT — ID único del proceso.
- `level` VARCHAR — si el autodiagnóstico tuvo error o no.
- `message` TEXT — paso del proceso (executing step, success step, failed, ...).
- `context` JSON — paso específico. Ej: `{"step":"initializing","data":{"message":"Initialization completed"}}`.
- `created_at` / `updated_at` TIMESTAMP.

**`sysbrazo.auto_diagnostic_run_steps`**
- `id` BIGINT — recuento de filas.
- `run_id` BIGINT — ID único del proceso.
- `step_number` INTEGER — número del paso en el flujo.
- `step_name` VARCHAR — nombre del paso.
- `status` VARCHAR — éxito, fallido, cancelado, etc.
- `details` JSON — qué sucedió en ese evento.
- `created_at` / `updated_at` TIMESTAMP.

**`sysbrazo.auto_diagnostic_runs`** (tabla clave: muestra el flujo completo del cliente)
- `id` BIGINT — recuento de filas.
- `client_id` BIGINT — identifica al cliente.
- `user_id` BIGINT — id de usuario (en ejemplos aparece null; validar).
- `status` VARCHAR — `finished`, `failed`, `canceled`.
- `started_at` / `finished_at` TIMESTAMP.
- `data` JSON — todos los pasos que recorrió el cliente y causas de falla.
- `created_at` / `updated_at` TIMESTAMP.
- Nota: `started_at`/`finished_at` coinciden con `created_at`/`updated_at`.
- `status = 'canceled'` genera un ticket. Ejemplo de respuesta:
  `{"reason":"CLIENT_HAS_OPEN_INCIDENT","source":"odoo","context":{"ticket_id":253996,"ticket_name":"Autodiagnostico","ticket_ref":"257970"}}`
  → Extraer el **`ticket_ref`** (ej. `257970`). Idealmente pedir a Data una columna
  `ticket_ref` con solo el número, para unir con `odoo.helpdesk_ticket`.

### Odoo (trazabilidad de resolución de tickets)
El `ticket_ref` conecta con `odoo.helpdesk_ticket`. Descripción completa de tablas en
archivo **`Tablas_Odoo`** (pendiente de agregar). Campos confirmados con datos reales
(2026-07-10):

- `odoo.helpdesk_ticket.stage_id` → `odoo.helpdesk_stage.id/name` (alias `stage_name`).
  Valores reales: Solved (82.241), New (7.612), In Progress (201), null (47),
  Ticket para desarrollo (24), Backlog (21), Pruebas con usuario/UAT (9),
  Análisis de requisitos (4).
  **`stage_name = 'Solved'` = ticket resuelto** (estado final exitoso). El resto son
  intermedios o residuales de un flujo de desarrollo que no aplica aquí.
- `odoo.helpdesk_ticket.team_id` → `odoo.helpdesk_team.id/name` (alias `team_name`).
  Valores reales y clasificación acordada:
  - `NOC` → categoría **NOC**
  - `Instalaciones y Mantenimiento` → categoría **OPS**
  - `NET Operations` (706 tickets) → **CONFIRMADO: NO es lo mismo que NOC**, es un
    equipo distinto. Queda como su propia categoría "NET Operations".
  - Resto (Planta externa, Customer Experience/CX, Planta Interna, PQRS, Marketing,
    Equipo de Ingeniería, null) → categoría **Otro** (o **CX** aparte si se quiere
    reportar solo ese equipo).
- `odoo.helpdesk_ticket.create_date` / `close_date` — timestamps de creación y cierre.
- `odoo.helpdesk_ticket.close_hours` — tiempo de resolución en horas, **ya calculado
  por Odoo**. Verificado: completo y confiable para tickets `Solved` (0 sin dato,
  promedio 31.4h). En tickets no resueltos (`New`, `In Progress`) viene en **0**, no
  vacío → **siempre filtrar `stage_name = 'Solved'`** al calcular tiempos de
  resolución (pregunta 8), o los ceros distorsionan los percentiles hacia abajo.
- `odoo.helpdesk_ticket.first_response_hours` — tiempo hasta la primera respuesta
  (disponible si se quiere medir esa métrica aparte).
- **Motivo de cierre:** `odoo.helpdesk_ticket.cierre_motivo_id` → `odoo.fbz_helpdesk_motivo.id/name`,
  filtrando `fbz_helpdesk_motivo.tipo = 'cierre'` (esa tabla mezcla motivos de
  apertura y de cierre en la misma tabla, distinguidos por la columna `tipo`).
  Pendiente ver valores reales de `name` para tickets de cierre (correr GROUP BY).
- **Definición de "resuelto" para la pregunta 7 (clientes repetidores):** un
  intento cuenta como resuelto si `sysbrazo.auto_diagnostic_runs.status = 'finished'`
  **o** si generó un ticket que quedó `stage_name = 'Solved'` en Odoo (confirmado
  2026-07-10, ambos casos cuentan).

**Campo de unión confirmado (2026-07-10):** `sysbrazo.auto_diagnostic_runs.data
->'context'->>'ticket_ref'` (texto, ej. `"257970"`) = `odoo.helpdesk_ticket.ticket_ref`
(numérico, ej. `257970`). Al unir hay que convertir tipos (texto ↔ número).

### Datos del cliente → analytics

**`analytics.client`**
- `client_id`, `gaiia_id`, `client_type` (persona/empresa), `first_name`, `last_name`,
  `commercial_name`, `document_type_id`, `document_id`, `email`,
  `phone_1_prefix`, `phone_1`, `phone_2_prefix`, `phone_2`, `person_type`.

**`analytics.client_address`**
- `client_id`, `stratum_number` (estrato), `zone_id`, `address`, `postal_code`,
  `neighborhood`, `city_id`, `locality` (ciudad), `country`, `lat_long`.

---

## Decisiones de alcance (2026-07-10)
- **Tipo de solución:** Chatbot en lenguaje natural (chat web: escribes preguntas,
  responde con texto + gráficos consultando los datos).
- **Datos:** Conexión directa a las bases (Postgres para sysbrazo/analytics/odoo;
  Mixpanel vía su API para bot/portal).
- **Despliegue:** Compartido en la empresa (accesible por otras personas vía enlace/
  servidor interno).
- **Fase 2 — método de conexión confirmado:** conexión directa a Postgres (no vía
  API de Redash). Se necesitan credenciales: host, puerto, nombre de BD, usuario,
  contraseña — guardadas SIEMPRE en `.env` (nunca en el chat ni en el código).
- **Nota de alcance de canal:** las consultas SQL directas solo cubren el canal
  Sysbrazo (tablas en Postgres). Los canales Bot y Portal viven en Mixpanel y se
  integran en la Fase 4 (API distinta, no SQL). Hasta entonces, la métrica
  "por_canal" en datos reales solo tendrá el dato de Sysbrazo.

## Arquitectura propuesta (a confirmar)
- **App:** Streamlit (Python) — chat web sencillo, conecta fácil a Postgres, renderiza
  gráficos, fácil de compartir internamente.
- **Cerebro:** Claude API (traduce la pregunta en lenguaje natural → consulta de datos).
- **Enfoque híbrido recomendado:** consultas pre-validadas para las 10 mediciones
  conocidas (confiable) + texto-a-SQL libre para preguntas ad-hoc (flexible).
- **Credenciales:** en variables de entorno / archivo de configuración local, NUNCA en
  el código ni en el chat.

## Estado del proyecto
- Nota: los archivos `Flujo Autodiagnóstico`, `auto-diagnostic-mixpanel.md`,
  `mixpanel-autodiagnostico-dashboard-guide.md` y `Tablas_Odoo` NO existen en la
  carpeta; fueron mencionados solo como contexto. Pedir su contenido cuando se necesite.
- [x] Arquitectura confirmada: Streamlit + Claude, enfoque híbrido.
- [x] **Fase 1 COMPLETA (2026-07-10):** prototipo funcionando con datos de ejemplo.
      Python 3.14 + entorno `.venv`. Archivos: `app.py`, `chatbot.py`, `metrics.py`,
      `sample_data.py`, `requirements.txt`, `.env.example`, `README.md`.
      Ejecutar: `.venv\Scripts\streamlit run app.py`. Verificado: 10 métricas OK,
      enrutador por palabras OK, servidor arranca (health 200) sin errores.
- [x] **Fase 2 — consultas SQL redactadas (2026-07-10):** las 10 preguntas tienen
      su archivo `.sql` en la carpeta `queries/` (ver `queries/README.md`).
      Pendiente: probarlas contra la base real (aún sin credenciales) y resolver
      3 dudas de negocio anotadas ahí (tipo de cierre, NET Operations vs NOC,
      definición de "resuelto" en la pregunta 7).
- [ ] Fase 2: obtener credenciales de conexión (host/puerto/BD/usuario/contraseña)
      de forma segura y construir el módulo de conexión (`db.py`) que reemplaza
      `sample_data.py` por consultas reales a Postgres.
- [ ] Fase 3: afinar las 10 mediciones con datos reales.
- [ ] Fase 4: sumar Mixpanel (bot y portal). Fase 5: publicar para la empresa.

### Modo IA de preguntas libres (2026-07-20)
- Objetivo del usuario: chatbot que entienda preguntas LIBRES sobre una fuente de
  datos, no una lista predeterminada. Se agregó dataset de ejemplo
  `autodiagnosticos.xlsx` (5.000 filas, mayo–jun 2026; canales Sysbrazo/Portal
  web/Botmaker; resultados Completado ok/Escalado/Fallido; áreas Customer/
  Operaciones/NOC; estados Abierto/En Gestión/Solucionado; 995 con ticket).
- Arquitectura (text-to-SQL): `data_source.py` carga y limpia el Excel;
  `ai_analyst.py` = (1) Claude traduce la pregunta a SQL DuckDB con
  `messages.parse` (structured output Pydantic), (2) se valida que sea solo lectura
  y se ejecuta en DuckDB con `enable_external_access=false`, (3) Claude redacta la
  respuesta en español desde el resultado. `app.py` reescrito a chat IA-first; el
  historial guarda resultados para NO re-llamar la IA en cada rerun.
- Requiere `ANTHROPIC_API_KEY` (local: `.env`; Streamlit Cloud: Secrets).
- Publicado en GitHub `apereze24/chatbot-autodiagnostico` (repo público) +
  Streamlit Cloud. Verificado: validador de SQL bloquea DROP/DELETE/read_csv;
  ejecutor OK; app arranca sin errores (health 200). No se probó la llamada real
  a Claude por falta de clave en el entorno de desarrollo.
- **Ambigüedad de datos pendiente:** la columna "Tiempo que tardó" está guardada
  como HH:MM:SS y al interpretarla literalmente da duraciones de hasta ~10h
  (promedios: Completado ok ~299 min, Escalado ~486 min). El usuario la describió
  como "minutos y segundos" → puede que la intención real sea MM:SS. Confirmar.

### Detalle técnico Fase 1
- La IA de Claude es OPCIONAL: sin `ANTHROPIC_API_KEY` funciona con enrutador por
  palabras clave; con la clave, entiende preguntas libres (modelo por defecto
  `claude-opus-4-8`, configurable con `CLAUDE_MODEL`). El número SIEMPRE lo calcula
  `metrics.py`; la IA solo elige la medición y los filtros.
- Datos de ejemplo: ~4000 runs, ~1162 clientes, 8 ciudades, 3 canales, ~3 meses.
