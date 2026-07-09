@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m joborchestrator.ranking.worker
) else (
  python -m joborchestrator.ranking.worker
)
pause
