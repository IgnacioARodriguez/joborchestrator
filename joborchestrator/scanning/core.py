"""
Portal Scanner — Core Logic

Handles filtering, deduplication, and scan history management.
"""

import csv
import re
from datetime import datetime
from typing import List, Dict, Optional, Set, Tuple
import pandas as pd

from joborchestrator.paths import DATA_DIR

SCAN_HISTORY_FILE = DATA_DIR / "scan_history.tsv"


def ensure_data_dir():
    """Ensure data/ directory exists."""
    DATA_DIR.mkdir(exist_ok=True)
    SCAN_HISTORY_FILE.touch(exist_ok=True)


def init_scan_history():
    """Initialize scan_history.tsv with headers if empty."""
    ensure_data_dir()
    
    if SCAN_HISTORY_FILE.stat().st_size == 0:
        with open(SCAN_HISTORY_FILE, "w", newline="") as f:
            writer = csv.writer(f, delimiter="\t")
            writer.writerow([
                "url", "first_seen", "portal", "title", "company", "status", "location"
            ])


def load_scan_history() -> Set[str]:
    """Load all seen URLs from scan_history.tsv."""
    init_scan_history()
    seen_urls = set()
    
    try:
        df = pd.read_csv(SCAN_HISTORY_FILE, sep="\t")
        seen_urls = set(df["url"].unique())
    except Exception as e:
        print(f"Warning: Could not load scan history: {e}")
    
    return seen_urls


def load_evaluated_urls() -> Set[str]:
    """Load URLs from persistence database (already evaluated)."""
    try:
        from joborchestrator.storage import persistence as db

        conn = db._conn()
        rows = conn.execute("SELECT DISTINCT url FROM ofertas WHERE url IS NOT NULL").fetchall()
        conn.close()
        return {r[0] for r in rows}
    except Exception as e:
        print(f"Warning: Could not load evaluated URLs: {e}")
        return set()


def normalize_url(url: str) -> str:
    """Normalize URL for comparison."""
    return url.strip().lower().rstrip("/")


def filter_by_title(jobs: List[Dict], title_filter: Dict) -> Tuple[List[Dict], List[Dict]]:
    """
    Filter jobs by title criteria.
    Returns (passed_jobs, filtered_jobs)
    """
    positive_keywords = [k.lower() for k in title_filter.get("positive", [])]
    negative_keywords = [k.lower() for k in title_filter.get("negative", [])]
    
    passed = []
    filtered = []
    
    for job in jobs:
        title_lower = job.get("title", "").lower()
        
        # Check negative keywords first
        if any(neg in title_lower for neg in negative_keywords):
            filtered.append(job)
            continue
        
        # Check positive keywords
        if positive_keywords and not any(pos in title_lower for pos in positive_keywords):
            filtered.append(job)
            continue
        
        passed.append(job)
    
    return passed, filtered


def filter_by_location(jobs: List[Dict], location_filter: Dict) -> Tuple[List[Dict], List[Dict]]:
    """
    Filter jobs by location criteria.
    Returns (passed_jobs, filtered_jobs)
    """
    if not location_filter:
        return jobs, []
    
    block_keywords = [k.lower() for k in location_filter.get("block", [])]
    allow_keywords = [k.lower() for k in location_filter.get("allow", [])]
    
    passed = []
    filtered = []
    
    for job in jobs:
        location = job.get("location", "").lower()
        
        # If location is empty, pass it
        if not location:
            passed.append(job)
            continue
        
        # Check block keywords first
        if any(block in location for block in block_keywords):
            filtered.append(job)
            continue
        
        # Check allow keywords
        if allow_keywords and not any(allow in location for allow in allow_keywords):
            filtered.append(job)
            continue
        
        passed.append(job)
    
    return passed, filtered


def deduplicate_jobs(jobs: List[Dict], seen_urls: Set[str], evaluated_urls: Set[str]) -> Tuple[List[Dict], List[Dict]]:
    """
    Deduplicate jobs against seen URLs and evaluated URLs.
    Returns (new_jobs, duplicates)
    """
    new_jobs = []
    duplicates = []
    
    for job in jobs:
        normalized = normalize_url(job.get("url", ""))
        
        if normalized in seen_urls or normalized in evaluated_urls:
            duplicates.append(job)
        else:
            new_jobs.append(job)
    
    return new_jobs, duplicates


def record_scan_result(job: Dict, company: str, portal: str, status: str, location: str = ""):
    """Record a job in scan_history.tsv."""
    init_scan_history()
    
    url = job.get("url", "")
    title = job.get("title", "")
    
    with open(SCAN_HISTORY_FILE, "a", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow([
            url,
            datetime.now().isoformat(),
            portal,
            title,
            company,
            status,
            location
        ])


def extract_company_from_title(title: str) -> str:
    """Extract company name from WebSearch result title."""
    # Pattern: "Job Title @ Company" or "Job Title at Company" or "Job Title | Company"
    patterns = [
        r"(?:^|.+?)\s+@\s+(.+?)$",  # "Title @ Company"
        r"(?:^|.+?)\s+at\s+(.+?)$",  # "Title at Company"
        r"(?:^|.+?)\s+\|\s+(.+?)$",  # "Title | Company"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    
    return "Unknown"


def generate_scan_report(
    new_jobs: int,
    filtered_by_title: int,
    filtered_by_location: int,
    duplicates: int,
    expired: int
) -> str:
    """Generate a summary report of the scan."""
    
    report = f"""
🔍 Portal Scan Report — {datetime.now().strftime('%Y-%m-%d %H:%M')}
{'='*60}

📊 Statistics:
  • Offers found: {new_jobs + filtered_by_title + filtered_by_location + duplicates + expired}
  • New & added: {new_jobs}
  • Filtered (title): {filtered_by_title}
  • Filtered (location): {filtered_by_location}
  • Duplicates: {duplicates}
  • Expired: {expired}

{'='*60}
    """
    
    return report


def get_scan_history_df() -> pd.DataFrame:
    """Get scan history as DataFrame."""
    init_scan_history()
    
    try:
        df = pd.read_csv(SCAN_HISTORY_FILE, sep="\t")
        return df
    except Exception as e:
        print(f"Warning: Could not load scan history DataFrame: {e}")
        return pd.DataFrame()


def filter_by_salary(jobs: List[Dict], salary_config: Dict) -> Tuple[List[Dict], List[Dict]]:
    """
    Filtra ofertas por rango salarial.
    
    salary_config esperado:
    {
        "min_salary": 50000,
        "max_salary": 200000,
        "currency": "USD"
    }
    
    Retorna (passed_jobs, filtered_out)
    """
    if not salary_config or not salary_config.get("min_salary"):
        return jobs, []
    
    import re
    passed = []
    filtered = []
    min_sal = salary_config.get("min_salary", 0)
    max_sal = salary_config.get("max_salary", float('inf'))
    
    for job in jobs:
        # Intenta extraer salary del job
        salary_min = job.get("salary_min")
        salary_max = job.get("salary_max")
        salary_str = job.get("salario", "") or job.get("salary", "")
        
        # Si no hay salary data, pasa el job
        if not salary_min and not salary_max and not salary_str:
            passed.append(job)
            continue
        
        # Intenta parsear salary_str si es string (ej: "$50k-$100k")
        if isinstance(salary_min, str) or isinstance(salary_max, str):
            try:
                numbers = re.findall(r'\d+', str(salary_min) + " " + str(salary_max))
                if numbers:
                    salary_min = int(numbers[0]) * 1000 if len(numbers[0]) < 3 else int(numbers[0])
                    salary_max = int(numbers[-1]) * 1000 if len(numbers[-1]) < 3 else int(numbers[-1])
            except (ValueError, IndexError):
                salary_min = None
                salary_max = None
        
        # Valida rango
        if salary_min and salary_max:
            midpoint = (salary_min + salary_max) / 2
            if min_sal <= midpoint <= max_sal:
                passed.append(job)
            else:
                filtered.append(job)
        else:
            # Si no puedo parsear, dejo pasar
            passed.append(job)
    
    return passed, filtered
