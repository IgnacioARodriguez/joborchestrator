from __future__ import annotations

import hashlib
import json
from typing import Any


def profile_trace(profile_payload: dict[str, Any] | None) -> dict[str, Any]:
    snapshot = profile_payload or {}
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    return {
        "hash": hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest() if snapshot else None,
        "snapshot": snapshot,
    }
