import asyncio
import time

from joborchestrator.scanning import scanner
from joborchestrator.scanning.models import ScanResult


def test_scan_sources_concurrently_respects_parallelism(monkeypatch):
    async def fake_scan_source_row(source):
        await asyncio.sleep(0.1)
        return ScanResult(
            source_type=source["provider"],
            company_name=source["company_name"],
            company_ref=source["company_ref"],
        )

    monkeypatch.setattr(scanner, "scan_source_row", fake_scan_source_row)
    sources = [
        {"id": i, "provider": "greenhouse", "company_name": f"Company {i}", "company_ref": f"company-{i}"}
        for i in range(4)
    ]

    started = time.perf_counter()
    results = asyncio.run(scanner.scan_sources_concurrently(sources, max_concurrency=4))
    elapsed = time.perf_counter() - started

    assert len(results) == 4
    assert elapsed < 0.25
