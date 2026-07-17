-- Pregunta 6: De los autodiagnósticos que generaron un ticket, ¿cuántos
-- terminaron Resuelto (Solved), qué equipo lo atendió (NOC / OPS / Otro), y
-- con qué motivo de cierre?
--
-- Cómo se conecta:
--   sysbrazo.auto_diagnostic_runs.data -> 'context' ->> 'ticket_ref' (texto)
--   = odoo.helpdesk_ticket.ticket_ref (número).
--
-- El motivo de cierre sale de fbz_helpdesk_motivo, que guarda motivos de
-- APERTURA y de CIERRE en la misma tabla (columna 'tipo'). Por eso se filtra
-- tipo = 'cierre' al unir por helpdesk_ticket.cierre_motivo_id.
--
-- Confirmado: "NET Operations" NO es lo mismo que "NOC" — quedan separados.

WITH runs_con_ticket AS (
    SELECT
        r.id AS run_id,
        r.client_id,
        r.status AS status_run,
        (r.data -> 'context' ->> 'ticket_ref') AS ticket_ref
    FROM sysbrazo.auto_diagnostic_runs r
    WHERE (r.data -> 'context' ->> 'ticket_ref') IS NOT NULL
)
SELECT
    CASE
        WHEN hs.name = 'Solved' THEN 'Resuelto'
        ELSE 'No resuelto'
    END AS estado_resolucion,
    CASE
        WHEN htm.name = 'NOC' THEN 'NOC'
        WHEN htm.name = 'Instalaciones y Mantenimiento' THEN 'OPS'
        WHEN htm.name = 'Customer Experience (CX)' THEN 'CX'
        WHEN htm.name = 'NET Operations' THEN 'NET Operations'
        ELSE 'Otro'
    END AS equipo,
    COALESCE(motivo_cierre.name, 'Sin motivo registrado') AS motivo_cierre,
    COUNT(*) AS tickets
FROM runs_con_ticket rt
-- Forzamos a texto en ambos lados para evitar errores silenciosos
JOIN odoo.helpdesk_ticket ht ON ht.ticket_ref::text = rt.ticket_ref::text 
LEFT JOIN odoo.helpdesk_stage hs ON hs.id = ht.stage_id
LEFT JOIN odoo.helpdesk_team htm ON htm.id = ht.team_id
LEFT JOIN odoo.fbz_helpdesk_motivo motivo_cierre
    ON motivo_cierre.id = ht.cierre_motivo_id
   AND motivo_cierre.tipo = 'cierre'
GROUP BY 1, 2, 3
ORDER BY tickets DESC;

** Aún no podemos reflejar fechas, El SQL para cruzar Autodiagnósticos con Odoo ya está listo, pero detectamos un problema de captura de datos: en la tabla sysbrazo.auto_diagnostic_runs, los registros de 2026 están llegando con la columna data en null. Necesitamos que el sistema vuelva a guardar el JSON que contiene el ticket_ref cuando un proceso falla, ya que este es nuestro único puente de conexión con los tickets de Odoo.