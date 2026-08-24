@echo off
rem ============================================================
rem  Manda un correo de PRUEBA para comprobar que la alerta
rem  quedo bien configurada. Doble clic a este archivo.
rem
rem  Pregunta a que correo mandarlo, asi que la prueba no le
rem  llega al equipo completo: solo a quien uno diga.
rem
rem  Nota para quien edite: no usar parentesis en los mensajes
rem  de echo, cmd.exe los interpreta como fin de bloque.
rem ============================================================

cd /d "%~dp0"

echo.
echo  ============================================
echo   Prueba del correo de alerta
echo  ============================================
echo.
echo  Antes de seguir, el archivo .env debe tener
echo  llenas estas dos lineas:
echo.
echo     SMTP_USUARIO=la.cuenta.que.envia@fibrazo.com
echo     SMTP_CLAVE=lacontrasenadeaplicacion
echo.

if not exist ".venv\Scripts\python.exe" goto sin_entorno
if not exist ".env" goto sin_env

set "CORREO="
set /p CORREO=  A que correo quieres que llegue la prueba?
if "%CORREO%"=="" goto sin_correo

echo.
echo  Enviando a %CORREO% ...
echo.
".venv\Scripts\python.exe" alertas.py --probar-envio --solo-a "%CORREO%"
echo.
goto fin

:sin_correo
echo.
echo  No escribiste ningun correo. No envie nada.
goto fin

:sin_env
echo  ----------------------------------------------------------
echo  ERROR: no encuentro el archivo .env en esta carpeta.
echo.
echo  Copia el archivo .env.example, renombralo a .env
echo  y llena las dos lineas de arriba.
echo  ----------------------------------------------------------
goto fin

:sin_entorno
echo  ----------------------------------------------------------
echo  ERROR: no encuentro el entorno de Python en .venv
echo  ----------------------------------------------------------

:fin
echo.
pause
