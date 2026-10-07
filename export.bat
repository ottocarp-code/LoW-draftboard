@echo off
REM Noodexport: de draft tot nu toe als Excel, ook als de app vastzit of niet draait.
REM Leest data\draft.db read-only en opent het bestand in exports\.
cd /d "%~dp0"
set "PY=py"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" tool\export_xlsx.py --open %*
pause
