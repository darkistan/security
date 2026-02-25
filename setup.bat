@echo off
chcp 65001 > nul 2>&1
cls
echo =============================================================
echo    SETUP - Security
echo =============================================================
echo.
echo Цей скрипт встановить та налаштує систему Security
echo.

REM Перевірка Python
echo [1/5] Перевірка Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python не знайдено!
    echo Будь ласка, встановіть Python 3.8 або новіший
    pause
    exit /b 1
)
python --version
echo OK

REM Створення віртуального середовища
echo.
echo [2/5] Створення віртуального середовища...
if exist venv (
    echo Віртуальне середовище вже існує, пропускаємо...
) else (
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Не вдалося створити віртуальне середовище
        pause
        exit /b 1
    )
    echo OK
)

REM Активація віртуального середовища та встановлення залежностей
echo.
echo [3/5] Встановлення залежностей...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Не вдалося активувати віртуальне середовище
    pause
    exit /b 1
)
python -m pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Не вдалося встановити залежності
    pause
    exit /b 1
)
echo OK

REM Створення config.env
echo.
echo [4/5] Налаштування конфігурації...
if exist config.env (
    echo Файл config.env вже існує, пропускаємо...
) else (
    copy config.env.example config.env >nul
    echo Створено config.env на основі config.env.example
    echo.
    echo ВАЖЛИВО: Відредагуйте config.env та встановіть:
    echo   - TELEGRAM_BOT_TOKEN (отримайте у @BotFather)
    echo   - FLASK_SECRET_KEY (згенеруйте через: python generate_secret_key.py)
    echo.
)
echo OK

REM Ініціалізація БД
echo.
echo [5/5] Ініціалізація бази даних...
python -c "from database import init_database; init_database()"
if errorlevel 1 (
    echo ERROR: Не вдалося ініціалізувати базу даних
    pause
    exit /b 1
)
echo OK

echo.
echo =============================================================
echo    SETUP ЗАВЕРШЕНО
echo =============================================================
echo.
echo Наступні кроки:
echo   1. Відредагуйте config.env та встановіть:
echo      - TELEGRAM_BOT_TOKEN
echo      - FLASK_SECRET_KEY (згенеруйте: python generate_secret_key.py)
echo.
echo   2. Запустіть систему:
echo      - start_all.bat (запустить бота та веб-інтерфейс)
echo      - або окремо: start_bot.bat та start_web.bat
echo.
echo   3. Увійдіть у веб-інтерфейс:
echo      - Адреса: http://127.0.0.1:5000
echo      - User ID: 1
echo      - Пароль: Abh3var4@
echo.
pause
