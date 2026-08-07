from __future__ import annotations

from scripts import smoke_vercel_ui


def test_elapsed_ms_returns_non_negative_integer():
    started = smoke_vercel_ui.time.perf_counter()

    elapsed = smoke_vercel_ui._elapsed_ms(started)

    assert isinstance(elapsed, int)
    assert elapsed >= 0


def test_vercel_ui_required_text_accepts_readonly_production_summary():
    smoke_vercel_ui.require_screen_text(
        "Jobs\nAplicar\nAplicaciones\nConfiguración",
        {"jobs_total": 383, "profile_present": True},
    )


def test_vercel_ui_required_text_reports_missing_labels():
    try:
        smoke_vercel_ui.require_screen_text("Jobs", {"jobs_total": 1, "profile_present": True})
    except AssertionError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected missing text assertion.")

    assert "Aplicar" in message
    assert "Aplicaciones" in message
    assert "Configuración" in message


def test_vercel_ui_smoke_short_circuits_when_backend_fails(monkeypatch):
    monkeypatch.setattr(
        smoke_vercel_ui,
        "run_vercel_backend_smoke",
        lambda base_url: {
            "passed": False,
            "checks": {"failures": ["Backend did not report db_mode=turso."]},
            "summary": {},
        },
    )

    result = smoke_vercel_ui.run_vercel_ui_smoke(base_url="https://example.test")

    assert result["passed"] is False
    assert result["mode"] == "vercel_ui_readonly"
    assert result["base_url"] == "https://example.test"
    assert result["ui"] is None


def test_vercel_ui_compact_backend_reports_best_effort_error():
    compact = smoke_vercel_ui._compact_backend_result(None, "TimeoutError: handshake timeout")

    assert compact["passed"] is None
    assert compact["error"] == "TimeoutError: handshake timeout"
    assert compact["warnings"] == ["Backend preflight failed; UI browser checks continued."]


def test_vercel_ui_backend_preflight_retries_transient_errors(monkeypatch):
    calls = []

    def flaky_backend(base_url):
        calls.append(base_url)
        if len(calls) == 1:
            raise TimeoutError("handshake timeout")
        return {"passed": True, "checks": {"warnings": []}, "summary": {}}

    monkeypatch.setattr(smoke_vercel_ui, "run_vercel_backend_smoke", flaky_backend)
    monkeypatch.setattr(smoke_vercel_ui.time, "sleep", lambda seconds: None)

    result = smoke_vercel_ui._run_backend_preflight("https://example.test", attempts=2)

    assert result["passed"] is True
    assert calls == ["https://example.test", "https://example.test"]
    assert result["checks"]["warnings"] == ["Backend preflight succeeded after 2 attempts."]
