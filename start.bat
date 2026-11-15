@echo off
cd /d "%~dp0"
if exist ".venv-playwright\Scripts\python.exe" (
    ".venv-playwright\Scripts\python.exe" app.py
) else (
    python app.py
)
if errorlevel 1 pause
