# Mantenimiento de la alerta automática

> **Este archivo existe para ser editado.** Editarlo es, literalmente, el
> mantenimiento: cada edición cuenta como actividad del repositorio y reinicia el
> reloj de los 60 días que GitHub usa para desactivar las tareas programadas.

## Por qué hay que hacer algo

La alerta de picos corre sola cada hora gracias a una tarea programada en GitHub
Actions. Pero **en los repositorios públicos, GitHub desactiva las tareas
programadas cuando el repositorio pasa 60 días sin actividad.** No es una falla:
es una medida de GitHub para no gastar recursos en proyectos abandonados.

Si eso pasa, la alerta **deja de enviarse en silencio**. No hay error, no hay
correo de aviso al equipo: simplemente no vuelve a llegar nada, y es fácil
confundirlo con "no ha habido picos".

## La rutina: una vez cada 45 días

Cuarenta y cinco, no sesenta, para tener margen.

**Lo más práctico: pon un recordatorio recurrente cada 45 días en tu calendario**
que diga *"Editar MANTENIMIENTO.md del chatbot"*, con el enlace a este archivo en
GitHub. Toma un minuto y no requiere saber programar.

### Cómo hacerlo, desde el navegador

1. Abre este archivo en GitHub:
   `https://github.com/apereze24/chatbot-autodiagnostico/blob/main/MANTENIMIENTO.md`
2. Arriba a la derecha del contenido, haz clic en el **ícono del lápiz**
   (*Edit this file*).
3. Baja hasta la bitácora del final y **agrega una línea nueva** con la fecha de
   hoy y quién la revisó.
4. Botón verde **Commit changes...** → otra vez **Commit changes**.

Con eso el repositorio registra actividad y el reloj vuelve a cero. No hay que
instalar nada ni abrir la terminal.

## Y de paso, revisa que esté viva

Aprovecha el mismo momento para confirmar que la alerta está corriendo. Entra a
la pestaña **Actions** del repositorio y mira la lista de corridas:

| Lo que ves | Qué significa |
|---|---|
| Corridas cada ~2 minutos que dicen **workflow_dispatch**, con visto verde | Todo bien. Es el disparador de cron-job.org. |
| Solo aparecen corridas **Scheduled**, unas pocas al día | El disparador externo se cayó: la alerta sigue viva pero **ya no avisa a tiempo**. Revisa cron-job.org y el token (abajo). |
| La última corrida es de hace días o semanas | La tarea se desactivó. Ver abajo cómo reactivarla. |
| Un aviso amarillo diciendo que el workflow está deshabilitado | Confirmado: se desactivó. |
| Corridas en rojo | Está corriendo pero algo falla. Abre la corrida y lee el último paso. |

Las corridas **Scheduled** son solo un respaldo: GitHub las ejecuta pocas veces
al día y no garantizan avisos a tiempo. Lo que hace puntual a la alerta es el
disparador de cron-job.org (instrucciones en `ALERTA-CORREO.md`).

## El token del disparador vence

El disparador de cron-job.org usa un token de GitHub con fecha de vencimiento.
**Cuando vence, cron-job.org empieza a fallar y la alerta vuelve a avisar con
horas de atraso**, sin que el programa falle. Si en cron-job.org activaste el
aviso de fallas, te llegará un correo. Para renovarlo:

1. GitHub → foto → **Settings** → **Developer settings** → **Personal access
   tokens** → **Fine-grained tokens** → `disparador-alerta-autodiagnostico` →
   **Regenerate token**, con un año más.
2. Copia el token nuevo y pégalo en cron-job.org, en el encabezado
   `Authorization` (`Bearer ` + token). Guarda y haz **Test run**: debe dar 204.
3. Anota la nueva fecha de vencimiento en la bitácora de abajo.

**Vencimiento actual del token:** _(anotar al crearlo)_

## Si ya se desactivó: cómo reactivarla

1. Repositorio → pestaña **Actions**
2. En la columna de la izquierda, **Alerta de picos de autodiagnóstico**
3. Aparecerá un mensaje diciendo que el workflow está deshabilitado, con un
   botón **Enable workflow**. Haz clic.
4. Lánzala una vez a mano (**Run workflow**, modo `revisar`) para confirmar que
   volvió a andar.
5. Y edita este archivo, para que el reloj arranque de nuevo desde hoy.

## Qué NO cuenta como actividad

Para que no te confíes: comentar un issue, poner una estrella o simplemente
visitar el repositorio **no cuentan**. Lo que cuenta es modificar el repositorio
—un commit, un merge, una publicación—. Por eso la rutina es editar este archivo
y no solo entrar a mirar.

---

## Bitácora de revisiones

Agrega una línea cada vez. La más reciente arriba.

| Fecha | Quién | Notas |
|---|---|---|
| 2026-11-04 | Alejandro | La alerta pasa a leer en vivo y a dispararse cada 2 min desde cron-job.org. Falta anotar el vencimiento del token. |
| 2026-10-13 | Alejandro | Alerta puesta en marcha y verificada desde Actions. |
