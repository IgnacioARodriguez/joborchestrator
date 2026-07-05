import pandas as pd

from joborchestrator.storage import persistence as db


def test_resetear_puntuaciones_preserva_historial_y_estado(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_tracker.db")
    db.init_db()

    db.registrar_ofertas_vistas(
        pd.DataFrame(
            [
                {
                    "id": "job-1",
                    "titulo": "Backend Engineer",
                    "empresa": "Acme",
                    "ubicacion": "Remote",
                    "modalidad": "Remoto",
                    "categoria": "backend",
                    "url": "https://example.com/job-1",
                }
            ]
        )
    )
    db.guardar_scores(
        pd.DataFrame(
            [
                {
                    "id": "job-1",
                    "SCORE_TOTAL": 91,
                    "FIT_STACK": 90,
                    "FIT_SENIORITY": 90,
                    "BARRERAS_DURAS": 5,
                    "VOLUMEN_CONTRATACION": 80,
                    "TRANSFERIBILIDAD": 85,
                    "razon_breve": "Good fit",
                }
            ]
        )
    )
    db.marcar_aplicado("job-1", True, "Applied manually")

    assert db.resetear_puntuaciones() == 1

    history = db.get_historial()
    row = history.iloc[0]
    assert row["id"] == "job-1"
    assert pd.isna(row["score_total"])
    assert row["aplicado"] == 1
    assert row["notas"] == "Applied manually"


def test_borrar_historial_elimina_ofertas(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_tracker.db")
    db.init_db()
    db.registrar_ofertas_vistas(pd.DataFrame([{"id": "job-1", "titulo": "Backend Engineer"}]))

    assert db.borrar_historial() == 1
    assert db.get_historial().empty
