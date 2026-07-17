# Consultas SQL — Fase 2

Estas son las 10 consultas, una por archivo, escritas contra las tablas reales
(`sysbrazo`, `analytics`, `odoo`). **Todavía no se han probado contra la base de
datos real** — están escritas con base en los campos que confirmaste, pero hay
que ejecutarlas al menos una vez para verificar que corren bien y que las cifras
tienen sentido.

Los `%(fecha_inicio)s`, `%(fecha_fin)s`, etc. son "espacios en blanco" que el
programa llena automáticamente según los filtros que el usuario elija en el
chatbot (no hay que editarlos a mano).

| Archivo | Pregunta | Estado |
|---|---|---|
| `01_total_clientes.sql` | 1. Total de clientes/autodiagnósticos | ✅ Lista |
| `02_por_canal.sql` | 2. Por canal | ⚠️ Solo trae "Sysbrazo" (Bot/Portal llegan en Fase 4) |
| `03_por_ciudad.sql` | 3. Por ciudad | ✅ Lista |
| `04a_por_hora.sql` | 4. Por hora del día | ✅ Lista |
| `04b_por_dia_semana.sql` | 4. Por día de la semana | ✅ Lista |
| `05_tiempo_por_funnel.sql` | 5. Tiempo por funnel | ✅ Lista |
| `06_tipo_resolucion.sql` | 6. Resuelto / NOC / OPS / motivo de cierre | ✅ Lista (falta ver valores reales de `motivo_cierre`, ver abajo) |
| `07_clientes_repetidores.sql` | 7. Clientes que repiten | ✅ Lista |
| `08_percentiles_resolucion.sql` | 8. Percentiles de resolución | ✅ Lista |
| `09_reopen_fallidos.sql` | 9. Reopen 24/48/72h | ✅ Lista |
| `10_por_hora_y_ciudad.sql` | 10. Hora y ciudad | ✅ Lista |

## Definiciones de negocio ya confirmadas

- **Equipo NOC vs OPS** (`06_tipo_resolucion.sql`): `team_name = 'NOC'` → NOC;
  `team_name = 'Instalaciones y Mantenimiento'` → OPS. `NET Operations` es un
  equipo **distinto** a NOC (confirmado) y queda como su propia categoría.
- **Motivo de cierre** (`06_tipo_resolucion.sql`): sale de
  `odoo.fbz_helpdesk_motivo` uniendo por `helpdesk_ticket.cierre_motivo_id`,
  filtrando `tipo = 'cierre'` (esa tabla mezcla motivos de apertura y cierre).
  Pendiente menor: correr la consulta para ver qué valores reales trae
  `motivo_cierre` (ej. "Falla técnica resuelta", "Sin problema detectado", etc.)
  — no bloquea usar la consulta, solo falta verla con datos reales.
- **"Terminó resuelto"** (`07_clientes_repetidores.sql`): un intento cuenta como
  resuelto si el proceso corrió completo (`status = 'finished'`) **o** si generó
  un ticket que quedó `Solved` en Odoo.

## Lo único que falta para poder usarlas

**Probarlas contra la base real** — necesito que las ejecutes en la herramienta
donde ya tienes acceso (la misma con la que sacaste los datos de
`helpdesk_ticket`), o bien darme acceso directo a Postgres para probarlas yo.
