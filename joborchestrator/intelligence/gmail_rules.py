from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class GmailMessageSignal:
    event_type: str
    confidence: float
    note: str


def classify_recruiter_message(sender: str, subject: str, body: str) -> GmailMessageSignal | None:
    text = f"{sender} {subject} {body}".lower()
    if any(marker in text for marker in ["unfortunately", "not moving forward", "other candidates", "not selected"]):
        return GmailMessageSignal("rejection", 0.9, "Rule matched rejection language.")
    if any(marker in text for marker in ["interview", "technical screen", "calendar", "schedule a call", "meet with"]):
        return GmailMessageSignal("interview_scheduled", 0.82, "Rule matched interview scheduling language.")
    if any(marker in text for marker in ["recruiter", "talent acquisition", "hiring team", "thanks for applying"]):
        return GmailMessageSignal("recruiter_reply", 0.7, "Rule matched recruiter reply language.")
    return None
