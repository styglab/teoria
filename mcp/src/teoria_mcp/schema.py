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
            "pagination": {
                "type": "object",
                "properties": {
                    "page": {"type": "integer", "minimum": 1},
                    "page_size": {"type": "integer", "minimum": 1},
                    "total_items": {"type": "integer", "minimum": 0},
                    "total_pages": {"type": "integer", "minimum": 0},
                },
                "required": ["page", "page_size", "total_items", "total_pages"],
                "additionalProperties": False,
            },
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
