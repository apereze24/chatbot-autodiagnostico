-- Pregunta 4a: Distribución de autodiagnósticos por hora del día (0 a 23).

SELECT
    EXTRACT(HOUR FROM started_at)::int AS hora,
    COUNT(*)                           AS autodiagnosticos
FROM sysbrazo.auto_diagnostic_runs
WHERE started_at BETWEEN %(fecha_inicio)s AND %(fecha_fin)s
GROUP BY 1
ORDER BY 1;
