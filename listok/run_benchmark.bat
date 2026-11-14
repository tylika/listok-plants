@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo  Заміри Flash vs Pro на фото з папки demo_photos ...
".venv\Scripts\python.exe" scripts\benchmark.py demo_photos
echo.
echo  Результати: папка benchmark_results (results.csv відкривається в Excel)
pause
