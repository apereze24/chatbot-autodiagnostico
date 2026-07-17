-- Pregunta 7: ¿Cuántos clientes hicieron varios autodiagnósticos en poco tiempo
-- y aun así terminaron con el proceso resuelto? (para entender por qué siguen
-- intentando).
--
-- "Resuelto" incluye DOS casos (confirmado):
--   a) el proceso de autodiagnóstico corrió completo (status = 'finished'), o
--   b) el ticket que generó (si lo hubo) quedó Solved en Odoo.
--
-- Parámetros: %(min_intentos)s (ej. 3) y %(fecha_inicio)s / %(fecha_fin)s definen
-- la ventana de tiempo a analizar.

WITH runs_con_ticket AS (
    SELECT
        r.id AS run_id,  -- ¡Corregido aquí! Cambiamos r.run_id por r.id
        r.client_id,
        r.status,
        r.started_at,
        (r.data -> 'context' ->> 'ticket_ref') AS ticket_ref
    FROM sysbrazo.auto_diagnostic_runs r
    WHERE r.started_at BETWEEN %(fecha_inicio)s AND %(fecha_fin)s
),
runs_resueltos AS (
    SELECT
        rt.run_id,
        rt.client_id,
        rt.started_at,
        (
            rt.status = 'finished'
            OR EXISTS (
                SELECT 1
                FROM odoo.helpdesk_ticket ht
                LEFT JOIN odoo.helpdesk_stage hs ON hs.id = ht.stage_id
                WHERE rt.ticket_ref IS NOT NULL
                  AND ht.ticket_ref::text = rt.ticket_ref::text -- ¡Ajuste preventivo a texto!
                  AND hs.name = 'Solved'
            )
        ) AS resuelto
    FROM runs_con_ticket rt
)
SELECT
    client_id,
    COUNT(*)                              AS autodiagnosticos,
    COUNT(*) FILTER (WHERE resuelto)      AS veces_resuelto,
    BOOL_OR(resuelto)                     AS alguno_resuelto,
    MIN(started_at)                       AS primer_intento,
    MAX(started_at)                       AS ultimo_intento
FROM runs_resueltos
GROUP BY client_id
HAVING COUNT(*) >= %(min_intentos)s
   AND BOOL_OR(resuelto)
ORDER BY autodiagnosticos DESC;
