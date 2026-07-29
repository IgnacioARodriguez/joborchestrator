from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


PolicyOutcome = Literal["ALLOW", "REVIEW_REQUIRED", "DENY"]

PROFILE_AUTOFILL_KEYS = {
    "full_name",
    "email",
    "phone",
    "linkedin",
    "portfolio",
    "preferred_location",
    "talent_pool",
}

OPTIONAL_DEMOGRAPHIC_KEYS = {"gender", "ethnicity", "disability", "veteran"}
LEGAL_CONSENT_REASON = "legal_consent_reserved_for_user"


@dataclass(frozen=True)
class PolicyDecision:
    outcome: PolicyOutcome
    reason_code: str
    action: str
    control: dict[str, Any]
    semantic_category: str
    evidence: list[str] = field(default_factory=list)
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_answer_action(answer: dict[str, Any], *, action: str) -> PolicyDecision:
    control = {
        "field_name": str(answer.get("field_name") or ""),
        "label": str(answer.get("label") or ""),
        "field_type": str(answer.get("field_type") or "text"),
    }
    semantic = str(answer.get("canonical_key") or answer.get("classification") or "unknown") or "unknown"
    evidence = _evidence_parts(control["label"], control["field_name"], semantic)
    text = _normalized(" ".join(evidence))

    challenge = _challenge_category(text)
    if challenge:
        return PolicyDecision(
            outcome="DENY",
            reason_code=f"{challenge}_automation_denied",
            action=action,
            control=control,
            semantic_category=challenge,
            evidence=evidence,
            explanation="External challenge/login flows are never automated.",
        )

    legal = legal_consent_category(text, semantic)
    if legal:
        return PolicyDecision(
            outcome="REVIEW_REQUIRED",
            reason_code=LEGAL_CONSENT_REASON,
            action=action,
            control=control,
            semantic_category=legal,
            evidence=evidence,
            explanation="Legal, consent, certification and signature actions are reserved for the user.",
        )

    if semantic in OPTIONAL_DEMOGRAPHIC_KEYS:
        return PolicyDecision(
            outcome="REVIEW_REQUIRED",
            reason_code="optional_demographic_reserved_for_user",
            action=action,
            control=control,
            semantic_category=semantic,
            evidence=evidence,
            explanation="Optional demographic fields require user review.",
        )

    if answer.get("requires_confirmation"):
        return PolicyDecision(
            outcome="REVIEW_REQUIRED",
            reason_code="answer_requires_confirmation",
            action=action,
            control=control,
            semantic_category=semantic,
            evidence=evidence,
            explanation="The resolved answer is not approved for unattended automation.",
        )

    value = str(answer.get("value") or "").strip()
    if not value:
        return PolicyDecision(
            outcome="REVIEW_REQUIRED",
            reason_code="missing_answer",
            action=action,
            control=control,
            semantic_category=semantic,
            evidence=evidence,
            explanation="No valid answer was resolved for the control.",
        )

    source = str(answer.get("source") or "")
    if semantic in {"work_authorization", "sponsorship"}:
        if source == "approved_answer":
            return PolicyDecision(
                outcome="ALLOW",
                reason_code=f"{semantic}_approved_answer",
                action=action,
                control=control,
                semantic_category=semantic,
                evidence=evidence,
                explanation="Work authorization and sponsorship can be automated only with an approved exact answer.",
            )
        return PolicyDecision(
            outcome="REVIEW_REQUIRED",
            reason_code=f"{semantic}_requires_approved_answer",
            action=action,
            control=control,
            semantic_category=semantic,
            evidence=evidence,
            explanation="Sensitive work eligibility answers require explicit approved-answer evidence.",
        )

    if source != "approved_answer" and semantic not in PROFILE_AUTOFILL_KEYS:
        return PolicyDecision(
            outcome="REVIEW_REQUIRED",
            reason_code="unapproved_non_profile_answer",
            action=action,
            control=control,
            semantic_category=semantic,
            evidence=evidence,
            explanation="Only confirmed profile fields or approved answers can be automated.",
        )

    return PolicyDecision(
        outcome="ALLOW",
        reason_code="authorized_answer",
        action=action,
        control=control,
        semantic_category=semantic,
        evidence=evidence,
        explanation="The answer is authorized for the planned action.",
    )


def evaluate_browser_action(label: str, *, action: str = "click") -> PolicyDecision:
    evidence = _evidence_parts(label)
    text = _normalized(label)
    if re.search(r"\b(submit application|send application|complete application|finish|submit|enviar candidatura|enviar solicitud|finalizar)\b", text):
        return PolicyDecision(
            outcome="REVIEW_REQUIRED",
            reason_code="final_submit_reserved_for_user",
            action=action,
            control={"label": label},
            semantic_category="final_submit",
            evidence=evidence,
            explanation="Final submit remains reserved for the user.",
        )
    if re.search(r"\b(apply|apply now|i m interested|start application|continue application|aplicar|solicitar|postular|postularme)\b", text):
        return PolicyDecision(
            outcome="ALLOW",
            reason_code="safe_navigation_action",
            action=action,
            control={"label": label},
            semantic_category="navigation",
            evidence=evidence,
            explanation="The action is a pre-submit navigation boundary.",
        )
    return PolicyDecision(
        outcome="REVIEW_REQUIRED",
        reason_code="ambiguous_browser_action",
        action=action,
        control={"label": label},
        semantic_category="unknown",
        evidence=evidence,
        explanation="The browser action is not clearly safe.",
    )


def requires_explicit_human_consent(*parts: str) -> bool:
    text = _normalized(" ".join(str(part or "") for part in parts))
    semantic = _normalized(parts[-1] if parts else "")
    return legal_consent_category(text, semantic) is not None


def legal_consent_category(text: str, semantic: str = "") -> str | None:
    normalized_text = _normalized(text)
    normalized_semantic = _normalized(semantic)
    if normalized_semantic in {"work_authorization", "sponsorship"}:
        return None
    if "background check" in normalized_text or "background-check" in normalized_text:
        return "background_check_authorization"
    if "marketing" in normalized_text and any(marker in normalized_text for marker in ("opt in", "subscribe", "consent", "agree")):
        return "marketing_opt_in"
    markers = {
        "privacy": "privacy_acknowledgement",
        "policy": "privacy_acknowledgement",
        "declaration": "accuracy_certification",
        "certify": "accuracy_certification",
        "accurate": "accuracy_certification",
        "accuracy": "accuracy_certification",
        "signature": "signature",
        "acknowledge": "legal_acknowledgement",
        "acknowledgement": "legal_acknowledgement",
        "terms": "terms_acceptance",
        "agreement": "terms_acceptance",
        "agree": "terms_acceptance",
        "consent": "legal_consent",
    }
    for marker, category in markers.items():
        if marker in normalized_text:
            return category
    if "authorization" in normalized_text and not any(
        marker in normalized_text
        for marker in ("work authorization", "authorized to work", "authorization to work", "permiso de trabajo", "sponsorship", "visa")
    ):
        return "legal_authorization"
    return None


def _challenge_category(text: str) -> str | None:
    markers = {
        "captcha": "captcha",
        "mfa": "mfa",
        "multi factor": "mfa",
        "two factor": "mfa",
        "email verification": "email_verification",
        "password recovery": "password_recovery",
        "login": "login_required",
        "log in": "login_required",
        "sign in": "login_required",
    }
    for marker, category in markers.items():
        if marker in text:
            return category
    return None


def _evidence_parts(*parts: str) -> list[str]:
    return [str(part).strip() for part in parts if str(part or "").strip()]


def _normalized(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    ascii_text = ascii_text.lower()
    ascii_text = re.sub(r"[^\w\s-]+", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip()
