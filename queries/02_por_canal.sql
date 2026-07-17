-- Pregunta 2: Número de clientes por canal (Portal, Bot, Sysbrazo).
--
-- NOTA IMPORTANTE: por ahora esta consulta solo puede traer el canal "Sysbrazo",
-- porque es el único que vive en esta base de datos (Postgres). Los canales
-- "Portal" y "Bot" viven en Mixpanel y se conectan en la Fase 4.
-- Mientras tanto, esta consulta sirve para tener el número de Sysbrazo, y el
-- chatbot combinará este resultado con los de Mixpanel más adelante.

SELECT
    'Sysbrazo' AS canal,
    COUNT(*)                  AS autodiagnosticos,
    COUNT(DISTINCT client_id) AS clientes
FROM sysbrazo.auto_diagnostic_runs
WHERE started_at BETWEEN %(fecha_inicio)s AND %(fecha_fin)s;
