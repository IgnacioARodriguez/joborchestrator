from __future__ import annotations

import re
import unicodedata
from collections import Counter

from joborchestrator.intelligence.cv_profile_extractor import CVProfileError, extract_text_from_cv


class CVExportValidationError(RuntimeError):
    pass


def clean_ats_cv_text_for_export(text: str) -> str:
    cleaned = str(text or "")
    replacements = {
        "\x7f": "-",
        "\u2022": "-",
        "\u2023": "-",
        "\u25e6": "-",
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)

    forbidden_sections = [
        "Optimization notes",
        "ATS CV targeting notes",
        "ATS optimized CV draft",
        "Optimized CV",
    ]
    lines: list[str] = []
    skip_rest = False
    for raw_line in cleaned.splitlines():
        stripped = raw_line.strip()
        normalized = stripped.casefold()
        if any(normalized.startswith(section.casefold()) for section in forbidden_sections):
            if normalized.startswith("optimization notes"):
                skip_rest = True
            continue
        if skip_rest:
            continue
        if stripped.startswith("Target role:") or stripped.startswith("Positioning angle:"):
            continue
        if stripped.startswith("ATS keywords to emphasize truthfully:"):
            continue
        if stripped and set(stripped) <= {"-"}:
            continue
        lines.append(raw_line)
    return "\n".join(lines).strip()


def validate_exported_ats_cv(
    file_format: str,
    content: bytes,
    expected_text: str,
) -> None:
    normalized_format = str(file_format or "").strip().lower()
    if normalized_format not in {"docx", "pdf"}:
        raise CVExportValidationError(
            f"Unsupported ATS CV export format for validation: {file_format!r}."
        )
    if not content:
        raise CVExportValidationError(
            f"Generated ATS CV {normalized_format.upper()} file is empty."
        )

    expected_export_text = clean_ats_cv_text_for_export(expected_text)
    expected_segments = _significant_segments(expected_export_text)
    if not expected_segments:
        raise CVExportValidationError(
            "ATS CV export validation requires non-empty expected CV text."
        )

    try:
        exported_text = extract_text_from_cv(
            f"ats-cv-round-trip.{normalized_format}",
            content,
        )
    except CVProfileError as exc:
        raise CVExportValidationError(
            f"Could not read the generated ATS CV {normalized_format.upper()} file: {exc}"
        ) from exc
    except Exception as exc:
        raise CVExportValidationError(
            f"Could not read the generated ATS CV {normalized_format.upper()} file: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    exported_tokens = _tokens(exported_text)
    if not exported_tokens:
        raise CVExportValidationError(
            f"Generated ATS CV {normalized_format.upper()} file contains no readable text."
        )

    expected_counts = Counter(tuple(_tokens(segment)) for segment in expected_segments)
    missing: list[str] = []
    for token_sequence, required_count in expected_counts.items():
        if not token_sequence:
            continue
        found_count = _count_token_sequence(exported_tokens, token_sequence)
        if found_count < required_count:
            original = next(
                segment
                for segment in expected_segments
                if tuple(_tokens(segment)) == token_sequence
            )
            missing.append(original)

    if missing:
        preview = "; ".join(repr(segment) for segment in missing[:5])
        suffix = "" if len(missing) <= 5 else f"; plus {len(missing) - 5} more"
        raise CVExportValidationError(
            f"Generated ATS CV {normalized_format.upper()} file lost source-backed CV content: "
            f"{preview}{suffix}."
        )


def _significant_segments(text: str) -> list[str]:
    return [line.strip() for line in str(text or "").splitlines() if _tokens(line)]


def _tokens(text: str) -> list[str]:
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    ascii_text = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return re.findall(r"[a-z0-9+#@]+", ascii_text.casefold())


def _count_token_sequence(tokens: list[str], sequence: tuple[str, ...]) -> int:
    size = len(sequence)
    if size == 0 or size > len(tokens):
        return 0
    return sum(
        1
        for index in range(len(tokens) - size + 1)
        if tuple(tokens[index : index + size]) == sequence
    )
