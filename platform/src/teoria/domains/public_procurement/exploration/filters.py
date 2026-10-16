from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

ENTITY_TYPES = ("bid_notice", "organization", "company", "classification")
_INITIALS = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"

from teoria.runtime.capability.contracts import CapabilityExecutionError


def _digits(value: Any) -> str:
    return "".join(character for character in str(value or "") if character.isdigit())


def _normalized_query(value: Any) -> str:
    return re.sub(r"[\s\-]+", "", str(value or "").strip().casefold())


def _hangul_initials(value: str) -> str:
    result: list[str] = []
    for character in value:
        code = ord(character)
        if 0xAC00 <= code <= 0xD7A3:
            result.append(_INITIALS[(code - 0xAC00) // 588])
        elif not character.isspace():
            result.append(character.casefold())
    return "".join(result)


def _with_period(inputs: dict[str, Any], capability_id: str) -> dict[str, Any]:
    current_year = datetime.now(timezone.utc).year
    period_to_year = int(inputs.get("period_to_year") or current_year)
    period_from_year = int(
        inputs.get("period_from_year") or max(2000, period_to_year - 4)
    )
    if period_from_year > period_to_year:
        raise CapabilityExecutionError(
            "invalid_period",
            "period_from_year must not exceed period_to_year",
            capability_id=capability_id,
        )
    return {
        **inputs,
        "period_from_year": period_from_year,
        "period_to_year": period_to_year,
    }


def _with_region_filter(inputs: dict[str, Any], capability_id: str) -> dict[str, Any]:
    basis = inputs.get("region_basis")
    code = str(inputs.get("region_code") or "").strip() or None
    codes = [
        str(value).strip()
        for value in (inputs.get("region_codes") or [])
        if str(value).strip()
    ]
    if code:
        codes.append(code)
    codes = list(dict.fromkeys(codes))
    if basis is not None and basis != "participation_restriction":
        raise CapabilityExecutionError(
            "unsupported_region_basis",
            f"unsupported region_basis '{basis}'",
            capability_id=capability_id,
        )
    if codes and basis is None:
        basis = "participation_restriction"
    return {
        **inputs,
        "region_basis": basis,
        "region_code": codes[0] if len(codes) == 1 else None,
        "region_codes": codes or None,
    }
