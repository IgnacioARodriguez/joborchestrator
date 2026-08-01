from __future__ import annotations

from io import BytesIO

import pytest
from docx import Document
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from joborchestrator.intelligence.cv_export_validation import (
    CVExportValidationError,
    clean_ats_cv_text_for_export,
    validate_exported_ats_cv,
)
from joborchestrator.intelligence.llm_application_materials import (
    _clean_cv_text_for_export,
    export_ats_cv_docx_bytes,
    export_ats_cv_pdf_bytes,
)


ATS_CV_TEXT = """Ignacio Rodriguez
ignacio@example.com | Malaga, Spain

Professional Summary
Backend engineer focused on Python and REST APIs with reliable delivery across product teams and a deliberately long sentence that must wrap in the PDF without failing round-trip validation.

Technical Skills
Python, REST APIs, Redis, PostgreSQL, Docker, C++

Professional Experience
Backend Developer | Fiction Express | April 2025 - March 2026
- Built analytics APIs with Python for education workflows and reporting requirements.
- Improved Redis-backed data reliability and documented operational support workflows.
Technologies: Python, REST APIs, Redis

Education
Computer Science

Optimization notes
Target role: Senior Backend Engineer
Kubernetes
""".strip()


def _docx_bytes(text: str) -> bytes:
    document = Document()
    for line in text.splitlines():
        document.add_paragraph(line)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _pdf_bytes(text: str) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    y = 800
    for line in text.splitlines():
        pdf.drawString(40, y, line)
        y -= 14
    pdf.save()
    return buffer.getvalue()


def test_shared_export_cleaner_preserves_existing_behavior() -> None:
    cleaned = clean_ats_cv_text_for_export(ATS_CV_TEXT)

    assert cleaned == _clean_cv_text_for_export(ATS_CV_TEXT)
    assert "Optimization notes" not in cleaned
    assert "Target role:" not in cleaned
    assert "Kubernetes" not in cleaned


def test_actual_docx_export_passes_round_trip_validation() -> None:
    content = export_ats_cv_docx_bytes({}, ATS_CV_TEXT)

    validate_exported_ats_cv("docx", content, ATS_CV_TEXT)


def test_actual_pdf_export_passes_round_trip_validation() -> None:
    content = export_ats_cv_pdf_bytes({}, ATS_CV_TEXT)

    validate_exported_ats_cv("pdf", content, ATS_CV_TEXT)


def test_round_trip_blocks_missing_company() -> None:
    incomplete = clean_ats_cv_text_for_export(ATS_CV_TEXT).replace(
        "Fiction Express",
        "Acme",
    )

    with pytest.raises(CVExportValidationError, match="Fiction Express"):
        validate_exported_ats_cv("docx", _docx_bytes(incomplete), ATS_CV_TEXT)


def test_round_trip_blocks_missing_bullet() -> None:
    incomplete = clean_ats_cv_text_for_export(ATS_CV_TEXT).replace(
        "- Improved Redis-backed data reliability and documented operational support workflows.\n",
        "",
    )

    with pytest.raises(CVExportValidationError, match="Redis-backed"):
        validate_exported_ats_cv("pdf", _pdf_bytes(incomplete), ATS_CV_TEXT)


def test_round_trip_rejects_unsupported_format() -> None:
    with pytest.raises(CVExportValidationError, match="Unsupported"):
        validate_exported_ats_cv("txt", b"content", ATS_CV_TEXT)
