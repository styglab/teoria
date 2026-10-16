from __future__ import annotations

import base64
import json
from typing import Any

from teoria.runtime.capability.contracts import CapabilityExecutionError


def _cursor(offset: int, fingerprint: str) -> str:
    value = json.dumps(
        {"offset": offset, "fingerprint": fingerprint}, separators=(",", ":")
    )
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def _decode_cursor(value: Any, fingerprint: str, capability_id: str) -> int:
    if not value:
        return 0
    try:
        encoded = str(value)
        decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        payload = json.loads(decoded)
        if payload.get("fingerprint") != fingerprint:
            raise ValueError("cursor query does not match")
        offset = int(payload["offset"])
        if offset < 0:
            raise ValueError("cursor offset is negative")
        return offset
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise CapabilityExecutionError(
            "invalid_cursor",
            "cursor is invalid or belongs to another query",
            capability_id=capability_id,
        ) from exc
