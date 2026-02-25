@echo off
chcp 65001 > nul 2>&1
cls
echo =============================================================
echo    STARTING FULL SYSTEM - Security
echo =============================================================
echo.
echo Starting:
echo   1. Telegram Bot
echo   2. Web Interface
echo.
echo Two windows will open - DO NOT CLOSE THEM!
echo.
pause

start "Security - Telegram Bot" cmd /k "start_bot.bat"

timeout /t 3 /nobreak > nul

start "Security - Web Admin" cmd /k "start_web.bat"

cls
echo.
echo =============================================================
echo    SYSTEM STARTED
echo =============================================================
echo.
echo Bot: Running in first window
echo Web: http://127.0.0.1:5000
echo.
echo Default admin credentials:
echo   User ID: 1
echo   Password: Abh3var4@
echo.
echo To stop: Close both windows or press Ctrl+C
echo.

pause
