-- Pregunta 5: Tiempo de resolución por etapa del funnel (según cómo terminó el
-- proceso: finished / failed / canceled). La duración es del proceso de
-- autodiagnóstico en sí (started_at -> finished_at), en minutos.
--
-- Nota: 'finished' = el autodiagnóstico corrió completo (sin importar si el
-- resultado técnico fue OK o mostró una falla). 'failed' / 'canceled' = el
-- proceso no pudo completarse (normalmente genera un ticket, ver preguntas 6 y 8).

SELECT
    status,
    COUNT(*) AS casos,
    ROUND(
        AVG(EXTRACT(EPOCH FROM (finished_at - started_at)) / 60.0)::numeric, 1
    ) AS duracion_promedio_min,
    ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY EXTRACT(EPOCH FROM (finished_at - started_at)) / 60.0
        )::numeric, 1
    ) AS duracion_mediana_min
FROM sysbrazo.auto_diagnostic_runs
WHERE started_at BETWEEN %(fecha_inicio)s AND %(fecha_fin)s
  AND finished_at IS NOT NULL
GROUP BY status
ORDER BY casos DESC;
