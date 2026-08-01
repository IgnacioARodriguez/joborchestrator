import asyncio

from joborchestrator.scanning import linkedin


def test_persist_linkedin_offer_upserts_one_job_immediately(monkeypatch):
    captured = {}

    def fake_upsert(posting):
        captured["posting"] = posting
        return "new"

    monkeypatch.setattr(linkedin.db, "upsert_job_posting", fake_upsert)

    status = asyncio.run(
        linkedin.persist_linkedin_offer(
            {
                "id": "123",
                "titulo": "Backend Engineer",
                "empresa": "Acme",
                "ubicacion": "Malaga, Spain",
                "modalidad": "Hybrid",
                "fecha_publicacion": "1 day ago",
                "url": "https://www.linkedin.com/jobs/view/123/",
                "descripcion": "Build Python APIs with FastAPI. " * 10,
                "descripcion_len": 320,
                "extraccion_ok": True,
            }
        )
    )

    assert status == "new"
    assert captured["posting"].external_id == "123"
    assert captured["posting"].source == "linkedin_scraper"
    assert captured["posting"].title == "Backend Engineer"
    assert captured["posting"].company == "Acme"

