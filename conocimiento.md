# Conocimiento del negocio — Autodiagnóstico

> **Este archivo lo lee la IA antes de responder cada pregunta.**
> Puedes editarlo libremente (es texto normal): cada cosa que agregues aquí,
> el chatbot la sabrá. Si notas que responde algo mal o interpreta un término
> de forma equivocada, corrígelo aquí y quedará aprendido para siempre.

## Qué es el autodiagnóstico

Proceso que diagnostica de forma remota el módem de wifi (CPE) en la casa del
cliente, para saber si el equipo está bien, si replica wifi, si está sin señal o
si definitivamente no funciona. El cliente puede lanzarlo por su cuenta, o un
asesor lo ejecuta por él.

Cada fila de la tabla = **un intento de autodiagnóstico** de un cliente.

## Canales (columna `source`)

| Valor | Qué es |
|---|---|
| `portal` | El cliente entra al portal "Mi Fibrazo" y lo ejecuta él mismo. Es el canal de mayor volumen. |
| `whatsapp` | El cliente interactúa con el bot de WhatsApp (Botmaker) y llega a ejecutarlo. |
| `sysbrazo` | Lo ejecuta un asesor humano desde el CRM, normalmente cuando el cliente insiste con una falla de internet. Es el de menor volumen. |

## Resultado del proceso (columna `status`)

| Valor | Significado |
|---|---|
| `finished` | El proceso corrió completo. |
| `failed` | El proceso falló técnicamente. |
| `canceled` | El proceso se detuvo y **escaló a un ticket** para revisión manual. |
| `running` | Estaba en curso al momento de extraer los datos. |

**Regla importante:** `canceled` NO significa que el cliente canceló. Significa
que el autodiagnóstico no pudo resolverlo solo y lo escaló.

## Directriz final entregada al cliente (columna `final_outcome`)

Es **lo que finalmente se le comunicó al cliente**. Es la columna más
importante para entender el desenlace desde la óptica del cliente.

| Valor | Significado |
|---|---|
| `ALL_OK` | Todo bien, no se detectó problema. |
| `TICKET_CREATED` | Se generó un ticket para revisión manual. |
| `CREDIT_RECHARGED` | Se le recargó crédito al cliente. |
| `BLOCKED` | El proceso se bloqueó (ej. el cliente ya tenía un incidente abierto). |
| `CANCELED` | El proceso se canceló. |
| `ERROR` | Ocurrió un error técnico. |

**Ojo:** este dato empezó a capturarse recientemente, así que los
autodiagnósticos anteriores lo tienen vacío. Al analizarlo, excluir los vacíos.

## El ticket (cuando el autodiagnóstico escala)

- `ticket_stage` — estado: `New` (abierto), `In Progress` (en gestión),
  `Solved` (resuelto).
- `ticket_team` — equipo que lo atiende: `NOC`, `Instalaciones y Mantenimiento`
  (equivale a OPS / operaciones de campo), `Customer Experience (CX)`,
  `Planta externa`, `NET Operations`.
  **`NET Operations` NO es lo mismo que `NOC`**: son equipos distintos.
- `ticket_resolucion_horas` — horas que tardó en resolverse (cierre − apertura).
  Solo tiene valor si el ticket ya cerró.
- `ticket_opening_reason` / `ticket_close_reason` — por qué se abrió y cómo se
  cerró.

## Causas técnicas de falla (columna `failure_reason`)

Códigos técnicos, en inglés. Los más comunes y su traducción:

| Código | Qué significa |
|---|---|
| `CPE_OFFLINE` | El módem está apagado o desconectado. |
| `CPE_LOSS_OF_SIGNAL` | El módem perdió señal de fibra (LOS). |
| `CPE_NOT_FOUND` | No se encontró el módem del cliente en el sistema. |
| `CPE_GPON_POWER_LOW` | Potencia óptica baja (señal débil de fibra). |
| `CPE_STATE_NOT_UP` | El módem no está en estado operativo. |
| `CLIENT_HAS_OPEN_INCIDENT` | El cliente ya tenía un incidente/ticket abierto. |
| `CLIENT_AFFECTED_BY_KRILL_ALARM` | El cliente está afectado por una falla masiva conocida. |
| `CLIENT_STATUS_INACTIVE` | El cliente está inactivo (ej. suspendido). |
| `DAILY_CREDIT_LIMIT_REACHED` | Se alcanzó el límite diario de crédito. |
| `TIMEOUT_EXCEEDED` | El proceso se pasó del tiempo máximo. |
| `PING_BATCH_RETRY_FAILED` | Fallaron los reintentos de ping al módem. |
| `KRILL_POST_FAILED` | Falló el registro en el sistema Krill. |

Al responder, **traduce estos códigos a lenguaje entendible** (ej. "módem
desconectado" en vez de `CPE_OFFLINE`), pero menciona el código entre
paréntesis por si el usuario lo necesita.

## Pasos del proceso (columna `failed_step`)

Orden típico del flujo: `initializing` → `check_credit` →
`get_cpe_status_info` → `get_cpe_gpon_power_Info` → `ping_internet_cpe` →
`get_cpe_devices_quantity` → `analyze_wifi_signal_quality` → `finalizing`.

`failed_step` indica en qué paso se detuvo cuando falló.

## Definiciones de métricas (usar estas fórmulas)

- **Tasa de éxito** = autodiagnósticos con `status = 'finished'` ÷ total.
- **Tasa de falla** = `status = 'failed'` ÷ total.
- **Tasa de escalamiento** = `status = 'canceled'` ÷ total (los que generaron ticket).
- **Resolución autónoma** = el autodiagnóstico resolvió sin generar ticket
  (`final_outcome = 'ALL_OK'`, o `status = 'finished'` sin ticket asociado).
- **Tiempo de resolución del ticket** = usar `ticket_resolucion_horas`,
  considerando SOLO tickets con `ticket_stage = 'Solved'` (los no resueltos
  distorsionan el promedio).
- **Duración del proceso** = `duration_seconds` (o `duracion_min` en minutos).

## Reglas de análisis

1. Cuando pidan porcentajes, calcularlos en la misma consulta (no dejar que el
   usuario los deduzca).
2. Al agrupar por tiempo (mes, semana, día, hora), usar `started_at`.
3. Excluir filas con fecha vacía en análisis temporales
   (`started_at IS NOT NULL`).
4. En rankings ("cuál es el que más/menos..."), incluir siempre el **conteo**
   junto al porcentaje o promedio, para dar contexto del volumen.
5. Si una pregunta se puede responder de dos formas (ej. "fallidos" puede ser
   `status='failed'` o `final_outcome='ERROR'`), elegir la más literal y
   mencionarlo en la respuesta.
6. Los promedios sobre pocos registros son poco confiables: si un grupo tiene
   menos de 30 casos, mencionarlo al interpretarlo.

## Contexto de negocio útil

- Las 6 ciudades cubiertas son de la costa Caribe colombiana: Barranquilla,
  Cartagena, Montería, Santa Marta, Sincelejo y Turbaco.
- El objetivo del autodiagnóstico es que el cliente resuelva solo, sin generar
  ticket. Por eso un `ALL_OK` alto y un escalamiento bajo son buenas señales.
- Un mismo cliente puede hacer varios autodiagnósticos; si repite mucho en poco
  tiempo, suele indicar que su problema no se resolvió.
