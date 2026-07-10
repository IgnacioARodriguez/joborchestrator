from __future__ import annotations

import os
import base64
from datetime import datetime
from typing import Any, Protocol

from joborchestrator.scanning.models import JobPosting
from joborchestrator.scanning.normalization import compute_content_hash, first_value, html_to_text
from joborchestrator.scanning.providers import BaseProvider, ProviderError, _to_float


class SearchProvider(Protocol):
    source: str

    async def search_jobs(
        self,
        query: str,
        location: str | None = None,
        *,
        remote: bool = True,
        page: int = 1,
    ) -> list[JobPosting]:
        ...


class BaseSearchProvider(BaseProvider):
    source = "search"

    def _finalize_search_job(self, job: JobPosting, query: str, location: str | None) -> JobPosting:
        now = datetime.now().isoformat(timespec="seconds")
        job.scraped_at = job.scraped_at or now
        job.posted_at_raw = job.posted_at_raw or job.posted_at
        job.posted_at_confidence = job.posted_at_confidence or "medium"
        job.parse_confidence = job.parse_confidence if job.parse_confidence is not None else 0.82
        job.raw_payload = {
            **(job.raw_payload or {}),
            "search_query": query,
            "search_location": location,
        }
        job.content_hash = compute_content_hash(
            job.title,
            job.company,
            job.location,
            job.description_text or job.description_html,
            job.apply_url,
        )
        return job


class RemotiveSearchProvider(BaseSearchProvider):
    source = "remotive"

    async def search_jobs(
        self,
        query: str,
        location: str | None = None,
        *,
        remote: bool = True,
        page: int = 1,
    ) -> list[JobPosting]:
        if page > 1:
            return []
        data = await self._get_json("https://remotive.com/api/remote-jobs", params={"search": query})
        jobs = data.get("jobs", []) if isinstance(data, dict) else []
        return [self.normalize_job(job, query, location) for job in jobs if _matches_location(job, location, remote)]

    def normalize_job(self, payload: dict[str, Any], query: str, location: str | None) -> JobPosting:
        company = first_value(payload.get("company_name"), payload.get("company")) or "UNKNOWN"
        job = JobPosting(
            external_id=str(first_value(payload.get("id"), payload.get("url")) or ""),
            source=self.source,
            company=company,
            title=payload.get("title"),
            location=first_value(payload.get("candidate_required_location"), payload.get("job_type"), "Remote"),
            workplace_type="Remote",
            url=payload.get("url"),
            apply_url=payload.get("url"),
            description_html=payload.get("description"),
            description_text=html_to_text(payload.get("description")),
            posted_at=payload.get("publication_date"),
            posted_at_raw=payload.get("publication_date"),
            posted_at_confidence="medium",
            raw_payload=payload,
        )
        return self._finalize_search_job(job, query, location)


class ArbeitnowSearchProvider(BaseSearchProvider):
    source = "arbeitnow"

    async def search_jobs(
        self,
        query: str,
        location: str | None = None,
        *,
        remote: bool = True,
        page: int = 1,
    ) -> list[JobPosting]:
        data = await self._get_json("https://www.arbeitnow.com/api/job-board-api", params={"page": page})
        jobs = data.get("data", []) if isinstance(data, dict) else []
        return [
            self.normalize_job(job, query, location)
            for job in jobs
            if _matches_query(job, query) and _matches_location(job, location, remote)
        ]

    def normalize_job(self, payload: dict[str, Any], query: str, location: str | None) -> JobPosting:
        company = first_value(payload.get("company_name"), payload.get("company")) or "UNKNOWN"
        tags = payload.get("tags") if isinstance(payload.get("tags"), list) else []
        job = JobPosting(
            external_id=str(first_value(payload.get("slug"), payload.get("url"), payload.get("id")) or ""),
            source=self.source,
            company=company,
            title=payload.get("title"),
            location=first_value(payload.get("location"), "Europe"),
            workplace_type="Remote" if payload.get("remote") else None,
            department=", ".join(tags[:3]) if tags else None,
            url=payload.get("url"),
            apply_url=payload.get("url"),
            description_html=payload.get("description"),
            description_text=html_to_text(payload.get("description")),
            posted_at=str(payload.get("created_at")) if payload.get("created_at") else None,
            posted_at_raw=str(payload.get("created_at")) if payload.get("created_at") else None,
            posted_at_confidence="medium",
            raw_payload=payload,
        )
        return self._finalize_search_job(job, query, location)


class AdzunaSearchProvider(BaseSearchProvider):
    source = "adzuna"

    async def search_jobs(
        self,
        query: str,
        location: str | None = None,
        *,
        remote: bool = True,
        page: int = 1,
    ) -> list[JobPosting]:
        app_id = os.getenv("ADZUNA_APP_ID")
        app_key = os.getenv("ADZUNA_APP_KEY")
        if not app_id or not app_key:
            raise ProviderError("Adzuna requires ADZUNA_APP_ID and ADZUNA_APP_KEY")

        data = await self._get_json(
            f"https://api.adzuna.com/v1/api/jobs/es/search/{page}",
            params={
                "app_id": app_id,
                "app_key": app_key,
                "what": query,
                "where": location or "Spain",
                "sort_by": "date",
                "content-type": "application/json",
            },
        )
        jobs = data.get("results", []) if isinstance(data, dict) else []
        return [self.normalize_job(job, query, location) for job in jobs]

    def normalize_job(self, payload: dict[str, Any], query: str, location: str | None) -> JobPosting:
        company_data = payload.get("company") if isinstance(payload.get("company"), dict) else {}
        location_data = payload.get("location") if isinstance(payload.get("location"), dict) else {}
        location_name = first_value(location_data.get("display_name"), location)
        job = JobPosting(
            external_id=str(first_value(payload.get("id"), payload.get("redirect_url")) or ""),
            source=self.source,
            company=first_value(company_data.get("display_name"), payload.get("company")) or "UNKNOWN",
            title=payload.get("title"),
            location=location_name,
            workplace_type="Remote" if _contains_remote(payload) else None,
            url=payload.get("redirect_url"),
            apply_url=payload.get("redirect_url"),
            description_text=payload.get("description"),
            salary_min=_to_float(payload.get("salary_min")),
            salary_max=_to_float(payload.get("salary_max")),
            salary_currency="EUR",
            posted_at=payload.get("created"),
            posted_at_raw=payload.get("created"),
            posted_at_confidence="medium",
            raw_payload=payload,
        )
        return self._finalize_search_job(job, query, location)


class TheMuseSearchProvider(BaseSearchProvider):
    source = "themuse"

    async def search_jobs(
        self,
        query: str,
        location: str | None = None,
        *,
        remote: bool = True,
        page: int = 1,
    ) -> list[JobPosting]:
        params: dict[str, Any] = {"page": page, "category": "Software Engineering"}
        if location:
            params["location"] = location
        data = await self._get_json("https://www.themuse.com/api/public/jobs", params=params)
        jobs = data.get("results", []) if isinstance(data, dict) else []
        return [
            self.normalize_job(job, query, location)
            for job in jobs
            if _matches_query(job, query) and _matches_location(job, location, remote)
        ]

    def normalize_job(self, payload: dict[str, Any], query: str, location: str | None) -> JobPosting:
        company_data = payload.get("company") if isinstance(payload.get("company"), dict) else {}
        locations = payload.get("locations") if isinstance(payload.get("locations"), list) else []
        location_name = ", ".join(loc.get("name", "") for loc in locations if isinstance(loc, dict)) or location
        refs = payload.get("refs") if isinstance(payload.get("refs"), dict) else {}
        description_html = payload.get("contents")
        job = JobPosting(
            external_id=str(first_value(payload.get("id"), refs.get("landing_page")) or ""),
            source=self.source,
            company=first_value(company_data.get("name"), "UNKNOWN"),
            title=payload.get("name"),
            location=location_name,
            workplace_type="Remote" if _contains_remote(payload) else None,
            url=refs.get("landing_page"),
            apply_url=refs.get("landing_page"),
            description_html=description_html,
            description_text=html_to_text(description_html),
            posted_at=payload.get("publication_date"),
            posted_at_raw=payload.get("publication_date"),
            posted_at_confidence="medium",
            raw_payload=payload,
        )
        return self._finalize_search_job(job, query, location)


class RemoteOkSearchProvider(BaseSearchProvider):
    source = "remoteok"

    async def search_jobs(
        self,
        query: str,
        location: str | None = None,
        *,
        remote: bool = True,
        page: int = 1,
    ) -> list[JobPosting]:
        if page > 1:
            return []
        data = await self._get_json("https://remoteok.com/api")
        jobs = data[1:] if isinstance(data, list) and data and isinstance(data[0], dict) else data
        postings = jobs if isinstance(jobs, list) else []
        return [
            self.normalize_job(job, query, location)
            for job in postings
            if isinstance(job, dict) and _matches_query(job, query) and _matches_location(job, location, remote)
        ]

    def normalize_job(self, payload: dict[str, Any], query: str, location: str | None) -> JobPosting:
        tags = payload.get("tags") if isinstance(payload.get("tags"), list) else []
        company = first_value(payload.get("company"), payload.get("company_name")) or "UNKNOWN"
        job = JobPosting(
            external_id=str(first_value(payload.get("id"), payload.get("url"), payload.get("slug")) or ""),
            source=self.source,
            company=company,
            title=first_value(payload.get("position"), payload.get("title")),
            location=first_value(payload.get("location"), "Remote"),
            workplace_type="Remote",
            department=", ".join(str(tag) for tag in tags[:3]) if tags else None,
            url=payload.get("url"),
            apply_url=first_value(payload.get("apply_url"), payload.get("url")),
            description_html=payload.get("description"),
            description_text=first_value(payload.get("description"), html_to_text(payload.get("description"))),
            salary_min=_to_float(payload.get("salary_min")),
            salary_max=_to_float(payload.get("salary_max")),
            posted_at=first_value(payload.get("date"), payload.get("epoch")),
            posted_at_raw=str(first_value(payload.get("date"), payload.get("epoch")) or "") or None,
            posted_at_confidence="medium",
            raw_payload=payload,
        )
        return self._finalize_search_job(job, query, location)


class HimalayasSearchProvider(BaseSearchProvider):
    source = "himalayas"

    async def search_jobs(
        self,
        query: str,
        location: str | None = None,
        *,
        remote: bool = True,
        page: int = 1,
    ) -> list[JobPosting]:
        data = await self._get_json(
            "https://himalayas.app/jobs/api/search",
            params={"query": query, "page": page},
        )
        jobs = []
        if isinstance(data, dict):
            jobs = first_value(data.get("jobs"), data.get("data"), data.get("results")) or []
        elif isinstance(data, list):
            jobs = data
        return [
            self.normalize_job(job, query, location)
            for job in jobs
            if isinstance(job, dict) and _matches_location(job, location, remote)
        ]

    def normalize_job(self, payload: dict[str, Any], query: str, location: str | None) -> JobPosting:
        company_data = payload.get("company") if isinstance(payload.get("company"), dict) else {}
        locations = payload.get("locations") if isinstance(payload.get("locations"), list) else []
        location_name = first_value(
            payload.get("location"),
            payload.get("locationRestrictions"),
            ", ".join(str(item.get("name") or item) for item in locations if item) if locations else None,
            location,
            "Remote",
        )
        description_html = first_value(payload.get("description"), payload.get("descriptionHtml"))
        job_url = first_value(payload.get("url"), payload.get("applicationUrl"), payload.get("applyUrl"))
        job = JobPosting(
            external_id=str(first_value(payload.get("id"), payload.get("slug"), job_url) or ""),
            source=self.source,
            company=first_value(company_data.get("name"), payload.get("companyName"), payload.get("company")) or "UNKNOWN",
            title=first_value(payload.get("title"), payload.get("name")),
            location=str(location_name) if location_name else None,
            workplace_type="Remote",
            url=job_url,
            apply_url=first_value(payload.get("applicationUrl"), payload.get("applyUrl"), job_url),
            description_html=description_html,
            description_text=first_value(payload.get("descriptionPlain"), html_to_text(description_html)),
            posted_at=first_value(payload.get("publishedAt"), payload.get("createdAt"), payload.get("postedAt")),
            posted_at_raw=first_value(payload.get("publishedAt"), payload.get("createdAt"), payload.get("postedAt")),
            posted_at_confidence="medium",
            raw_payload=payload,
        )
        return self._finalize_search_job(job, query, location)


class InfoJobsSearchProvider(BaseSearchProvider):
    source = "infojobs"

    async def search_jobs(
        self,
        query: str,
        location: str | None = None,
        *,
        remote: bool = True,
        page: int = 1,
    ) -> list[JobPosting]:
        client_id = os.getenv("INFOJOBS_CLIENT_ID")
        client_secret = os.getenv("INFOJOBS_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise ProviderError("InfoJobs requires INFOJOBS_CLIENT_ID and INFOJOBS_CLIENT_SECRET")
        token = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
        params: dict[str, Any] = {
            "q": query,
            "page": page,
            "maxResults": 50,
        }
        if location:
            params["province"] = location
        data = await self._get_json(
            "https://api.infojobs.net/api/9/offer",
            params=params,
            headers={"Authorization": f"Basic {token}"},
        )
        offers = first_value(data.get("offers"), data.get("items"), data.get("results"), []) if isinstance(data, dict) else []
        return [
            self.normalize_job(offer, query, location)
            for offer in offers
            if isinstance(offer, dict) and _matches_location(offer, location, remote)
        ]

    def normalize_job(self, payload: dict[str, Any], query: str, location: str | None) -> JobPosting:
        company_data = payload.get("author") if isinstance(payload.get("author"), dict) else {}
        city_data = payload.get("city") if isinstance(payload.get("city"), dict) else {}
        province_data = payload.get("province") if isinstance(payload.get("province"), dict) else {}
        salary = payload.get("salary") if isinstance(payload.get("salary"), dict) else {}
        offer_id = str(first_value(payload.get("id"), payload.get("code"), payload.get("link")) or "")
        title = first_value(payload.get("title"), payload.get("name"))
        url = first_value(payload.get("link"), payload.get("url"), f"https://www.infojobs.net/oferta/{offer_id}" if offer_id else None)
        location_name = first_value(
            city_data.get("value"),
            province_data.get("value"),
            payload.get("city"),
            payload.get("province"),
            location,
        )
        job = JobPosting(
            external_id=offer_id or str(url or title or ""),
            source=self.source,
            company=first_value(company_data.get("name"), payload.get("company"), "UNKNOWN"),
            title=title,
            location=location_name,
            workplace_type="Remote" if _contains_remote(payload) else None,
            url=url,
            apply_url=url,
            description_text=first_value(payload.get("description"), payload.get("summary")),
            salary_min=_to_float(first_value(salary.get("minimum"), salary.get("min"))),
            salary_max=_to_float(first_value(salary.get("maximum"), salary.get("max"))),
            salary_currency="EUR",
            posted_at=first_value(payload.get("published"), payload.get("publishedAt"), payload.get("updated")),
            posted_at_raw=first_value(payload.get("published"), payload.get("publishedAt"), payload.get("updated")),
            posted_at_confidence="medium",
            raw_payload=payload,
        )
        return self._finalize_search_job(job, query, location)


SEARCH_PROVIDERS: dict[str, SearchProvider] = {
    "remotive": RemotiveSearchProvider(),
    "arbeitnow": ArbeitnowSearchProvider(),
    "adzuna": AdzunaSearchProvider(),
    "themuse": TheMuseSearchProvider(),
    "remoteok": RemoteOkSearchProvider(),
    "himalayas": HimalayasSearchProvider(),
    "infojobs": InfoJobsSearchProvider(),
}


def get_search_provider(source_type: str) -> SearchProvider | None:
    return SEARCH_PROVIDERS.get((source_type or "").lower())


def provider_requires_configuration(source_type: str) -> bool:
    if source_type == "adzuna":
        return not (os.getenv("ADZUNA_APP_ID") and os.getenv("ADZUNA_APP_KEY"))
    if source_type == "infojobs":
        return not (os.getenv("INFOJOBS_CLIENT_ID") and os.getenv("INFOJOBS_CLIENT_SECRET"))
    return False


def _matches_query(payload: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    text = " ".join(str(value) for value in payload.values() if isinstance(value, (str, int, float)))
    terms = [term for term in query.lower().replace("/", " ").split() if len(term) >= 3]
    return any(term in text.lower() for term in terms)


def _matches_location(payload: dict[str, Any], location: str | None, remote: bool) -> bool:
    if not location and not remote:
        return True
    text = str(payload).lower()
    if remote and any(term in text for term in ["remote", "remoto", "anywhere", "europe"]):
        return True
    if location:
        location_terms = [term for term in location.lower().replace(",", " ").split() if len(term) >= 3]
        return any(term in text for term in location_terms)
    return True


def _contains_remote(payload: dict[str, Any]) -> bool:
    text = str(payload).lower()
    return any(term in text for term in ["remote", "remoto", "anywhere"])
