from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from teoria_pipelines.models import ExtractedBatch


@dataclass(slots=True)
class OpeningResultBatch:
    """Opening results plus the award records whose lookup was conclusive."""

    openings: ExtractedBatch
    successful_awards: ExtractedBatch
    failed_awards: ExtractedBatch


@dataclass(slots=True)
class NoticeOutcomeResultBatch:
    """Failure outcomes plus notice lookups classified by request success."""

    outcomes: ExtractedBatch
    successful_notices: ExtractedBatch
    failed_notices: ExtractedBatch


@dataclass(slots=True)
class NormalizedBidResultBatch:
    awards: list[dict[str, Any]] = field(default_factory=list)
    opening_participants: list[dict[str, Any]] = field(default_factory=list)
    notice_outcomes: list[dict[str, Any]] = field(default_factory=list)
