"""
Portal Scanner — ATS Provider Modules (Level 2 APIs)

Handles direct API calls to Greenhouse, Ashby, Lever, Workday, BambooHR, etc.
"""

import httpx
import json
from typing import Optional, List, Dict
from datetime import datetime
import asyncio


class ATSProvider:
    """Base class for ATS providers."""
    
    def __init__(self, company: str, timeout: int = 30):
        self.company = company
        self.timeout = timeout
        self.session = httpx.AsyncClient(timeout=timeout)
    
    async def fetch_jobs(self) -> List[Dict]:
        """Fetch jobs from this provider. Returns [{ title, url, location, job_id }]"""
        raise NotImplementedError


class GreenhouseProvider(ATSProvider):
    """Greenhouse Boards API: https://boards-api.greenhouse.io/v1/boards/{company}/jobs"""
    
    def __init__(self, company: str, api_url: Optional[str] = None):
        super().__init__(company)
        # api_url should be like: https://boards-api.greenhouse.io/v1/boards/anthropic/jobs
        self.api_url = api_url or f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs"
    
    async def fetch_jobs(self) -> List[Dict]:
        try:
            resp = await self.session.get(self.api_url)
            resp.raise_for_status()
            data = resp.json()
            
            jobs = []
            for job in data.get("jobs", []):
                jobs.append({
                    "title": job.get("title", ""),
                    "url": job.get("absolute_url", ""),
                    "location": job.get("location", {}).get("name", "Remote"),
                    "job_id": str(job.get("id", "")),
                    "posted_at": job.get("posted_at", ""),
                    "department": job.get("department", {}).get("name", ""),
                })
            
            return jobs
        except Exception as e:
            print(f"[Greenhouse] Error fetching jobs for {self.company}: {e}")
            return []


class AshbyProvider(ATSProvider):
    """Ashby GraphQL API (via jobs.ashbyhq.com)"""
    
    def __init__(self, company: str):
        super().__init__(company)
        self.api_url = "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobBoardWithTeams"
    
    async def fetch_jobs(self) -> List[Dict]:
        try:
            query = """
            query ApiJobBoardWithTeams($organizationHostedJobsPageName: String!) {
              jobBoard(organizationHostedJobsPageName: $organizationHostedJobsPageName) {
                jobPostings {
                  id
                  title
                  locationNames
                  employmentType
                }
              }
            }
            """
            
            payload = {
                "operationName": "ApiJobBoardWithTeams",
                "variables": {
                    "organizationHostedJobsPageName": self.company
                },
                "query": query
            }
            
            resp = await self.session.post(self.api_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            
            jobs = []
            job_postings = data.get("data", {}).get("jobBoard", {}).get("jobPostings", [])
            for job in job_postings:
                url = f"https://jobs.ashbyhq.com/{self.company}?ashby_jid={job.get('id', '')}"
                jobs.append({
                    "title": job.get("title", ""),
                    "url": url,
                    "location": ", ".join(job.get("locationNames", ["Remote"])),
                    "job_id": job.get("id", ""),
                    "employment_type": job.get("employmentType", ""),
                })
            
            return jobs
        except Exception as e:
            print(f"[Ashby] Error fetching jobs for {self.company}: {e}")
            return []


class LeverProvider(ATSProvider):
    """Lever API: https://api.lever.co/v0/postings/{company}?mode=json"""
    
    def __init__(self, company: str):
        super().__init__(company)
        self.api_url = f"https://api.lever.co/v0/postings/{company}?mode=json"
    
    async def fetch_jobs(self) -> List[Dict]:
        try:
            resp = await self.session.get(self.api_url)
            resp.raise_for_status()
            data = resp.json()
            
            jobs = []
            for job in data:
                jobs.append({
                    "title": job.get("text", ""),
                    "url": job.get("hostedUrl", job.get("applyUrl", "")),
                    "location": job.get("categories", {}).get("location", "Remote"),
                    "job_id": job.get("id", ""),
                    "team": job.get("categories", {}).get("team", ""),
                })
            
            return jobs
        except Exception as e:
            print(f"[Lever] Error fetching jobs for {self.company}: {e}")
            return []


class WorkdayProvider(ATSProvider):
    """Workday CXS API"""
    
    def __init__(self, company: str, workday_url: Optional[str] = None):
        super().__init__(company)
        # URL format: https://{company}.{shard}.myworkdayjobs.com/wday/cxs/{company}/{site}/jobs
        # Shard defaults to 'wd1' or 'wd5'
        self.workday_url = workday_url
    
    async def fetch_jobs(self) -> List[Dict]:
        if not self.workday_url:
            return []
        
        try:
            payload = {
                "appliedFacets": {},
                "limit": 100,
                "offset": 0,
                "searchText": ""
            }
            
            resp = await self.session.post(self.workday_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            
            jobs = []
            for job in data.get("jobPostings", []):
                url = f"{self.workday_url.rsplit('/', 1)[0]}/{job.get('id', '')}"
                jobs.append({
                    "title": job.get("title", ""),
                    "url": url,
                    "location": job.get("location", ""),
                    "job_id": job.get("id", ""),
                })
            
            return jobs
        except Exception as e:
            print(f"[Workday] Error fetching jobs: {e}")
            return []


class BambooHRProvider(ATSProvider):
    """BambooHR careers API"""
    
    def __init__(self, company: str, domain: str):
        super().__init__(company)
        self.domain = domain  # e.g., "company.bamboohr.com"
    
    async def fetch_jobs(self) -> List[Dict]:
        try:
            # Fetch list
            list_url = f"https://{self.domain}/careers/list"
            resp = await self.session.get(list_url)
            resp.raise_for_status()
            
            # Parse HTML (simplified — real code would use BeautifulSoup)
            # For now, return empty and note this needs HTML parsing
            return []
        except Exception as e:
            print(f"[BambooHR] Error fetching jobs for {self.company}: {e}")
            return []


async def get_provider(api_provider: str, company: str, api_url: Optional[str] = None) -> Optional[ATSProvider]:
    """Factory function to get the right provider based on api_provider type."""
    
    if api_provider == "greenhouse":
        return GreenhouseProvider(company, api_url)
    elif api_provider == "ashby":
        return AshbyProvider(company)
    elif api_provider == "lever":
        return LeverProvider(company)
    elif api_provider == "workday":
        return WorkdayProvider(company, api_url)
    elif api_provider == "bamboohr":
        return BambooHRProvider(company, api_url or "")
    else:
        return None


async def fetch_all_providers(companies: List[Dict]) -> Dict[str, List[Dict]]:
    """Fetch jobs from all configured companies (Level 2)."""
    
    results = {}
    tasks = []
    
    for company_cfg in companies:
        if not company_cfg.get("enabled", True):
            continue
        
        api_provider = company_cfg.get("api_provider")
        api_url = company_cfg.get("api")
        company_name = company_cfg.get("name", "")
        
        if not api_provider:
            continue
        
        provider = await get_provider(api_provider, company_name, api_url)
        if provider:
            tasks.append(fetch_single(provider, company_name, results))
    
    if tasks:
        await asyncio.gather(*tasks)
    
    return results


async def fetch_single(provider: ATSProvider, company_name: str, results: Dict):
    """Fetch jobs from a single provider."""
    jobs = await provider.fetch_jobs()
    results[company_name] = jobs
    print(f"✓ {company_name}: {len(jobs)} jobs found")
