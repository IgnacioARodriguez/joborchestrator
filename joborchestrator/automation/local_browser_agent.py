from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page

SESSION_SCHEME = "local-browser://session/"


@dataclass
class LocalBrowserSession:
    ref: str
    page: Page
    browser: Browser | None
    context: BrowserContext | None
    playwright: Any | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    provider: str
    session_id: int
    job_id: int


_SESSIONS: dict[str, LocalBrowserSession] = {}


def enabled() -> bool:
    import os

    return os.getenv("APPLICATION_BROWSER_HANDOFF", "0") == "1"


def register_session(
    *,
    page: Page,
    browser: Browser | None,
    context: BrowserContext | None,
    playwright: Any | None = None,
    provider: str,
    session_id: int,
    job_id: int,
    timeout_seconds: int = 3600,
) -> LocalBrowserSession:
    ref = f"{SESSION_SCHEME}{uuid.uuid4()}"
    now = datetime.now()
    session = LocalBrowserSession(
        ref=ref,
        page=page,
        browser=browser,
        context=context,
        playwright=playwright,
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(seconds=max(60, timeout_seconds)),
        provider=provider,
        session_id=session_id,
        job_id=job_id,
    )
    _SESSIONS[ref] = session
    return session


async def get_session(ref: str | None) -> LocalBrowserSession | None:
    if not ref or not ref.startswith(SESSION_SCHEME):
        return None
    session = _SESSIONS.get(ref)
    if not session:
        return None
    if session.expires_at <= datetime.now() or session.page.is_closed():
        await close_session(ref)
        return None
    session.updated_at = datetime.now()
    return session


async def close_session(ref: str) -> bool:
    session = _SESSIONS.pop(ref, None)
    if not session:
        return False
    if session.context is not None:
        await session.context.close()
    elif session.browser is not None:
        await session.browser.close()
    if session.playwright is not None:
        await session.playwright.stop()
    return True


def public_metadata(session: LocalBrowserSession) -> dict[str, Any]:
    return {
        "ref": session.ref,
        "provider": session.provider,
        "session_id": session.session_id,
        "job_id": session.job_id,
        "created_at": session.created_at.isoformat(timespec="seconds"),
        "updated_at": session.updated_at.isoformat(timespec="seconds"),
        "expires_at": session.expires_at.isoformat(timespec="seconds"),
    }
