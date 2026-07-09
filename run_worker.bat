@echo off
cd /d "%~dp0"
echo Starting Job Orchestrator CV/profile worker...
echo Logs: %CD%\logs\worker.log
echo.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m joborchestrator.worker
) else (
  python -m joborchestrator.worker
)
echo.
echo Worker stopped. Check logs\worker.log for details.
pause
