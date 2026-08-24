# Cómo activar el correo de alerta

Guía para dejar funcionando el aviso al equipo de CX cuando los autodiagnósticos
se disparan en una hora. No hace falta saber programar: es copiar y pegar valores
en dos pantallas.

## Qué hace, en una frase

Cada hora, un programa revisa la última hora completa de datos. Si en esa hora se
ejecutaron **el doble o más** de los autodiagnósticos que suele haber a esa misma
hora, y además se salió de su rango normal, manda un correo con el desglose:
cuántos fueron, qué falló, en qué ciudad y por qué canal entraron.

Con ese criterio suena **alrededor de una vez al día** (33 veces en los últimos
30 días). Si en cambio avisara con solo superar la mediana, serían 13 correos
diarios: por definición, la mitad de las horas supera la mediana.

## Quién recibe el aviso

- mbustamante@fibrazo.com
- busuga@fibrazo.com
- jgaravito@fibrazo.com
- jmantilla@fibrazo.com
- ammunoz@fibrazo.com

Para cambiar la lista no hay que tocar el código: se pone el secret
`ALERTA_DESTINATARIOS` con los correos separados por coma.

---

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
