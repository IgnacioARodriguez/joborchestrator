"""Shared filesystem paths for the local application."""

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent

DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = PROJECT_ROOT / "job_tracker.db"
PORTALS_FILE = PROJECT_ROOT / "portals.yml"
SALIDAS_DIR = PROJECT_ROOT / "salidas_todas_posiciones_raw"
LINKEDIN_SCRAPER = PACKAGE_DIR / "scanning" / "linkedin.py"

