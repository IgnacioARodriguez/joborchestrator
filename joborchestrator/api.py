from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from joborchestrator.api_dto import (
    job_dto,
    latest_rankings_by_job_id,
    parse_json_value,
    scan_result_dto,
)
from joborchestrator.batching import MIN_DESCRIPCION_LEN_DEFAULT, filtrar_ofertas
from joborchestrator.intelligence.application_materials import ApplicationMaterialsError, build_application_kit
from joborchestrator.intelligence.cv_profile_extractor import (
    CVProfileError,
    extract_text_from_cv,
    normalize_profile_payload,
)
from joborchestrator.intelligence.llm_application_materials import (
    DEFAULT_MATERIALS_MODEL,
    LLMMaterialsError,
    build_application_kit_with_llm,
)
from joborchestrator.paths import SALIDAS_DIR
from joborchestrator.ranking.nvidia_ranker import (
    DEFAULT_NVIDIA_MAX_CONCURRENCY,
    DEFAULT_NVIDIA_MODEL,
    DEFAULT_NVIDIA_REQUEST_BATCH_SIZE,
)
from joborchestrator.ranking.versions import NVIDIA_RANKING_VERSION, filter_llm_ranking_versions, is_heuristic_ranking_version
from joborchestrator.ranking.worker import run_worker_once
from joborchestrator.scanning import scanner as source_scanner
from joborchestrator.scanning import search_scanner
from joborchestrator.scanning.linkedin_importer import import_linkedin_dataframe_to_job_postings
from joborchestrator.scanning.providers import PROVIDERS
from joborchestrator.scanning.search_providers import SEARCH_PROVIDERS
from joborchestrator.storage import db_connection
from joborchestrator.storage import persistence as db


app = FastAPI(title="Job Orchestrator API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PipelinePatch(BaseModel):
    status: Literal["new", "shortlisted", "applied", "discarded", "opened"]


class SourcePayload(BaseModel):
    provider: str
    company_name: str
    company_ref: str
    enabled: bool = True


class AtsScanPayload(BaseModel):
    source_ids: list[int] | None = None
    max_concurrency: int = Field(default=6, ge=1, le=20)


class SearchPayload(BaseModel):
    providers: list[str]
    queries: list[str]
    location: str | None = "Spain"
    remote: bool = True
    max_pages: int = Field(default=1, ge=1, le=10)
    max_concurrency: int = Field(default=4, ge=1, le=20)


class RankingJobPayload(BaseModel):
    job_ids: list[int] | None = None
    limit: int = Field(default=250, ge=1, le=2000)
    model: str = DEFAULT_NVIDIA_MODEL
    request_batch_size: int = Field(default=DEFAULT_NVIDIA_REQUEST_BATCH_SIZE, ge=1, le=25)
    max_concurrency: int = Field(default=DEFAULT_NVIDIA_MAX_CONCURRENCY, ge=1, le=10)
    ranking_version: str = NVIDIA_RANKING_VERSION
    run_once: bool = False


class MaterialsPayload(BaseModel):
    use_llm: bool = False
    model: str = DEFAULT_MATERIALS_MODEL
    api_key: str | None = None
    shortlist: bool = True


class ProfilePayload(BaseModel):
    profile: dict[str, Any]


class SkillCatalogPayload(BaseModel):
    category: str = "General"
    name: str


def _job_for_materials(job_id: int) -> tuple[dict[str, Any], dict[str, Any] | None]:
    job = db.get_job_posting(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    ranking = latest_rankings_by_job_id().get(job_id)
    if ranking:
        job.update(
            {
                "final_score": ranking.get("final_score"),
                "decision": ranking.get("decision"),
                "reasoning_summary": ranking.get("reasoning_summary"),
                "recommended_application_angle": ranking.get("recommended_application_angle"),
                "cv_keywords_to_emphasize": parse_json_value(ranking.get("cv_keywords_to_emphasize_json"), []),
            }
        )
    return job, ranking


@app.on_event("startup")
def startup() -> None:
    db.init_db()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/profile")
def get_profile() -> dict[str, Any]:
    return {"profile": db.get_candidate_profile_payload()}


@app.put("/api/profile")
def save_profile(payload: ProfilePayload) -> dict[str, Any]:
    profile = normalize_profile_payload(payload.profile)
    db.save_candidate_profile_payload(profile)
    return {"profile": profile}


@app.get("/api/profile/skill-catalog")
def get_skill_catalog() -> dict[str, Any]:
    return {"skills": db.list_skill_catalog()}


@app.post("/api/profile/skill-catalog")
def add_skill_catalog_item(payload: SkillCatalogPayload) -> dict[str, Any]:
    try:
        skill = db.add_skill_catalog_item(payload.category, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"skill": skill, "skills": db.list_skill_catalog()}


@app.post("/api/profile/import-cv")
async def import_profile_cv(file: UploadFile = File(...)) -> dict[str, Any]:
    filename = file.filename or "cv"
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded CV is empty.")
    try:
        cv_text = extract_text_from_cv(filename, content)
    except CVProfileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    operation_id = db.create_operation(
        "cv_profile_import",
        {"filename": filename, "cv_text": cv_text},
        "Queued. Waiting for your local worker.",
    )
    return {"operation_id": operation_id, "status": "queued"}


@app.get("/api/operations/latest")
def latest_operation(type: str | None = None) -> dict[str, Any]:
    return {"operation": db.get_latest_operation(type)}


@app.get("/api/operations/{operation_id}")
def get_operation(operation_id: int) -> dict[str, Any]:
    operation = db.get_operation(operation_id)
    if not operation:
        raise HTTPException(status_code=404, detail="Operation not found")
    return {"operation": operation}


@app.get("/api/jobs")
def list_jobs(limit: int | None = None, ranking_version: str | None = None) -> dict[str, Any]:
    if ranking_version and is_heuristic_ranking_version(ranking_version):
        raise HTTPException(status_code=400, detail="Heuristic rankings are no longer supported in the dashboard.")
    jobs = db.get_job_postings(limit=limit)
    rankings = latest_rankings_by_job_id(ranking_version)
    ranking_versions = filter_llm_ranking_versions(db.get_ranking_versions())
    total = db.count_job_postings()
    return {
        "jobs": [job_dto(row, rankings.get(int(row["id"]))) for row in jobs.to_dict("records")],
        "ranking_versions": ranking_versions,
        "selected_ranking_version": ranking_version or (ranking_versions[0] if ranking_versions else None),
        "meta": {
            "total": total,
            "returned": len(jobs),
            "limited": limit is not None and len(jobs) < total,
            "db_mode": db_connection.connection_mode(),
        },
    }


@app.post("/api/jobs/{job_id}/pipeline")
def update_pipeline(job_id: int, payload: PipelinePatch) -> dict[str, Any]:
    db.update_job_status(job_id, payload.status)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/opened")
def mark_opened(job_id: int) -> dict[str, Any]:
    db.update_job_status(job_id, "opened")
    return {"ok": True}


@app.post("/api/jobs/{job_id}/materials")
def generate_materials(job_id: int, payload: MaterialsPayload) -> dict[str, Any]:
    job, ranking = _job_for_materials(job_id)
    keywords = parse_json_value(ranking.get("cv_keywords_to_emphasize_json"), []) if ranking else []
    try:
        if payload.use_llm:
            kit = build_application_kit_with_llm(
                job,
                api_key=payload.api_key,
                model=payload.model,
            )
        else:
            kit = build_application_kit(job, keywords=keywords)
    except (ApplicationMaterialsError, LLMMaterialsError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    db.update_job_application_materials(
        job_id,
        pipeline_status="shortlisted" if payload.shortlist else None,
        recruiter_message=kit.get("recruiter_message"),
        cover_letter=kit.get("cover_letter"),
        ats_cv_text=kit.get("ats_cv_text") or kit.get("ats_cv_notes"),
        autofill_notes=kit.get("autofill_notes"),
    )
    fresh = db.get_job_posting(job_id)
    rankings = latest_rankings_by_job_id()
    return {"job": job_dto(fresh, rankings.get(job_id))}


@app.get("/api/sources")
def list_sources() -> dict[str, Any]:
    return {
        "sources": db.list_company_sources().to_dict("records"),
        "providers": sorted(PROVIDERS.keys()),
        "search_providers": sorted(SEARCH_PROVIDERS.keys()),
    }


@app.post("/api/sources")
def upsert_source(payload: SourcePayload) -> dict[str, Any]:
    if payload.provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {payload.provider}")
    source_id = db.add_company_source(
        payload.provider,
        payload.company_name,
        payload.company_ref,
        enabled=payload.enabled,
    )
    return {"id": source_id}


@app.post("/api/scans/ats")
async def scan_ats(payload: AtsScanPayload) -> dict[str, Any]:
    sources = db.list_company_sources(enabled_only=True).to_dict("records")
    if payload.source_ids:
        wanted = {int(source_id) for source_id in payload.source_ids}
        sources = [source for source in sources if int(source["id"]) in wanted]
    results = await source_scanner.scan_sources_concurrently(sources, max_concurrency=payload.max_concurrency)
    return {"results": [scan_result_dto(result) for result in results]}


@app.post("/api/scans/search")
async def scan_search(payload: SearchPayload) -> dict[str, Any]:
    bad = [provider for provider in payload.providers if provider not in SEARCH_PROVIDERS]
    if bad:
        raise HTTPException(status_code=400, detail=f"Unsupported search providers: {bad}")
    queries = [query.strip() for query in payload.queries if query.strip()]
    results = await search_scanner.search_jobs_concurrently(
        payload.providers,
        queries,
        payload.location,
        remote=payload.remote,
        max_pages=payload.max_pages,
        max_concurrency=payload.max_concurrency,
    )
    return {"results": [scan_result_dto(result) for result in results]}


@app.get("/api/scans/overview")
def scan_overview() -> dict[str, Any]:
    return {
        "overview": db.get_scanner_overview(),
        "events": db.get_recent_scan_events(limit=20).to_dict("records"),
        "errors": db.get_recent_scan_errors(limit=10).to_dict("records"),
    }


@app.post("/api/linkedin/import-latest")
def import_latest_linkedin(min_description_len: int = MIN_DESCRIPCION_LEN_DEFAULT) -> dict[str, Any]:
    if not SALIDAS_DIR.exists():
        raise HTTPException(status_code=404, detail=f"LinkedIn output folder not found: {SALIDAS_DIR}")
    files = sorted(Path(SALIDAS_DIR).glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise HTTPException(status_code=404, detail="No LinkedIn .xlsx files found")
    df = pd.read_excel(files[0])
    filtered, stats = filtrar_ofertas(df, min_descripcion_len=min_description_len)
    import_stats = import_linkedin_dataframe_to_job_postings(filtered)
    return {"file": files[0].name, "filter_stats": stats, "import_stats": import_stats}


@app.post("/api/linkedin/import-excel")
async def import_linkedin_excel(
    file: UploadFile = File(...),
    min_description_len: int = MIN_DESCRIPCION_LEN_DEFAULT,
) -> dict[str, Any]:
    filename = file.filename or "linkedin.xlsx"
    if not filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Upload a LinkedIn Excel file (.xlsx or .xls).")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    try:
        df = pd.read_excel(BytesIO(content))
        filtered, stats = filtrar_ofertas(df, min_descripcion_len=min_description_len)
        import_stats = import_linkedin_dataframe_to_job_postings(filtered)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not import Excel: {exc}") from exc
    return {"file": filename, "filter_stats": stats, "import_stats": import_stats}


@app.post("/api/ranking/jobs")
def create_ranking_job(payload: RankingJobPayload) -> dict[str, Any]:
    if not db.get_candidate_profile_payload():
        raise HTTPException(status_code=400, detail="No candidate profile configured. Upload a CV in Profile before running NVIDIA ranking.")
    if payload.run_once and os.getenv("ALLOW_API_RANKING_RUN_ONCE") != "1":
        raise HTTPException(
            status_code=409,
            detail=(
                "Ranking jobs must be processed by the local NVIDIA ranking worker. "
                "Start run_ranking_worker.bat on your PC instead of running this from the API."
            ),
        )
    job_ids = payload.job_ids
    if not job_ids:
        unranked = db.get_unranked_jobs(ranking_version=payload.ranking_version, limit=payload.limit)
        job_ids = [int(value) for value in unranked["id"].tolist()]
    if not job_ids:
        return {"ranking_job_id": None, "queued": 0}

    ranking_job_id = db.create_ranking_job(
        provider="nvidia",
        model=payload.model,
        ranking_version=payload.ranking_version,
        job_ids=job_ids,
        request_batch_size=payload.request_batch_size,
        max_concurrency=payload.max_concurrency,
    )
    processed = False
    if payload.run_once:
        processed = run_worker_once(ranking_job_id=ranking_job_id)
    return {"ranking_job_id": ranking_job_id, "queued": len(job_ids), "processed_once": processed}


@app.post("/api/ranking/jobs/{ranking_job_id}/run-once")
def run_ranking_job_once(ranking_job_id: int) -> dict[str, Any]:
    if not db.get_candidate_profile_payload():
        raise HTTPException(status_code=400, detail="No candidate profile configured. Upload a CV in Profile before running NVIDIA ranking.")
    if os.getenv("ALLOW_API_RANKING_RUN_ONCE") != "1":
        raise HTTPException(
            status_code=409,
            detail=(
                "Ranking jobs must be processed by the local NVIDIA ranking worker. "
                "Start run_ranking_worker.bat on your PC instead of running this from the API."
            ),
        )
    return {"processed": run_worker_once(ranking_job_id=ranking_job_id)}


@app.get("/api/ranking/jobs")
def list_ranking_jobs() -> dict[str, Any]:
    return {"jobs": db.list_ranking_jobs(limit=25).to_dict("records")}


def main() -> None:
    import uvicorn

    uvicorn.run("joborchestrator.api:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
