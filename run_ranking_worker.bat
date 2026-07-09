@echo off
cd /d "%~dp0"
echo Starting Job Orchestrator NVIDIA ranking worker...
echo Logs: %CD%\logs\ranking-worker.log
echo.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m joborchestrator.ranking.worker
) else (
  python -m joborchestrator.ranking.worker
)
echo.
echo Ranking worker stopped. Check logs\ranking-worker.log for details.
pause
