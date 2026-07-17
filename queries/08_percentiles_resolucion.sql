-- Pregunta 8: Percentiles (P10 a P90) del tiempo de resolución, en horas, de los
-- tickets generados por el autodiagnóstico y que quedaron Resueltos (Solved).
--
-- Usa el campo close_hours de Odoo (ya calculado), filtrando SIEMPRE por
-- stage_name = 'Solved' (los tickets no resueltos traen close_hours = 0, no
-- vacío, y distorsionarían los percentiles si no se filtran).

WITH runs_con_ticket AS (
    SELECT (r.data -> 'context' ->> 'ticket_ref') AS ticket_ref
    FROM sysbrazo.auto_diagnostic_runs r
    WHERE r.started_at BETWEEN %(fecha_inicio)s AND %(fecha_fin)s
      AND (r.data -> 'context' ->> 'ticket_ref') IS NOT NULL
),
tickets_resueltos AS (
    SELECT ht.close_hours
    FROM runs_con_ticket rt
    JOIN odoo.helpdesk_ticket ht ON ht.ticket_ref = rt.ticket_ref::numeric
    LEFT JOIN odoo.helpdesk_stage hs ON hs.id = ht.stage_id
    WHERE hs.name = 'Solved'
)
SELECT
    percentil,
    ROUND(
        PERCENTILE_CONT(percentil / 100.0) WITHIN GROUP (ORDER BY close_hours)::numeric,
        1
    ) AS horas
FROM tickets_resueltos, UNNEST(ARRAY[10,20,30,40,50,60,70,80,90]) AS percentil
GROUP BY percentil
ORDER BY percentil;
