"""
Portal Scanner — Main Orchestrator

Combines Level 0-3 scanning methods into a unified pipeline.
"""

import asyncio
import yaml
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

import pandas as pd

import providers
import scan_core
import trust_validator
import archetype_detector
import repost_detector


PORTALS_FILE = Path("portals.yml")


def load_portals_config() -> Dict:
    """Load portals.yml configuration."""
    if not PORTALS_FILE.exists():
        print(f"Warning: {PORTALS_FILE} not found. Creating default...")
        # Will be created by user
        return {"tracked_companies": [], "search_queries": []}
    
    with open(PORTALS_FILE) as f:
        return yaml.safe_load(f) or {}


def get_enabled_companies(config: Dict) -> List[Dict]:
    """Get enabled companies from config."""
    companies = config.get("tracked_companies", [])
    return [c for c in companies if c.get("enabled", True)]


async def scan_level_2_apis(config: Dict) -> Dict[str, List[Dict]]:
    """
    LEVEL 2: Fetch jobs from public ATS APIs (Greenhouse, Ashby, Lever, etc.)
    
    Returns: { company_name: [jobs] }
    """
    print("\n🔗 LEVEL 2: Fetching from ATS APIs...")
    
    companies = get_enabled_companies(config)
    all_jobs = {}
    
    # Filter companies with API endpoints
    api_companies = [c for c in companies if c.get("api_provider")]
    
    if not api_companies:
        print("  No companies with API endpoints configured.")
        return {}
    
    # Fetch all in parallel
    results = await providers.fetch_all_providers(api_companies)
    
    return results


def scan_level_1_playwright(config: Dict) -> Dict[str, List[Dict]]:
    """
    LEVEL 1: Direct Playwright navigation (currently stubbed)
    
    For companies without APIs or as fallback.
    In production, would use Playwright to navigate careers_url.
    """
    print("\n🌐 LEVEL 1: Playwright scanning (requires Playwright + browser)...")
    print("  ⚠️  Level 1 requires browser automation (would use jobscrapping.py logic)")
    return {}


def scan_level_0_local_parsers(config: Dict) -> Dict[str, List[Dict]]:
    """
    LEVEL 0: Run local parsers (currently stubbed)
    
    For companies with custom parsing scripts.
    """
    print("\n📝 LEVEL 0: Running local parsers...")
    print("  (Configure parsers: in portals.yml)")
    return {}


def apply_filters(jobs: List[Dict], config: Dict) -> tuple:
    """
    Apply title and location filters from config.
    Returns (passed_jobs, stats)
    """
    title_filter = config.get("title_filter", {})
    location_filter = config.get("location_filter", {})
    
    stats = {
        "input": len(jobs),
        "filtered_by_title": 0,
        "filtered_by_location": 0,
        "output": 0,
    }
    
    if not jobs:
        return jobs, stats
    
    # Title filter
    passed, filtered_title = scan_core.filter_by_title(jobs, title_filter)
    stats["filtered_by_title"] = len(filtered_title)
    jobs = passed
    
    # Location filter
    passed, filtered_location = scan_core.filter_by_location(jobs, location_filter)
    stats["filtered_by_location"] = len(filtered_location)
    stats["output"] = len(passed)
    
    return passed, stats


def deduplicate_against_history(jobs: List[Dict]) -> tuple:
    """
    Deduplicate against scan history and evaluated offers.
    Returns (new_jobs, duplicate_count)
    """
    seen_urls = scan_core.load_scan_history()
    evaluated_urls = scan_core.load_evaluated_urls()
    
    new_jobs, duplicates = scan_core.deduplicate_jobs(
        jobs, seen_urls, evaluated_urls
    )
    
    return new_jobs, len(duplicates)


async def run_full_scan(config: Optional[Dict] = None) -> Dict:
    """
    Execute full portal scan (Levels 0-3).
    Returns scan results and statistics.
    """
    
    if config is None:
        config = load_portals_config()
    
    print("\n" + "="*70)
    print("🔍 PORTAL SCANNER — Full Scan")
    print("="*70)
    
    scan_core.ensure_data_dir()
    
    all_jobs_by_company = {}
    all_jobs_flat = []
    total_stats = {
        "input_total": 0,
        "filtered_by_title": 0,
        "filtered_by_location": 0,
        "duplicates": 0,
        "new_jobs": 0,
    }
    
    # ===== LEVEL 0: Local Parsers =====
    level_0_results = scan_level_0_local_parsers(config)
    
    # ===== LEVEL 1: Playwright (if needed) =====
    # level_1_results = scan_level_1_playwright(config)
    
    # ===== LEVEL 2: APIs (PRIMARY) =====
    level_2_results = await scan_level_2_apis(config)
    all_jobs_by_company.update(level_2_results)
    
    # Flatten all jobs
    for company, jobs in all_jobs_by_company.items():
        for job in jobs:
            job["company"] = company
            all_jobs_flat.append(job)
        total_stats["input_total"] += len(jobs)
    
    print(f"\n📋 Total jobs found from APIs: {total_stats['input_total']}")
    
    # ===== FILTER BY TITLE & LOCATION =====
    filtered_jobs, filter_stats = apply_filters(all_jobs_flat, config)
    total_stats["filtered_by_title"] = filter_stats["filtered_by_title"]
    total_stats["filtered_by_location"] = filter_stats["filtered_by_location"]
    
    print(f"✓ After filtering: {filter_stats['output']} jobs")
    
    # ===== DEDUPLICATE =====
    new_jobs, dup_count = deduplicate_against_history(filtered_jobs)
    total_stats["duplicates"] = dup_count
    total_stats["new_jobs"] = len(new_jobs)
    
    print(f"✓ After dedup: {len(new_jobs)} new jobs")
    
    # ===== RECORD IN HISTORY =====
    for job in new_jobs:
        scan_core.record_scan_result(
            job,
            job.get("company", "Unknown"),
            "API",
            "added",
            job.get("location", "")
        )
    
    # ===== GENERATE REPORT =====
    report = scan_core.generate_scan_report(
        new_jobs=len(new_jobs),
        filtered_by_title=total_stats["filtered_by_title"],
        filtered_by_location=total_stats["filtered_by_location"],
        duplicates=total_stats["duplicates"],
        expired=0
    )
    
    print(report)
    
    return {
        "new_jobs": new_jobs,
        "stats": total_stats,
        "report": report,
    }


def apply_trust_validation(jobs: List[Dict]) -> Dict:
    """
    Aplica validación de confianza a todas las ofertas.
    Retorna dict con jobs marcados y estadísticas.
    """
    validated = trust_validator.batch_validate_jobs(jobs)
    
    safe_jobs = [j for j in validated if j["trust_validation"]["trust_score"] >= 70]
    warning_jobs = [j for j in validated if 40 <= j["trust_validation"]["trust_score"] < 70]
    danger_jobs = [j for j in validated if j["trust_validation"]["trust_score"] < 40]
    
    return {
        "validated_jobs": validated,
        "safe": safe_jobs,
        "warning": warning_jobs,
        "danger": danger_jobs,
        "stats": {
            "total": len(jobs),
            "safe_count": len(safe_jobs),
            "warning_count": len(warning_jobs),
            "danger_count": len(danger_jobs),
        }
    }


def apply_archetype_detection(jobs: List[Dict]) -> Dict:
    """
    Detecta archetype para todas las ofertas.
    Retorna dict con jobs clasificados.
    """
    detected = archetype_detector.batch_detect_archetypes(jobs)
    
    archetypes = {}
    for job in detected:
        arch = job["archetype_detection"]["primary_archetype"]
        if arch not in archetypes:
            archetypes[arch] = []
        archetypes[arch].append(job)
    
    return {
        "classified_jobs": detected,
        "by_archetype": archetypes,
        "stats": {
            "total": len(jobs),
            "archetypes_found": len(archetypes),
            "distribution": {k: len(v) for k, v in archetypes.items()}
        }
    }


def apply_repost_detection(jobs: List[Dict]) -> Dict:
    """
    Detecta ofertas que fueron republicadas.
    Retorna dict con jobs marcados.
    """
    marked = repost_detector.mark_repost_status(jobs)
    
    unique = [j for j in marked if j["repost_info"]["status"] == "unique"]
    masters = [j for j in marked if j["repost_info"]["status"] == "master"]
    reposts = [j for j in marked if j["repost_info"]["status"] == "repost"]
    
    return {
        "marked_jobs": marked,
        "unique": unique,
        "masters": masters,
        "reposts": reposts,
        "stats": {
            "total": len(jobs),
            "unique_count": len(unique),
            "master_count": len(masters),
            "repost_count": len(reposts),
            "duplicate_savings": len(reposts),
        }
    }


def apply_salary_filter(jobs: List[Dict], config: Dict) -> Dict:
    """
    Filtra ofertas por rango salarial desde portals.yml
    """
    if not config:
        return {"passed": jobs, "filtered": [], "stats": {"total": len(jobs), "filtered": 0}}
    
    passed, filtered = scan_core.filter_by_salary(jobs, config.get("salary_filter", {}))
    
    return {
        "passed": passed,
        "filtered": filtered,
        "stats": {
            "total": len(jobs),
            "passed": len(passed),
            "filtered_out": len(filtered),
        }
    }


def get_scan_history_df() -> pd.DataFrame:
    """Get scan history as DataFrame for display."""
    return scan_core.get_scan_history_df()


if __name__ == "__main__":
    # Test: Run full scan
    result = asyncio.run(run_full_scan())
    print(f"\nResult: {len(result['new_jobs'])} new jobs found")
