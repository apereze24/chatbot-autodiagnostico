-- Pregunta 3: Número de clientes/autodiagnósticos por ciudad.
-- Se obtiene la ciudad uniendo con analytics.client_address (campo 'locality').

SELECT
    COALESCE(ca.locality, 'Sin ciudad registrada') AS ciudad,
    COUNT(*)                    AS autodiagnosticos,
    COUNT(DISTINCT r.client_id) AS clientes
FROM sysbrazo.auto_diagnostic_runs r
LEFT JOIN analytics.client_address ca ON ca.client_id = r.client_id
WHERE r.started_at BETWEEN %(fecha_inicio)s AND %(fecha_fin)s
GROUP BY 1
ORDER BY autodiagnosticos DESC;
