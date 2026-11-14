@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo  === Листок: локальний запуск ===
echo.

set "PY="
py -3.13 -c "pass" >nul 2>nul && set "PY=py -3.13"
if not defined PY py -3.12 -c "pass" >nul 2>nul && set "PY=py -3.12"
if not defined PY python -c "pass" >nul 2>nul && set "PY=python"
if not defined PY (
  echo  [ПОМИЛКА] Python не знайдено. Встановіть Python 3.13 з python.org
  echo  і поставте галочку "Add python.exe to PATH".
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo  Створюю віртуальне середовище .venv ...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo  [ПОМИЛКА] Не вдалося створити .venv.
    pause
    exit /b 1
  )
)

echo  Перевіряю залежності (перший раз 1-3 хвилини) ...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
  echo  [ПОМИЛКА] Не вдалося встановити залежності. Надішліть скриншот цього вікна.
  pause
  exit /b 1
)

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo.
  echo  Створено файл .env. Зараз він відкриється в Блокноті:
  echo  вставте ключі, збережіть ^(Ctrl+S^), закрийте Блокнот і запустіть run_local.bat ще раз.
  notepad ".env"
  pause
  exit /b 0
)

echo.
echo  Сервер запускається. Браузер відкриється сам: http://127.0.0.1:5000
echo  Щоб зупинити сервер, закрийте це вікно.
echo.
start "" /min cmd /c "timeout /t 4 >nul & start "" http://127.0.0.1:5000"
".venv\Scripts\python.exe" app.py
pause
