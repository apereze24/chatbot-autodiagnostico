-- =============================================================================
-- Métricas de autodiagnóstico por periodo (día, semana, mes, año)
-- =============================================================================
-- Fuente: analytics.v_auto_diagnostic_full (la misma vista que alimenta el
-- chatbot). Motor: PostgreSQL.
--
-- SON 5 CONSULTAS SEPARADAS, no una sola. En Redash cada consulta produce UNA
-- tabla, y de ahí salen sus gráficos. Mezclar "por día" con "por ciudad" en un
-- mismo resultado obliga a repetir filas y los totales dejan de cuadrar. Se crea
-- una consulta de Redash por bloque, y luego se arman todas en un dashboard.
--
-- ZONA HORARIA: la vista guarda las fechas en UTC. Todo aquí las pasa a hora de
-- Colombia con  (started_at - INTERVAL '5 hours')  para que "el lunes" sea el
-- lunes del cliente y no el de UTC. Sin esa resta, todo lo que ocurre después de
-- las 7 p.m. se cuenta en el día siguiente.
--
-- PARÁMETROS: cada consulta usa {{ desde }} y {{ hasta }} (tipo Date en Redash).
-- Al guardar la consulta, Redash los detecta solo y muestra los dos calendarios.
-- Si prefieres ver todo el histórico, borra esas dos líneas del WHERE.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1) AUTODIAGNÓSTICOS POR DÍA
--    Una fila por día, con año, mes y semana al lado para poder agrupar y
--    filtrar sin volver a calcular nada.
-- -----------------------------------------------------------------------------
SELECT
    (started_at - INTERVAL '5 hours')::date                    AS dia,
    EXTRACT(YEAR  FROM started_at - INTERVAL '5 hours')::int   AS anio,
    EXTRACT(MONTH FROM started_at - INTERVAL '5 hours')::int   AS mes,
    TO_CHAR(started_at - INTERVAL '5 hours', 'YYYY-MM')        AS anio_mes,
    -- Lunes de esa semana: sirve como eje X en el gráfico semanal.
    DATE_TRUNC('week', started_at - INTERVAL '5 hours')::date  AS semana_inicia,
    TRIM(TO_CHAR(started_at - INTERVAL '5 hours', 'Day'))      AS dia_semana,
    COUNT(*)                                                   AS autodiagnosticos,
    COUNT(*) FILTER (WHERE status = 'finished')                AS completados,
    COUNT(*) FILTER (WHERE status = 'failed')                  AS fallidos,
    COUNT(*) FILTER (WHERE status = 'canceled')                AS escalados,
    COUNT(DISTINCT client_id)                                  AS clientes_distintos
FROM analytics.v_auto_diagnostic_full
WHERE started_at IS NOT NULL
  AND (started_at - INTERVAL '5 hours')::date BETWEEN {{ desde }} AND {{ hasta }}
GROUP BY 1, 2, 3, 4, 5, 6
ORDER BY dia;


-- -----------------------------------------------------------------------------
-- 2) AUTODIAGNÓSTICOS POR SEMANA
--    Cuidado con la primera y la última semana del rango: casi siempre están
--    incompletas, y en un gráfico eso se ve como una caída que no existe. Por
--    eso va 'dias_con_datos': si dice 3, esa barra no se compara con las de 7.
-- -----------------------------------------------------------------------------
SELECT
    DATE_TRUNC('week', started_at - INTERVAL '5 hours')::date   AS semana_inicia,
    (DATE_TRUNC('week', started_at - INTERVAL '5 hours')
        + INTERVAL '6 days')::date                              AS semana_termina,
    COUNT(*)                                                    AS autodiagnosticos,
    COUNT(DISTINCT (started_at - INTERVAL '5 hours')::date)     AS dias_con_datos,
    ROUND(COUNT(*)::numeric
          / NULLIF(COUNT(DISTINCT (started_at - INTERVAL '5 hours')::date), 0), 1)
                                                                AS promedio_por_dia,
    COUNT(*) FILTER (WHERE status = 'failed')                   AS fallidos,
    COUNT(*) FILTER (WHERE status = 'canceled')                 AS escalados
FROM analytics.v_auto_diagnostic_full
WHERE started_at IS NOT NULL
  AND (started_at - INTERVAL '5 hours')::date BETWEEN {{ desde }} AND {{ hasta }}
GROUP BY 1, 2
ORDER BY semana_inicia;


-- -----------------------------------------------------------------------------
-- 3) TOTALES POR SEMANA, MES Y AÑO (los tres en una sola tabla)
--    La columna 'periodo' dice de qué tipo es cada fila, así el dashboard puede
--    filtrar "solo meses" o "solo semanas" sin necesitar tres consultas.
--
--    Se usa UNION ALL y no GROUPING SETS a propósito: una semana puede quedar
--    partida entre dos meses (la que cruza el fin de mes), y anidar semana
--    dentro de mes la contaría dos veces. Así cada nivel se calcula solo, sobre
--    todas las filas, y los totales de cada bloque cuadran por separado.
-- -----------------------------------------------------------------------------
WITH base AS (
    SELECT
        (started_at - INTERVAL '5 hours') AS fecha_local,
        status
    FROM analytics.v_auto_diagnostic_full
    WHERE started_at IS NOT NULL
      AND (started_at - INTERVAL '5 hours')::date BETWEEN {{ desde }} AND {{ hasta }}
),
-- Cada nivel calcula lo mismo, solo cambia cómo se agrupa.
por_semana AS (
    SELECT 'Semana' AS periodo,
           TO_CHAR(DATE_TRUNC('week', fecha_local), 'YYYY-MM-DD') AS etiqueta,
           DATE_TRUNC('week', fecha_local)::date AS ordena,
           status
    FROM base
),
por_mes AS (
    SELECT 'Mes' AS periodo,
           TO_CHAR(fecha_local, 'YYYY-MM') AS etiqueta,
           DATE_TRUNC('month', fecha_local)::date AS ordena,
           status
    FROM base
),
por_anio AS (
    SELECT 'Año' AS periodo,
           TO_CHAR(fecha_local, 'YYYY') AS etiqueta,
           DATE_TRUNC('year', fecha_local)::date AS ordena,
           status
    FROM base
),
todo AS (
    SELECT * FROM por_semana
    UNION ALL SELECT * FROM por_mes
    UNION ALL SELECT * FROM por_anio
)
SELECT
    periodo,
    etiqueta,
    COUNT(*)                                        AS autodiagnosticos,
    COUNT(*) FILTER (WHERE status = 'finished')     AS completados,
    COUNT(*) FILTER (WHERE status = 'failed')       AS fallidos,
    COUNT(*) FILTER (WHERE status = 'canceled')     AS escalados,
    ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'finished')
          / NULLIF(COUNT(*), 0), 1)                 AS pct_completados,
    ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'canceled')
          / NULLIF(COUNT(*), 0), 1)                 AS pct_escalados
FROM todo
GROUP BY periodo, etiqueta, ordena
ORDER BY periodo, ordena;


-- -----------------------------------------------------------------------------
-- 4) ANÁLISIS DE RESULTADOS (desglose de 'final_outcome')
--    'final_outcome' es la directriz final que se le entregó al cliente: es lo
--    que el negocio llama "el resultado". No confundir con 'status', que es el
--    estado técnico con que terminó el proceso.
--
--    EL FILTRO 'IS NOT NULL' NO ES OPCIONAL: este campo se empezó a capturar en
--    agosto de 2026, así que todo lo anterior lo tiene vacío. Sin el filtro, los
--    porcentajes salen diluidos contra un universo que nunca tuvo el dato.
-- -----------------------------------------------------------------------------
SELECT
    TO_CHAR(started_at - INTERVAL '5 hours', 'YYYY-MM')   AS anio_mes,
    final_outcome                                         AS resultado,
    CASE final_outcome
        WHEN 'ALL_OK'               THEN 'Todo bien, sin problema'
        WHEN 'ALL_OK_WITH_WARNINGS' THEN 'Bien, con advertencias'
        WHEN 'TICKET_CREATED'       THEN 'Se generó un ticket'
        WHEN 'CREDIT_RECHARGED'     THEN 'Se recargó crédito'
        WHEN 'BLOCKED'              THEN 'Proceso bloqueado'
        WHEN 'CANCELED'             THEN 'Proceso cancelado'
        WHEN 'ERROR'                THEN 'Error técnico'
        ELSE final_outcome
    END                                                   AS resultado_en_palabras,
    COUNT(*)                                              AS casos,
    -- El porcentaje se calcula DENTRO de cada mes, no sobre el total del rango:
    -- así se comparan meses con volúmenes muy distintos sin que el más grande
    -- se coma a los demás.
    ROUND(100.0 * COUNT(*)
          / SUM(COUNT(*)) OVER (
                PARTITION BY TO_CHAR(started_at - INTERVAL '5 hours', 'YYYY-MM')
            ), 1)                                         AS pct_del_mes
FROM analytics.v_auto_diagnostic_full
WHERE started_at IS NOT NULL
  AND final_outcome IS NOT NULL
  AND (started_at - INTERVAL '5 hours')::date BETWEEN {{ desde }} AND {{ hasta }}
GROUP BY 1, 2, 3
ORDER BY anio_mes, casos DESC;


-- -----------------------------------------------------------------------------
-- 5) AUTODIAGNÓSTICOS POR CIUDAD
--    Con el mes al lado, para poder ver la evolución de una ciudad en el tiempo
--    o quedarse solo con el total del periodo.
-- -----------------------------------------------------------------------------
SELECT
    TO_CHAR(started_at - INTERVAL '5 hours', 'YYYY-MM')   AS anio_mes,
    COALESCE(nombre_ciudad, 'Sin ciudad')                 AS ciudad,
    COUNT(*)                                              AS autodiagnosticos,
    ROUND(100.0 * COUNT(*)
          / SUM(COUNT(*)) OVER (
                PARTITION BY TO_CHAR(started_at - INTERVAL '5 hours', 'YYYY-MM')
            ), 1)                                         AS pct_del_mes,
    COUNT(DISTINCT client_id)                             AS clientes_distintos,
    COUNT(*) FILTER (WHERE status = 'failed')             AS fallidos,
    COUNT(*) FILTER (WHERE status = 'canceled')           AS escalados,
    -- Si un mismo cliente vuelve a diagnosticar, su problema no se resolvió.
    -- Un número alto aquí es una señal de servicio, no de volumen.
    ROUND(COUNT(*)::numeric / NULLIF(COUNT(DISTINCT client_id), 0), 2)
                                                          AS intentos_por_cliente
FROM analytics.v_auto_diagnostic_full
WHERE started_at IS NOT NULL
  AND (started_at - INTERVAL '5 hours')::date BETWEEN {{ desde }} AND {{ hasta }}
GROUP BY 1, 2
ORDER BY anio_mes, autodiagnosticos DESC;
