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
| `ALL_OK_WITH_WARNINGS` | Bien, pero con advertencias. |
| `TICKET_CREATED` | Se generó un ticket para revisión manual. |
| `CREDIT_RECHARGED` | Se le recargó crédito al cliente. |
| `BLOCKED` | El proceso se bloqueó (ej. el cliente ya tenía un incidente abierto). |
| `CANCELED` | El proceso se canceló. |
| `ERROR` | Ocurrió un error técnico. |

**Ojo:** este dato empezó a capturarse recientemente por lo que solo tiene información de agosto 2026, así que los
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

**Importante:** esta columna solo tiene valor cuando `status = 'failed'`. Los
autodiagnósticos que terminaron bien no tienen causa (es NULL), así que al
analizar causas se está mirando únicamente el universo de los fallidos.

Códigos técnicos, en inglés, ordenados por frecuencia real:

| Código | Casos | Qué significa |
|---|---|---|
| `KRILL_POST_FAILED` | 9.274 | Falló el registro en el sistema Krill. Es la causa #1 y **es una falla interna del sistema, no del módem del cliente**. |
| `PING_BATCH_RETRY_FAILED` | 5.313 | Fallaron los reintentos de ping al módem. |
| `CLIENT_HAS_OPEN_INCIDENT` | 4.507 | El cliente ya tenía un incidente/ticket abierto. |
| `CPE_OFFLINE` | 1.822 | El módem está apagado o desconectado. |
| `CPE_STATE_NOT_UP` | 1.790 | El módem no está en estado operativo. |
| `CPE_LOSS_OF_SIGNAL` | 1.750 | El módem perdió señal de fibra (LOS). |
| `CREDIT_EXPIRED` | 1.620 | El crédito del cliente estaba vencido. |
| `CPE_GPON_POWER_LOW` | 975 | Potencia óptica baja (señal débil de fibra). |
| `NO_INTERNET_BALANCE` | 606 | El cliente no tenía saldo de internet. |
| `TIMEOUT_EXCEEDED` | 583 | El proceso se pasó del tiempo máximo. |
| `CLIENT_AFFECTED_BY_KRILL_ALARM` | 572 | El cliente está afectado por una falla masiva conocida. |
| `PING_NOT_COMPLETE` | 568 | El ping al módem no se completó. |
| `DAILY_CREDIT_LIMIT_REACHED` | 321 | Se alcanzó el límite diario de crédito. |
| `CANCELED_FOR_ADVISOR` | 245 | El asesor canceló el proceso. |
| `CPE_NOT_FOUND` | 223 | No se encontró el módem del cliente en el sistema. |
| `AUTO_REPAIR_FAILED` | 215 | Falló la reparación automática. |
| `RUN_IPPING_DIAGNOSTIC_FAILED` | 79 | Falló el diagnóstico de ping al módem. |
| `PING_NOT_NEW_OR_INVALID` | 62 | El ping no era válido o ya estaba registrado. |
| `CLIENT_STATUS_INACTIVE` | 38 | El cliente está inactivo (ej. suspendido). |
| `CLIENT_NOT_FOUND` | 24 | No se encontró el cliente en el sistema. |
| `PING_NO_SUCCESS` | 12 | El ping al módem no tuvo respuesta. |

## Cómo se lee un pico de autodiagnósticos

Los dos picos más grandes del histórico son el mejor ejemplo de cómo hay que
analizarlos, y de por qué **una sola dimensión engaña**. Ambos fueron
98%–100% `KRILL_POST_FAILED` (cuando lo habitual de esa causa a esas horas era
2%–19%), pero al mirar la ciudad se ve que no fueron el mismo fenómeno:

| | 16 de julio, 5–9 a.m. | 30 de julio, 9–12 a.m. |
|---|---|---|
| Volumen | 519 en una hora (habitual: 2) | 494 en una hora (habitual: 13) |
| Causa | 100% `KRILL_POST_FAILED` | 97% `KRILL_POST_FAILED` |
| Ciudad | **Cartagena 94%** (habitual 36%) | **Sincelejo 68% + Montería 30%** (habitual: Cartagena 63%) |
| Canal | Portal 96% | **WhatsApp 62%** (habitual 16%) |

**Cómo interpretarlo:** que el 94% de los casos venga de una sola ciudad NO es
lo que se vería si el sistema Krill se hubiera caído globalmente — eso afectaría
a todas las ciudades por igual. Lo que dicen los datos es que **el evento que
originó el pico fue local** (algo pasó en Cartagena, y luego en
Sincelejo/Montería) **y que además ninguno de esos autodiagnósticos pudo
registrarse en Krill**. Cuál de las dos cosas causó la otra no se puede deducir
de esta tabla; lo que sí se puede afirmar es dónde ocurrió.

**Regla para analizar cualquier pico:** mirar siempre las tres dimensiones
juntas y comparar cada una con su peso habitual a esa misma hora.

1. **Causa** (`failure_reason`) — qué falló.
2. **Ciudad** (`nombre_ciudad`) — si se concentra en una o dos ciudades, apunta a
   un evento de red local; si se reparte como siempre, apunta a un problema
   transversal del sistema.
3. **Canal** (`source`) — por dónde entraron. En el evento del 30 de julio el
   canal se volcó a WhatsApp (62% cuando lo habitual era 16%), señal de que en
   los eventos masivos la gente recurre al bot.

Comparar contra "lo habitual de esa misma hora" es indispensable: el canal
`portal` es el 90% del tráfico total, así que verlo como mayoría no dice nada;
lo que informa es que **cambie** su peso.

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
2. Al agrupar por tiempo (mes, semana, día, hora), usar `started_at`. Las fechas
   ya vienen convertidas a **hora local de Colombia (UTC−5)**, así que "las 8 de
   la noche" en los datos es de verdad las 8 de la noche para el cliente.
3. Excluir filas con fecha vacía en análisis temporales
   (`started_at IS NOT NULL`).
4. En rankings ("cuál es el que más/menos..."), incluir siempre el **conteo**
   junto al porcentaje o promedio, para dar contexto del volumen.
5. Si una pregunta se puede responder de dos formas (ej. "fallidos" puede ser
   `status='failed'` o `final_outcome='ERROR'`), elegir la más literal y
   mencionarlo en la respuesta.
6. Los promedios sobre pocos registros son poco confiables: si un grupo tiene
   menos de 30 casos, mencionarlo al interpretarlo.

## Cómo se mueve el día (patrón horario normal)

En hora de Colombia, un día típico se comporta así: la madrugada está casi
vacía (entre 2 y 4 a.m. suele haber 0–3 autodiagnósticos por hora), a partir de
las 10 a.m. empieza a subir, y el mayor movimiento va de la tarde a la noche
(entre 5 y 9 p.m. está el pico habitual). Por eso, para saber si una hora tuvo
mucho movimiento hay que compararla con **esa misma hora** en días anteriores, no
con el promedio del día completo: si no, todas las noches parecerían anormales.

Cuando en una hora se disparan los autodiagnósticos muy por encima de lo
habitual, casi siempre significa una **falla masiva** (varios clientes sin
servicio a la vez) o una campaña/comunicación que empujó a la gente a
diagnosticar. Ejemplo real: el 30 de julio de 2026 a las 9 a.m. hubo 494
autodiagnósticos en una sola hora, cuando lo habitual a esa hora eran 13.

## Contexto de negocio útil

- Las 6 ciudades cubiertas son de la costa Caribe colombiana: Barranquilla,
  Cartagena, Montería, Santa Marta, Sincelejo y Turbaco.
- El objetivo del autodiagnóstico es que el cliente resuelva solo, sin generar
  ticket. Por eso un `ALL_OK` alto y un escalamiento bajo son buenas señales.
- Un mismo cliente puede hacer varios autodiagnósticos; si repite mucho en poco
  tiempo, suele indicar que su problema no se resolvió.
