from __future__ import annotations

import os
from typing import Any, Protocol

import httpx

from joborchestrator.scanning.models import JobPosting
from joborchestrator.scanning.normalization import compute_content_hash, first_value, html_to_text

DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_RETRIES = int(os.getenv("JOB_PROVIDER_RETRIES", "1"))


class ProviderError(RuntimeError):
    pass


class JobProvider(Protocol):
    source: str

    async def list_jobs(self, company_ref: str, company_name: str | None = None) -> list[JobPosting]:
        ...

    async def get_job_detail(
        self,
        company_ref: str,
        external_id: str,
        company_name: str | None = None,
    ) -> JobPosting | None:
        ...


class BaseProvider:
    source = "base"

    def __init__(self, timeout: float = DEFAULT_TIMEOUT_SECONDS, retries: int = DEFAULT_RETRIES) -> None:
        self.timeout = timeout
        self.retries = max(0, int(retries))

    async def _get_json(self, url: str, **kwargs: Any) -> Any:
        return await self._request_json("get", url, **kwargs)

    async def _post_json(self, url: str, payload: dict[str, Any]) -> Any:
        return await self._request_json("post", url, json=payload)

    async def _request_json(self, method: str, url: str, **kwargs: Any) -> Any:
        timeout = httpx.Timeout(self.timeout)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            request = getattr(client, method)
            attempts = self.retries + 1
            for attempt in range(attempts):
                try:
                    response = await request(url, **kwargs)
                    response.raise_for_status()
                    return response.json()
                except httpx.HTTPStatusError as exc:
                    if _retryable_status(exc.response.status_code) and attempt < self.retries:
                        continue
                    raise ProviderError(
                        f"{self.source} returned HTTP {exc.response.status_code} for {url} after {attempt + 1} attempts"
                    ) from exc
                except httpx.TimeoutException as exc:
                    if attempt < self.retries:
                        continue
                    raise ProviderError(
                        f"{self.source} timed out after {self.timeout}s for {url} after {attempt + 1} attempts"
                    ) from exc
                except httpx.HTTPError as exc:
                    if attempt < self.retries:
                        continue
                    raise ProviderError(f"{self.source} request failed for {url} after {attempt + 1} attempts: {exc}") from exc
                except ValueError as exc:
                    raise ProviderError(f"{self.source} returned invalid JSON for {url}") from exc
        raise ProviderError(f"{self.source} request failed for {url}")

    def _finalize(self, job: JobPosting) -> JobPosting:
        job.content_hash = compute_content_hash(
            job.title,
            job.company,
            job.location,
            job.description_text or job.description_html,
            job.apply_url,
        )
        return job


class GreenhouseProvider(BaseProvider):
    source = "greenhouse"

    def _jobs_url(self, board_token: str) -> str:
        return f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"

    def _detail_url(self, board_token: str, external_id: str) -> str:
        return f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{external_id}?content=true"

    async def list_jobs(self, company_ref: str, company_name: str | None = None) -> list[JobPosting]:
        data = await self._get_json(self._jobs_url(company_ref))
        jobs = data.get("jobs", []) if isinstance(data, dict) else []
        return [self.normalize_job(job, company_ref, company_name) for job in jobs]

    async def get_job_detail(
        self,
        company_ref: str,
        external_id: str,
        company_name: str | None = None,
    ) -> JobPosting | None:
        data = await self._get_json(self._detail_url(company_ref, external_id))
        if not isinstance(data, dict):
            return None
        return self.normalize_job(data, company_ref, company_name)

    def normalize_job(
        self,
        payload: dict[str, Any],
        company_ref: str,
        company_name: str | None = None,
    ) -> JobPosting:
        description_html = first_value(payload.get("content"), payload.get("description"))
        location = payload.get("location") or {}
        department = payload.get("department") or {}
        offices = payload.get("offices") or []
        workplace_type = None
        if isinstance(offices, list) and offices:
            workplace_type = ", ".join(filter(None, [office.get("name") for office in offices if isinstance(office, dict)])) or None

        job = JobPosting(
            external_id=str(payload.get("id") or payload.get("internal_job_id") or ""),
            source=self.source,
            company=company_name or company_ref,
            title=payload.get("title"),
            location=location.get("name") if isinstance(location, dict) else None,
            workplace_type=workplace_type,
            department=department.get("name") if isinstance(department, dict) else None,
            url=payload.get("absolute_url"),
            apply_url=payload.get("absolute_url"),
            description_html=description_html,
            description_text=html_to_text(description_html),
            posted_at=payload.get("updated_at"),
            raw_payload=payload,
        )
        return self._finalize(job)


class LeverProvider(BaseProvider):
    source = "lever"

    def _jobs_url(self, slug: str) -> str:
        return f"https://api.lever.co/v0/postings/{slug}?mode=json"

    async def list_jobs(self, company_ref: str, company_name: str | None = None) -> list[JobPosting]:
        data = await self._get_json(self._jobs_url(company_ref))
        postings = data if isinstance(data, list) else []
        return [self.normalize_job(job, company_ref, company_name) for job in postings]

    async def get_job_detail(
        self,
        company_ref: str,
        external_id: str,
        company_name: str | None = None,
    ) -> JobPosting | None:
        jobs = await self.list_jobs(company_ref, company_name)
        return next((job for job in jobs if job.external_id == str(external_id)), None)

    def normalize_job(
        self,
        payload: dict[str, Any],
        company_ref: str,
        company_name: str | None = None,
    ) -> JobPosting:
        categories = payload.get("categories") or {}
        lists = payload.get("lists") or []
        list_html = " ".join(
            str(item.get("content", ""))
            for item in lists
            if isinstance(item, dict) and item.get("content")
        )
        description_html = " ".join(
            filter(
                None,
                [
                    payload.get("description"),
                    payload.get("descriptionPlain"),
                    list_html,
                    payload.get("additional"),
                    payload.get("additionalPlain"),
                ],
            )
        ) or None

        job = JobPosting(
            external_id=str(payload.get("id") or ""),
            source=self.source,
            company=company_name or company_ref,
            title=payload.get("text"),
            location=categories.get("location"),
            workplace_type=first_value(payload.get("workplaceType"), categories.get("commitment")),
            department=first_value(categories.get("department"), categories.get("team")),
            url=payload.get("hostedUrl"),
            apply_url=payload.get("applyUrl"),
            description_html=description_html,
            description_text=first_value(payload.get("descriptionPlain"), html_to_text(description_html)),
            posted_at=payload.get("createdAt"),
            raw_payload=payload,
        )
        return self._finalize(job)


class AshbyProvider(BaseProvider):
    source = "ashby"

    def _jobs_url(self, board_name: str) -> str:
        return f"https://api.ashbyhq.com/posting-api/job-board/{board_name}?includeCompensation=true"

    async def list_jobs(self, company_ref: str, company_name: str | None = None) -> list[JobPosting]:
        data = await self._get_json(self._jobs_url(company_ref))
        postings = []
        if isinstance(data, dict):
            postings = first_value(data.get("jobs"), data.get("jobPostings"), data.get("postings")) or []
        return [self.normalize_job(job, company_ref, company_name) for job in postings]

    async def get_job_detail(
        self,
        company_ref: str,
        external_id: str,
        company_name: str | None = None,
    ) -> JobPosting | None:
        jobs = await self.list_jobs(company_ref, company_name)
        return next((job for job in jobs if job.external_id == str(external_id)), None)

    def normalize_job(
        self,
        payload: dict[str, Any],
        company_ref: str,
        company_name: str | None = None,
    ) -> JobPosting:
        location = first_value(payload.get("locationName"), payload.get("location"))
        if not location and isinstance(payload.get("locationNames"), list):
            location = ", ".join(payload["locationNames"]) or None

        compensation = first_value(payload.get("compensation"), payload.get("compensationTierSummary"))
        salary_min = salary_max = salary_currency = None
        if isinstance(compensation, dict):
            salary_min = first_value(compensation.get("minValue"), compensation.get("salaryMin"), compensation.get("min"))
            salary_max = first_value(compensation.get("maxValue"), compensation.get("salaryMax"), compensation.get("max"))
            salary_currency = first_value(compensation.get("currencyCode"), compensation.get("currency"))
        elif isinstance(payload.get("compensationTiers"), list) and payload["compensationTiers"]:
            first_tier = payload["compensationTiers"][0]
            if isinstance(first_tier, dict):
                salary_min = first_value(first_tier.get("minValue"), first_tier.get("min"))
                salary_max = first_value(first_tier.get("maxValue"), first_tier.get("max"))
                salary_currency = first_value(first_tier.get("currencyCode"), first_tier.get("currency"))

        description_html = first_value(payload.get("descriptionHtml"), payload.get("description"), payload.get("jobDescriptionHtml"))
        job = JobPosting(
            external_id=str(first_value(payload.get("id"), payload.get("jobId")) or ""),
            source=self.source,
            company=company_name or company_ref,
            title=payload.get("title"),
            location=location,
            workplace_type=first_value(payload.get("employmentType"), payload.get("workplaceType")),
            department=first_value(payload.get("departmentName"), payload.get("teamName")),
            url=first_value(payload.get("jobUrl"), payload.get("hostedUrl"), f"https://jobs.ashbyhq.com/{company_ref}?ashby_jid={payload.get('id')}"),
            apply_url=first_value(payload.get("applyUrl"), payload.get("jobUrl")),
            description_html=description_html,
            description_text=first_value(payload.get("descriptionPlain"), html_to_text(description_html)),
            salary_min=_to_float(salary_min),
            salary_max=_to_float(salary_max),
            salary_currency=salary_currency,
            posted_at=first_value(payload.get("publishedDate"), payload.get("createdAt"), payload.get("postedAt")),
            raw_payload=payload,
        )
        return self._finalize(job)


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _retryable_status(status_code: int) -> bool:
    return status_code == 429 or status_code >= 500


PROVIDERS: dict[str, JobProvider] = {
    "greenhouse": GreenhouseProvider(),
    "lever": LeverProvider(),
    "ashby": AshbyProvider(),
}


def get_provider(source_type: str) -> JobProvider | None:
    return PROVIDERS.get((source_type or "").lower())


async def list_jobs_for_source(
    source_type: str,
    company_ref: str,
    company_name: str | None = None,
) -> list[JobPosting]:
    provider = get_provider(source_type)
    if provider is None:
        raise ProviderError(f"Unsupported provider: {source_type}")
    return await provider.list_jobs(company_ref, company_name)
