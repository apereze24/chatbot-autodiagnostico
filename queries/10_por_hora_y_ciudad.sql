-- Pregunta 10: Cantidad de autodiagnósticos por hora del día y por ciudad
-- (tabla cruzada: una fila por hora, una columna por ciudad).

SELECT
    COALESCE(ca.locality, 'Sin ciudad registrada') AS ciudad,
    EXTRACT(HOUR FROM r.started_at)::int           AS hora,
    COUNT(*)                                        AS autodiagnosticos
FROM sysbrazo.auto_diagnostic_runs r
LEFT JOIN analytics.client_address ca ON ca.client_id = r.client_id
WHERE r.started_at BETWEEN %(fecha_inicio)s AND %(fecha_fin)s
GROUP BY 1, 2
ORDER BY 1, 2;
