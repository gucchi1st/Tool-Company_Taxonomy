@echo off
cd /d "%~dp0"
if not exist ".venv-playwright\Scripts\python.exe" python -m venv .venv-playwright
if errorlevel 1 goto failed
".venv-playwright\Scripts\python.exe" -m pip install -r requirements-playwright.txt
if errorlevel 1 goto failed
echo Ready. Run start.bat and choose chrome or msedge.
echo For bundled Chromium, run: .venv-playwright\Scripts\python.exe -m playwright install chromium
pause
exit /b 0
:failed
echo Installation failed. Check Python and network access.
pause
exit /b 1
