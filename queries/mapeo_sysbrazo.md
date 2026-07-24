# Mapeo: tabla objetivo (canal Sysbrazo) ← tablas reales

Objetivo: construir UNA tabla consolidada (una fila por autodiagnóstico) con la
misma forma del Excel de ejemplo, pero con datos reales del canal **Sysbrazo**.

**Grano (base):** `sysbrazo.auto_diagnostic_runs` = un registro por
autodiagnóstico hecho vía Sysbrazo.

| Columna objetivo | De dónde sale | Notas |
|---|---|---|
| **Fecha** | `auto_diagnostic_runs.started_at` (parte fecha) | |
| **Hora** | `auto_diagnostic_runs.started_at` (parte hora) | |
| **Canal** | literal `'Sysbrazo'` | Estas tablas son del canal Sysbrazo |
| **Ciudad** | `analytics.client_address.locality` | join `runs.client_id = client_address.client_id` |
| **ID Cliente** | `auto_diagnostic_runs.client_id` | |
| **Nombre y Apellido** | `analytics.client.first_name + last_name` | join por `client_id` (o `commercial_name` si empresa) |
| **Cédula** | `analytics.client.document_id` | join por `client_id` |
| **Resultado** | `auto_diagnostic_runs.status` | `finished`→Completado, `failed`→Fallido, `canceled`→**Escalado** (generó ticket) |
| **Tiempo que tardó** | `finished_at - started_at` | duración del proceso |
| **Número de ticket** | `sysbrazo.odoo_tickets.odoo_id` | solo si Escalado — depende del join run→ticket (ver abajo) |
| **Área Responsable** | `sysbrazo.odoo_tickets.team` | texto directo, sin joins extra |
| **Estado de ticket** | `sysbrazo.odoo_tickets.stage` | mapear: Solved→Solucionado, New→Abierto, In Progress→En Gestión, otros→Otro; Nulo si no hay ticket |
| **Fecha/hora apertura ticket** | `sysbrazo.odoo_tickets.create_date` | |
| **Fecha/hora cierre ticket** | `sysbrazo.odoo_tickets.close_date` | |

## Lo que YA está resuelto (columnas 1–9)
Todo lo del nivel "proceso" sale directo de `auto_diagnostic_runs` +
`analytics.client` / `analytics.client_address`. Con esto solo, el canal Sysbrazo
ya funciona en el chatbot (fecha, hora, canal, ciudad, cliente, cédula,
resultado, duración).

## La ÚNICA pieza por confirmar (columnas 10–14: el ticket)
Falta confirmar **cómo se une un run 'canceled' con su ticket específico**, ahora
que la columna `data` (que traía el `ticket_ref`) viene en null en 2026.

Hipótesis a verificar con datos reales (ver `explorar_sysbrazo.py`):
1. **Vía `odoo_ticket_clients`:** `run.client_id → odoo_ticket_clients.client_id →
   odoo_ticket_id → odoo_tickets` (filtrando `name LIKE '%Autod%'`), emparejando
   por cliente + cercanía de fecha (ticket creado cerca del run).
2. **Vía llave `id`:** el documento sugiere que las tablas de proceso comparten un
   `id` que las conecta con las tablas de ticket. Hay que verificar la cardinalidad.
3. **Vía `data.ticket_ref`:** el camino original, solo si `data` dejó de venir null.

## Plan
- **Paso 1:** construir la consolidada con columnas 1–9 (100% listas) → Sysbrazo
  funcionando ya en el chatbot.
- **Paso 2:** confirmar el join run→ticket con la exploración → agregar columnas
  10–14.
