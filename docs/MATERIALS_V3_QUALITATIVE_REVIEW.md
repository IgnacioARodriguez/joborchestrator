# Materials v3 Qualitative Review

Date: 2026-07-29
Branch reviewed: `codex/chat-isolated-work`
Latest reviewed commit: `13520db fix(materials): align ATS keyword coverage with generated CV`

This review summarizes local generated artifacts without publishing full CV/contact text. Raw artifacts remain ignored under `data/` and `output/`.

## Review Scope

Reviewed local artifacts:

- `data/materials_live_probe/20260729_120305_synthetic_short_source_role_keywords_presence.json`
- `data/materials_live_probe/20260728_140737_pss_full_retry3.json`
- `data/materials_live_probe/20260729_111354_acme_backend_strong.json`
- `data/materials_live_probe/20260729_111851_between_fullstack_adjacent.json`
- `data/materials_live_probe/20260729_112345_hirefeed_contract_ai_cautious.json`
- PDF/DOCX exports under `output/pdf/materials_live_probe/`
- Rendered PDF page PNGs under `output/pdf/materials_live_probe/rendered/`

## Overall Read

The current materials output is qualitatively stronger than the short, plain, one-page artifact that originally raised concern. For real multi-role CVs, generated ATS CVs are not minimal summaries: they preserve multiple employers, use parseable sections, include substantial role bullets, and keep enough detail to read like a real application CV.

The latest synthetic one-role CV is intentionally short because the source CV is tiny. That is acceptable for the specific synthetic case, but should not be treated as the desired shape for the user's real CV. The adaptive line threshold is appropriate only because density, sections, source bullets, and keyword-presence gates still apply.

## Case Notes

### `synthetic_short_source_role_keywords_presence`

- Job: API Integration Developer at LeanOps.
- CV length: 732 characters, 18 non-empty lines.
- CV status: completed after 2 attempts.
- First attempt was correctly rejected because the CV was too short and `keywords_used` declared `operations workflows` before the exact phrase appeared in `ats_cv_text`.
- Final semantic eval: materials 100, ATS CV 100.
- Qualitative verdict: acceptable for a deliberately tiny one-role source CV. It should not be used as a representative visual/style benchmark for the user's real CV.

### `pss_full_retry3`

- Job: AWS Backend / Cloud Developer at PSS.
- CV length: 3641 characters, 53 non-empty lines, about 30 experience bullets.
- CV required 4 attempts; early attempts were rejected for overcompression, missing role technology preservation, and insufficient recent-role detail.
- Final semantic eval: materials 100, ATS CV 100.
- Qualitative verdict: materially complete. It preserves a multi-role work history and reads like a real ATS CV, not a stub.

### `acme_backend_strong`

- Job: Python Backend Engineer at Acme.
- CV length: 3494 characters, 55 non-empty lines, about 33 bullets.
- CV required 2 attempts; first attempt caught overcompression and employer-specific technology drift.
- Final semantic eval: materials 100, ATS CV 100.
- Qualitative verdict: strong representative real-case output. It is detailed enough for ATS while remaining parseable.

### `between_fullstack_adjacent`

- Job: Fullstack Developer Python & React at BETWEEN Group.
- CV length: 5183 characters, 61 non-empty lines, about 38 bullets.
- CV required 2 attempts; first attempt caught overcompression.
- Final semantic eval: materials 100, ATS CV 100.
- Qualitative verdict: strongest density sample. It demonstrates that the system can produce a longer, richer CV when the job and source history justify it.

### `hirefeed_contract_ai_cautious`

- Job: Python Developer at Hire Feed.
- CV length: 3887 characters, 49 non-empty lines.
- CV required 2 attempts; kit required 3 attempts because the system correctly pushed the tone away from overconfident language for a cautious/skip-style case.
- Raw CV used Unicode bullets; PDF export normalized them to standard hyphen bullets. The exported text is parseable and structured.
- Final semantic eval: materials 100, ATS CV 100.
- Qualitative verdict: acceptable. The cautious material tone is a feature, not a bug, given the riskier ranking context.

## ATS And Style Findings

- Real-case CVs are substantially longer than the one-role synthetic sample and preserve multiple roles.
- Generated CVs use standard ATS sections: Professional Summary, Technical Skills, Professional Experience, Education.
- PDF/DOCX exports preserve parseable text and sections.
- Raw Unicode bullets are normalized in exported PDFs/DOCX, so ATS export text uses ordinary hyphen bullets.
- The system now blocks a subtle ATS false positive: declaring a keyword in `keywords_used` while omitting the normalized token-aware phrase from `ats_cv_text`.
- The generated format is intentionally ATS-oriented, not a heavily designed visual resume. That is correct for ATS submission, but the visual styling will look simpler than a designed PDF resume.

## PDF Visual Render Check

`pdftoppm` was unavailable as a working binary in this Windows environment, so the PDFs were rendered with PyMuPDF into PNGs and visually inspected.

Rendered pages:

- `acme_backend_strong.pdf`: 1 page, nonblank, no visible clipping or overlap.
- `pss_full_retry3.pdf`: 1 page, nonblank, no visible clipping or overlap.
- `hirefeed_contract_ai_cautious.pdf`: 1 page, nonblank, no visible clipping or overlap.
- `between_fullstack_adjacent.pdf`: 2 pages, both nonblank; page 2 is intentionally short because the CV flows after a full first page.

Visual verdict: exports are readable, parseable, and ATS-classic. They are dense and plain rather than visually branded. That is acceptable for ATS submission, but not equivalent to a designed resume template.

## Remaining Risk

- Human review is still recommended for final wording, especially cover letter tone and whether a cautious application is worth sending.
- Visual PDF rendering has now been verified with PyMuPDF. Text extraction from PDFs/DOCX also passed.
- A production UI should make clear that ATS CV output is optimized for parseability, while a separate styled resume export could preserve a more designed look.

## Qualitative Verdict

The current branch is no longer showing the original "short and bare" failure mode for real multi-role CVs. The short output is confined to a synthetic short-source case and now passes only when it preserves source bullets, sections, and exact declared ATS keywords.

Recommended next step before merge: review cover-letter wording and application-tone choices for the four real-case generated materials. Treat any remaining PDF presentation feedback as export polish rather than core ATS correctness.
