from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class NormalizedBidNoticeBatch:
    notices: list[dict[str, Any]] = field(default_factory=list)
    license_restrictions: list[dict[str, Any]] = field(default_factory=list)
    participation_regions: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class BidNoticeKey:
    notice_number: str
    notice_order: str
