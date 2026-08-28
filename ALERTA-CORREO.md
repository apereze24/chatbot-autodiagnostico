# Cómo activar el aviso de alerta

Guía para dejar funcionando el aviso al equipo de CX cuando los autodiagnósticos
se disparan en una hora. No hace falta saber programar: es copiar y pegar valores
en dos pantallas.

Hay **dos canales** y son independientes: se puede usar uno, el otro, o los dos.
Si están los dos y uno se cae, el otro sigue avisando.

| Canal | Ventaja | Desventaja |
|---|---|---|
| **Google Chat** (recomendado) | No necesita credenciales de correo, remitente verificado ni DNS. No puede caer en spam. Todo queda dentro del Workspace de la empresa. | Hay que crear un espacio y un webhook. |
| **Correo** | Llega a la bandeja de entrada de siempre. | Necesita un servidor de correo que permita envío automático. |

> **Lección aprendida (agosto 2026):** se intentó primero con una cuenta personal
> de Gmail y Google la bloqueó en cuatro días, con tres errores distintos
> (`535 BadCredentials`, cuenta suspendida por política, `534 WebLoginRequired`).
> **Una cuenta personal de Gmail no sirve para envío automático** y no hay
> configuración que lo arregle. Para correo hace falta un relay interno de la
> empresa o un servicio de correo transaccional (Brevo, SMTP2GO).

---

## Opción A: Google Chat (la más robusta)

Un webhook es la vía que Google provee justamente para que un programa publique
mensajes en un espacio. Es lo contrario de lo que nos bloquearon.

1. Abre **Google Chat** y crea un espacio para el equipo, por ejemplo
   *Alertas Autodiagnóstico*. Invita a quienes deban enterarse.
2. Dentro del espacio, haz clic en el **nombre del espacio** (arriba) para abrir
   el menú → **Apps e integraciones**.
3. **Webhooks** → **Agregar webhook**.
4. Nombre: `Termómetro de Autodiagnóstico`. (Si quieres, ponle un avatar con una
   URL de imagen; es opcional.)
5. **Guardar**. Google muestra una **URL** larga que empieza con
   `https://chat.googleapis.com/...`. **Cópiala**: es la única vez que se ve
   cómoda de copiar, aunque se puede volver a consultar en el mismo menú.
6. En GitHub → **Settings** → **Secrets and variables** → **Actions** →
   **New repository secret**:
   - Name: `CHAT_WEBHOOK_URL`
   - Secret: la URL que copiaste
7. **Actions** → **Run workflow** → modo `revisar`. Si en ese momento hay un
   pico, el mensaje aparece en el espacio. Para probar sin esperar un pico, usa
   `--dia` y `--hora` de un día que sí tuvo pico (ver más abajo).

Esa URL es una credencial: cualquiera que la tenga puede publicar en el espacio.
Por eso va como secret y no en el código.

---

## Qué hace, en una frase

Cada hora, un programa revisa la última hora completa de datos. Si en esa hora se
ejecutaron **el doble o más** de los autodiagnósticos que suele haber a esa misma
hora, y además se salió de su rango normal, manda un correo con el desglose:
cuántos fueron, qué falló, en qué ciudad y por qué canal entraron.

Con ese criterio suena **alrededor de una vez al día** (33 veces en los últimos
30 días). Si en cambio avisara con solo superar la mediana, serían 13 correos
diarios: por definición, la mitad de las horas supera la mediana.

## Quién recibe el aviso

La lista **no está en el código**: vive en el secret `ALERTA_DESTINATARIOS` de
GitHub, con los correos separados por coma. Es a propósito, porque este
repositorio es público y una lista de correos corporativos a la vista es material
para spam y phishing dirigido. GitHub nunca muestra el contenido de un secret.

Para cambiar quién recibe los avisos, se edita ese secret. Nada más.

Si el secret falta o queda vacío, el programa **no envía a nadie en silencio**:
falla, lo dice en el registro y GitHub avisa de la falla. Eso es a propósito: el
peor escenario posible sería creer que la alerta está funcionando cuando en
realidad no le llega a nadie.

## Que la alerta no se apague sola

En los repositorios públicos GitHub desactiva las tareas programadas tras 60 días
sin actividad, y la alerta dejaría de enviarse sin avisar. La rutina para
evitarlo —un minuto cada 45 días— está en **`MANTENIMIENTO.md`**.

---

## Opción B: correo

## Paso 1: conseguir una contraseña de aplicación

El programa necesita una cuenta de correo desde la cual enviar. **Se recomienda
una cuenta dedicada** (por ejemplo `alertas@fibrazo.com`) en vez de la cuenta
personal de alguien: así los avisos no llegan "de parte de" una persona y no se
rompen si esa persona sale de la empresa.

Con Gmail o Google Workspace **no sirve la contraseña normal** de la cuenta: hay
que crear una contraseña de aplicación.

1. Entrar a https://myaccount.google.com/apppasswords con la cuenta que enviará.
2. Si pide activar la verificación en dos pasos, activarla primero.
3. En "Nombre de la aplicación" escribir algo como `Alerta autodiagnostico`.
4. Google muestra una clave de 16 letras, en 4 grupos. **Esa es la clave.**
   Se copia sin los espacios.

> Si la organización tiene bloqueadas las contraseñas de aplicación, el
> administrador de Google Workspace puede habilitarlas, o dar los datos del
> servidor SMTP interno de la empresa (servidor, puerto, usuario y clave). El
> programa funciona igual: solo cambian los valores de `SMTP_HOST` y `SMTP_PORT`.

## Paso 2: probar el envío desde tu computador (opcional pero recomendado)

Así se comprueba que la clave funciona antes de configurar nada más.

1. Abrir el archivo `.env` de la carpeta del proyecto (si no existe, copiar
   `.env.example` y renombrarlo a `.env`).
2. Llenar estas dos líneas:

   ```
   SMTP_USUARIO=alertas@fibrazo.com
   SMTP_CLAVE=lasdieciseisletras
   ```

3. Abrir PowerShell en la carpeta del proyecto y ejecutar, **cambiando el correo
   por el tuyo**:

   ```powershell
   .venv\Scripts\python alertas.py --probar-envio --solo-a tu.correo@fibrazo.com
   ```

Debe llegar un correo verde que dice "La alerta quedó configurada". Si falla, el
programa explica qué salió mal.

> ⚠️ El `--solo-a` es importante mientras se prueba: sin él, el correo va a las
> cinco personas de la lista.

## Paso 3: configurar los secrets en GitHub

Esto es lo que hace que la alerta funcione **sola, cada hora**, con la app
cerrada. La app de Streamlit no sirve para esto: solo se ejecuta cuando alguien
tiene la página abierta.

1. Entrar al repositorio en GitHub: `apereze24/chatbot-autodiagnostico`.
2. Arriba, pestaña **Settings** (la del repositorio, no la del perfil).
3. En el menú de la izquierda: **Secrets and variables** → **Actions**.
4. Botón verde **New repository secret**, y crear uno por uno:

| Name (el nombre exacto) | Secret (el valor) |
|---|---|
| `REDASH_URL` | la dirección de Redash, sin `/` al final |
| `REDASH_QUERY_ID` | el número de la consulta |
| `REDASH_API_KEY` | la API key de Redash |
| `SMTP_USUARIO` | la cuenta que envía, ej. `alertas@fibrazo.com` |
| `SMTP_CLAVE` | la contraseña de aplicación del Paso 1 |
| `ALERTA_URL_APP` | el enlace de la app, para el botón del correo |

Los tres valores de Redash son **los mismos** que ya están en el archivo `.env`
local y en los Secrets de Streamlit Cloud.

Opcionales, solo si se necesitan:

| Name | Para qué |
|---|---|
| `ALERTA_DESTINATARIOS` | cambiar quién recibe (correos separados por coma) |
| `SMTP_HOST` / `SMTP_PORT` | si no es Gmail (por defecto `smtp.gmail.com` y `587`) |

## Paso 4: comprobar que quedó andando

1. En el repositorio, pestaña **Actions**.
2. En la izquierda, elegir **Alerta de picos de autodiagnóstico**.
3. Botón **Run workflow** → **Run workflow**. Eso la ejecuta de una vez, sin
   esperar la hora.
4. Al terminar, hacer clic en la corrida para leer el registro. Va a decir una de
   estas cosas:
   - `Esa hora está dentro de lo normal. No hay nada que avisar.` → todo bien,
     simplemente no hay pico en este momento.
   - `PICO: ... Correo enviado a 5 personas` → hay un pico y el correo salió.
   - Un error de credenciales → revisar los secrets.

De ahí en adelante corre sola cada hora.

### Ver un aviso de verdad, sin esperar un pico

El modo `probar-envio` manda un mensaje de confirmación, pero no un aviso real.
Para ver cómo llega una alerta de verdad, se puede reproducir un pico conocido:
en **Run workflow**, además del modo `revisar`, se llenan los campos **dia**
(AAAA-MM-DD) y **hora** (0 a 23). Eso revisa solo esa hora y avisa por los
canales configurados, igual que en vivo.

Sirve también para depurar: si algún día un pico no llegó, se reproduce esa hora
y se ve en el registro exactamente qué pasó. Reproducir una hora **no altera** el
seguimiento normal: el puntero de "hasta dónde revisé" no se mueve.

---

## Preguntas que suelen salir

**¿Cuánto tarda en avisar?**
El aviso llega unos 10 minutos después de que termina la hora. Se revisan horas
completas a propósito: avisar de una hora a medias sería avisar con la mitad de
los casos.

**Si el pico dura toda la mañana, ¿llegan diez correos?**
No. Llega el primero y después uno cada 3 horas, y el asunto dice "Sigue el pico
· 3ª hora seguida" para distinguirlo de un evento nuevo. Se cambia con el secret
`ALERTA_CADA_N_HORAS`.

**¿Puede avisar de algo viejo?**
No. Si el dato de Redash viene con más de 6 horas de atraso, no envía nada: sería
una alerta sobre algo ya pasado.

**¿Y si quiero que avise más seguido, o menos?**
El único número que hay que mover está en `analisis.py`: `FACTOR_PICO = 2.0`
significa "el doble de lo habitual". Subirlo a 3 hace que avise menos; bajarlo,
más. Bajarlo a 1 equivale a "superar la mediana", que son 13 correos diarios.

**¿Dónde se ve lo mismo sin correo?**
En la app, pestaña **Termómetro por hora**. Es exactamente el mismo análisis: el
correo y la pantalla usan el mismo código, así que nunca dicen cosas distintas.
