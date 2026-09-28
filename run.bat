@echo off
REM LoW Draftboard lokaal starten. Open daarna http://localhost:8000
REM Met LOW_VALUES kan je een ander values.json kiezen, bv. de testfixture:
REM   set LOW_VALUES=tests\fixtures\values.json
REM   run.bat
cd /d "%~dp0"
if "%LOW_VALUES%"=="" if not exist "output\values.json" (
  echo output\values.json ontbreekt.
  echo Draai eerst:  py tool\fetch_espn.py   en dan   py tool\build_values.py
  echo De app start toch, en toont dezelfde melding tot het bestand er is.
)
py -m uvicorn main:app --app-dir app --host 127.0.0.1 --port 8000
pause
