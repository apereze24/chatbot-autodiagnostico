@echo off
rem ============================================================
rem  Abre el Chatbot de Autodiagnostico en el navegador.
rem  Solo hay que hacerle doble clic a este archivo.
rem
rem  La ventana negra que se abre es el motor de la aplicacion:
rem  hay que dejarla abierta mientras se usa el chatbot.
rem  Para cerrar el chatbot, se cierra esa ventana.
rem
rem  Nota para quien edite este archivo: no usar parentesis en
rem  los mensajes de echo ni bloques if con parentesis, porque
rem  cmd.exe los interpreta como fin de bloque y rompe el script.
rem ============================================================

rem Nos movemos a la carpeta donde esta este archivo, para que
rem encuentre app.py y la configuracion sin importar desde donde
rem se haya abierto.
cd /d "%~dp0"

echo.
echo  Abriendo el Chatbot de Autodiagnostico...
echo  Se va a abrir solo en el navegador en unos segundos.
echo.
echo  NO CIERRES esta ventana mientras uses el chatbot.
echo.

rem Verificamos que el entorno de Python este instalado.
if not exist ".venv\Scripts\streamlit.exe" goto sin_entorno

".venv\Scripts\streamlit.exe" run app.py
goto fin

:sin_entorno
echo  ----------------------------------------------------------
echo  ERROR: no encuentro el entorno de Python en la carpeta .venv
echo.
echo  Parece que falta instalarlo. Abre PowerShell en esta misma
echo  carpeta y ejecuta estas dos lineas, una por una:
echo.
echo     py -m venv .venv
echo     .venv\Scripts\python -m pip install -r requirements.txt
echo  ----------------------------------------------------------
echo.
pause
exit /b 1

:fin
echo.
echo  El chatbot se cerro.
pause
