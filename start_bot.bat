@echo off
chcp 65001 >nul
echo Запуск Telegram бота...
cd /d "%~dp0"
call venv\Scripts\activate.bat
python bot.py
pause
