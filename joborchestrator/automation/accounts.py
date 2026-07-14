from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


SERVICE_PREFIX = "joborchestrator"


@dataclass(frozen=True)
class SiteIdentity:
    provider: str
    domain: str


def site_identity_from_url(url: str, provider_hint: str = "generic") -> SiteIdentity:
    parsed = urlparse(url)
    domain = (parsed.netloc or parsed.path).lower().strip()
    if domain.startswith("www."):
        domain = domain[4:]
    provider = provider_hint or "generic"
    if "greenhouse" in domain or "grnh.se" in domain:
        provider = "greenhouse"
    elif "lever.co" in domain:
        provider = "lever"
    elif "ashbyhq" in domain:
        provider = "ashby"
    elif "workday" in domain:
        provider = "workday"
    return SiteIdentity(provider=provider, domain=domain or "unknown")


def credential_service_name(domain: str, username: str) -> str:
    return f"{SERVICE_PREFIX}:{domain}:{username}"


def store_password(domain: str, username: str, password: str | None) -> str | None:
    if not password:
        return None
    ref = credential_service_name(domain, username)
    try:
        import keyring  # type: ignore

        keyring.set_password(ref, username, password)
        return f"keyring://{ref}"
    except Exception:
        if os.getenv("ALLOW_PLAINTEXT_CREDENTIAL_STORE") == "1":
            return f"plaintext://{password}"
        raise RuntimeError(
            "Could not store password in OS keyring. Install keyring support or set "
            "ALLOW_PLAINTEXT_CREDENTIAL_STORE=1 for this personal local app."
        )


def load_password(password_ref: str | None, username: str) -> str | None:
    if not password_ref:
        return None
    if password_ref.startswith("plaintext://"):
        return password_ref.removeprefix("plaintext://")
    if password_ref.startswith("keyring://"):
        service = password_ref.removeprefix("keyring://")
        try:
            import keyring  # type: ignore

            return keyring.get_password(service, username)
        except Exception:
            return None
    return None
