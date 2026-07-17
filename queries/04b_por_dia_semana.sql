-- Pregunta 4b: Distribución de autodiagnósticos por día de la semana.
-- dia_num: 1 = Lunes ... 7 = Domingo (estándar ISO, usado para ordenar).

SELECT
    TO_CHAR(started_at, 'Day')      AS dia_semana,
    EXTRACT(ISODOW FROM started_at)::int AS dia_num,
    COUNT(*)                        AS autodiagnosticos
FROM sysbrazo.auto_diagnostic_runs
WHERE started_at BETWEEN %(fecha_inicio)s AND %(fecha_fin)s
GROUP BY 1, 2
ORDER BY 2;
