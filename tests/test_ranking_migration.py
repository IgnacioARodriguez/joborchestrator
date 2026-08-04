from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "verify_ranking_migration.py"
SPEC = importlib.util.spec_from_file_location("verify_ranking_migration", SCRIPT_PATH)
assert SPEC and SPEC.loader
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


def test_phase_0_integrity_verifier() -> None:
    metrics = verify.verify_phase_0_integrity()
    assert metrics["contradictions_before"] > metrics["contradictions_after"] == 0


def test_phase_1_persistence_verifier() -> None:
    metrics = verify.verify_phase_1_persistence()
    assert metrics["duplicate_items_before"] > metrics["duplicate_items_after"] == 0
    assert metrics["rerank_ids_after"] == [2, 3]


def test_phase_2_deterministic_verifier() -> None:
    metrics = verify.verify_phase_2_deterministic()
    assert metrics["decision_agreement_after"] == metrics["cases"]
    assert metrics["decision_agreement_after"] > metrics["decision_agreement_before"]


def test_phase_3_activation_verifier() -> None:
    metrics = verify.verify_phase_3_activation()
    assert metrics["default_version"] == verify.NVIDIA_DETERMINISTIC_RANKING_VERSION
    assert metrics["rollback_version"] == "ranking_v1.1.0-nvidia"
