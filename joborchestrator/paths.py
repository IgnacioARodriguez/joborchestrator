"""Shared filesystem paths for the local application."""

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent

DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = Path(os.getenv("JOB_ORCHESTRATOR_DB_PATH", PROJECT_ROOT / "job_tracker.db"))
SALIDAS_DIR = PROJECT_ROOT / "salidas_todas_posiciones_raw"
LINKEDIN_SCRAPER = PACKAGE_DIR / "scanning" / "linkedin.py"
