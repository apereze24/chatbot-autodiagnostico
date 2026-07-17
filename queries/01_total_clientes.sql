-- Pregunta 1: Número de clientes que piden soporte de autodiagnóstico
-- (y total de autodiagnósticos realizados) en el rango de fechas dado.
-- Alcance: solo canal Sysbrazo (Bot/Portal se suman en Fase 4 vía Mixpanel).

SELECT
    COUNT(*)                    AS total_autodiagnosticos,
    COUNT(DISTINCT client_id)   AS clientes_unicos
FROM sysbrazo.auto_diagnostic_runs
WHERE started_at BETWEEN %(fecha_inicio)s AND %(fecha_fin)s;
