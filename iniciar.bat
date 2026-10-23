@echo off
REM Conversor Nacional Software -> IPS D20 Digital
REM Crea el entorno la primera vez, instala dependencias y abre la aplicacion en el navegador.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Creando entorno virtual...
    py -3 -m venv .venv || python -m venv .venv
    call ".venv\Scripts\python.exe" -m pip install --upgrade pip
    call ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
set APP_SIN_LOGIN=1
".venv\Scripts\python.exe" -m streamlit run app.py
pause
