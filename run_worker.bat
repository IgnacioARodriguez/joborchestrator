@echo off
cd /d "%~dp0"
echo Starting Job Orchestrator local operation worker...
echo Uses Turso when TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are set in .env.
echo This is the worker used by v0/API for scans, materials, and application dry-runs.
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
