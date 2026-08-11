-- =============================================================================
-- Agregar el campo 'final_outcome' a la vista materializada del autodiagnóstico
-- =============================================================================
-- Contexto: el chatbot lee de la vista materializada
--   analytics.v_auto_diagnostic_full
-- Se quiere exponer la DIRECTRIZ FINAL entregada al cliente, que ya viene
-- dentro del JSON 'data' de sysbrazo.auto_diagnostic_runs como una clave de
-- primer nivel:
--   {"context":{...}, "final_outcome":"ALL_OK", "initializing - 0":"success", ...}
-- Valores observados: ALL_OK, TICKET_CREATED, CREDIT_RECHARGED, BLOCKED,
--                     CANCELED, ERROR
--
-- La línea a agregar es UNA sola:
--     r.data->>'final_outcome' AS final_outcome,
--
-- Pero como es una vista MATERIALIZADA, no admite CREATE OR REPLACE:
-- hay que recrearla (DROP + CREATE) y refrescarla.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- PASO 1 (IMPORTANTE): obtener la definición ACTUAL de la vista
-- -----------------------------------------------------------------------------
-- No recrear la vista "de memoria": hay que partir de su definición real, para
-- no perder columnas ni filtros que hoy existan (p. ej. 'created_at', que no
-- aparece en la versión de la consulta que se venía compartiendo).

SELECT definition
FROM pg_matviews
WHERE schemaname = 'analytics'
  AND matviewname = 'v_auto_diagnostic_full';


-- -----------------------------------------------------------------------------
-- PASO 2: recrear la vista agregando la columna
-- -----------------------------------------------------------------------------
-- Tomar el texto devuelto en el PASO 1, insertarle la línea nueva
-- (r.data->>'final_outcome' AS final_outcome,) y ejecutar:
--
--   DROP MATERIALIZED VIEW IF EXISTS analytics.v_auto_diagnostic_full;
--
--   CREATE MATERIALIZED VIEW analytics.v_auto_diagnostic_full AS
--   <definición del PASO 1, ya con la línea nueva>
--   ;
--
--   -- Índice único: permite refrescar sin bloquear lecturas (REFRESH CONCURRENTLY)
--   CREATE UNIQUE INDEX IF NOT EXISTS ix_v_auto_diag_full_id
--       ON analytics.v_auto_diagnostic_full (id);
--
--   REFRESH MATERIALIZED VIEW analytics.v_auto_diagnostic_full;


-- -----------------------------------------------------------------------------
-- REFERENCIA: dónde va la línea nueva dentro del SELECT
-- -----------------------------------------------------------------------------
-- (Fragmento ilustrativo — el orden de las columnas no afecta al chatbot.)
--
--     r.source,
--     r.status,
--     r.data->>'final_outcome' AS final_outcome,    -- <<< LÍNEA NUEVA
--     r.started_at,
--     r.finished_at,
--     ...


-- -----------------------------------------------------------------------------
-- ADVERTENCIAS
-- -----------------------------------------------------------------------------
-- 1) FILTRO DE FECHAS: la versión de la consulta que se venía compartiendo trae
--    "WHERE r.started_at >= '2026-07-01'". La vista actual NO tiene ese filtro
--    (el chatbot ve datos desde nov-2025). Si se recrea con ese WHERE, se
--    perdería el histórico. Conservar el filtro que tenga la definición real.
--
-- 2) DATO NUEVO: 'final_outcome' empezó a capturarse hace poco, así que vendrá
--    NULL en los autodiagnósticos anteriores. Es esperado; el chatbot ya está
--    preparado para excluirlos al analizar esta columna.
--
-- 3) REFRESCO: mientras la vista se recrea, el chatbot seguirá funcionando con
--    el último resultado cacheado en Redash. Al terminar, basta con ejecutar la
--    consulta en Redash y pulsar "Actualizar datos" en el chatbot.


-- -----------------------------------------------------------------------------
-- OPCIONAL: otros dos datos útiles que ya viven en el mismo JSON
-- -----------------------------------------------------------------------------
-- Si se quieren aprovechar en el mismo cambio (no son necesarios para
-- 'final_outcome'):
--
--   -- ¿El cliente repitió el autodiagnóstico por alcanzar un límite?
--   (r.data->>'repeated_from_limit')::boolean AS repetido_por_limite,
--
--   -- Teléfono usado en el proceso (cuando aplica)
--   r.data->'context'->>'phone' AS telefono_contacto,
