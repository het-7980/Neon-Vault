@echo off
setlocal
cd /d "%~dp0"
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 goto run_py
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 goto run_python
echo Neon Vault needs Python 3.10 or newer.
echo Install Python, reopen your terminal, and run play.bat again.
exit /b 1

:run_py
py -3 "%~dp0game.py" %*
exit /b %errorlevel%

:run_python
python "%~dp0game.py" %*
exit /b %errorlevel%
