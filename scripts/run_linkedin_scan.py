from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from joborchestrator.scanning import linkedin
from joborchestrator.scanning.linkedin_importer import LINKEDIN_SOURCE, import_linkedin_dataframe_to_job_postings
from joborchestrator.storage import persistence as db


async def run() -> dict:
    started = datetime.now().isoformat(timespec="seconds")
    timer = time.perf_counter()
    status = "success"
    error = None
    import_result = {"new": 0, "updated": 0, "seen": 0, "total": 0}
    inactive_count = 0

    try:
        df = await linkedin.run_linkedin_scrape()
        if not df.empty:
            import_result = import_linkedin_dataframe_to_job_postings(df)
        inactive_count = db.mark_jobs_inactive_by_last_seen(
            LINKEDIN_SOURCE,
            linkedin.FRESHNESS_WINDOW_SECONDS,
        )
    except Exception as exc:
        status = "error"
        error = str(exc)
        raise
    finally:
        finished = datetime.now().isoformat(timespec="seconds")
        duration = round(time.perf_counter() - timer, 3)
        searches = []
        try:
            searches = linkedin.load_profile_busquedas()
        except Exception:
            searches = []
        if not searches:
            searches = [{"keywords": "profile", "ubicacion": "profile"}]
        for search in searches:
            db.record_scan_event(
                source_id=None,
                provider=LINKEDIN_SOURCE,
                company_name=str(search.get("keywords", "LinkedIn")),
                company_ref=str(search.get("ubicacion", "LinkedIn")),
                started_at=started,
                finished_at=finished,
                status=status,
                found_count=int(import_result.get("total", 0)),
                new_count=int(import_result.get("new", 0)),
                updated_count=int(import_result.get("updated", 0)),
                unchanged_count=int(import_result.get("seen", 0)),
                error=error,
                duration_seconds=duration,
            )

    return {**import_result, "inactive": inactive_count, "status": status}


if __name__ == "__main__":
    result = asyncio.run(run())
    print(result)
