-- Pregunta 9: De los autodiagnósticos que dieron error (status 'failed' o
-- 'canceled'), ¿cuántos clientes repitieron el proceso dentro de 24, 48 y 72h?

WITH runs_ordenados AS (
    SELECT
        run_id,
        client_id,
        started_at,
        status,
        LEAD(started_at) OVER (
            PARTITION BY client_id ORDER BY started_at
        ) AS siguiente_intento
    FROM sysbrazo.auto_diagnostic_runs
    WHERE started_at BETWEEN %(fecha_inicio)s AND %(fecha_fin)s
),
errores AS (
    SELECT
        run_id,
        client_id,
        started_at,
        siguiente_intento,
        EXTRACT(EPOCH FROM (siguiente_intento - started_at)) / 3600.0 AS horas_hasta_reintento
    FROM runs_ordenados
    WHERE status IN ('failed', 'canceled')
)
SELECT
    COUNT(*)                                                     AS total_errores,
    COUNT(*) FILTER (WHERE horas_hasta_reintento <= 24)          AS reopen_24h,
    COUNT(*) FILTER (WHERE horas_hasta_reintento <= 48)          AS reopen_48h,
    COUNT(*) FILTER (WHERE horas_hasta_reintento <= 72)          AS reopen_72h,
    ROUND(100.0 * COUNT(*) FILTER (WHERE horas_hasta_reintento <= 24) / NULLIF(COUNT(*), 0), 1) AS pct_24h,
    ROUND(100.0 * COUNT(*) FILTER (WHERE horas_hasta_reintento <= 48) / NULLIF(COUNT(*), 0), 1) AS pct_48h,
    ROUND(100.0 * COUNT(*) FILTER (WHERE horas_hasta_reintento <= 72) / NULLIF(COUNT(*), 0), 1) AS pct_72h
FROM errores;
