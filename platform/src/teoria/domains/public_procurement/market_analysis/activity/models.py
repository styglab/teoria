from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ActivityEvents:
    activities: dict[str, dict[str, Any]]
    notice_to_activity: dict[str, str]
    participated_activity_ids: set[str]
    contract_classifications: dict[str, dict[str, Any]]
    organization_name: str | None


@dataclass
class ActivityPage:
    items: list[dict[str, Any]]
    stage_property: str
    id_property: str
    stage_counts: dict[str, int]
    linkage_counts: dict[str, int]
    pagination: dict[str, int]
