@echo off
chcp 65001 >nul
echo Запуск веб-інтерфейсу...
cd /d "%~dp0"
call venv\Scripts\activate.bat
python run_web.py
pause
