@echo off
cd /d "%~dp0"
echo Instalando lo necesario (solo tarda la primera vez)...
python -m pip install -q -r requirements.txt
python -m playwright install chromium
start "" http://localhost:8000
python app.py
pause
