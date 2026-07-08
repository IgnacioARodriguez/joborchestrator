from joborchestrator.ranking.requirements_extractor import extract_requirements
from joborchestrator.storage import persistence as db


def test_requirements_extractor_uses_db_skill_catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scanner.db")
    db.init_db()
    db.add_skill_catalog_item("Legal", "Contract Review")

    requirements = extract_requirements(
        {
            "title": "Legal Operations Specialist",
            "company": "Acme",
            "location": "Remote",
            "description_text": "Requirements: Contract Review, stakeholder communication.",
        }
    )

    assert "Contract Review" in requirements.tech_stack
    assert "Contract Review" in requirements.hard_requirements
