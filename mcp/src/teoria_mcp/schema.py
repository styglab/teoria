from __future__ import annotations

from typing import Any


def capability_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "status": {"type": "string", "const": "success"},
            "capability": {"type": "string"},
            "objects": {"type": "array", "items": {"type": "object"}},
            "links": {"type": "array", "items": {"type": "object"}},
            "total_objects": {"type": "integer"},
            "total_links": {"type": "integer"},
            "truncated": {"type": "boolean"},
            "outcome": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "status": {"type": "string"},
                    "matched": {"type": "boolean"},
                    "observed_at": {"type": "string", "format": "date-time"},
                    "input": {"type": "object"},
                },
                "required": ["type", "status", "matched", "observed_at", "input"],
            },
        },
        "required": ["status", "capability", "objects", "links", "total_objects", "total_links", "truncated"],
    }
