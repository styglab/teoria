from __future__ import annotations

import re
from decimal import Decimal
from typing import Any


TITLE_TRIGRAM_SIMILARITY_THRESHOLD = 0.08


def compact(value: Any) -> str:
    return "".join(str(value or "").split()).casefold()


def number(value: Any) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def normalized_title(value: str) -> str:
    value = re.sub(
        r"(19|20)\d{2}년|\([^)]*(긴급|재공고|변경|취소)[^)]*\)|\[(긴급|재공고|변경|취소)[^]]*\]",
        " ", value.casefold(),
    )
    return " ".join(re.sub(r"[^0-9a-z가-힣]+", " ", value).split())


def title_tokens(value: str) -> set[str]:
    stopwords = {"사업", "용역", "구매", "공사", "입찰", "공고", "및", "위한"}
    return {
        token for token in normalized_title(value).split()
        if len(token) > 1 and token not in stopwords
    }


def jaccard(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(left | right) if left or right else 0.0


def character_trigrams(value: str) -> set[str]:
    value = compact(normalized_title(value))
    return {value[index:index + 3] for index in range(max(0, len(value) - 2))}


def project_types(value: str) -> set[str]:
    patterns = {
        "build": ("구축", "개발", "도입"),
        "improvement": ("고도화", "개선", "재구축"),
        "maintenance": ("유지보수", "유지관리", "운영"),
        "consulting": ("컨설팅", "감리", "설계"),
    }
    value = compact(value)
    return {
        kind for kind, words in patterns.items()
        if any(word in value for word in words)
    }


def primary_project_type(value: str) -> str:
    value = compact(value)
    candidates = {
        "improvement": ("고도화", "개선", "재구축"),
        "maintenance": ("유지보수", "유지관리", "운영"),
        "build": ("구축", "개발", "도입"),
        "consulting": ("컨설팅", "감리", "설계"),
    }
    positions = []
    for kind, words in candidates.items():
        found = [value.find(word) for word in words if word in value]
        if found:
            positions.append((min(found), kind))
    return min(positions)[1] if positions else "unknown"


def project_type_label(value: str) -> str:
    return {
        "build": "구축", "improvement": "개선·고도화",
        "maintenance": "유지관리", "consulting": "컨설팅·감리·설계",
        "unknown": "미분류",
    }[value]


def work_type_label(value: str) -> str:
    return {
        "goods": "물품", "service": "용역", "construction": "공사",
        "foreign": "외자", "other": "기타", "unknown": "미분류",
    }.get(value, value)


def business_fields(value: str) -> set[str]:
    patterns = {
        "information_system": (
            "정보시스템", "플랫폼", "소프트웨어", "전산", "정보화",
            "데이터플랫폼", "데이터시스템", "재해복구시스템", "클라우드",
        ),
        "security": ("정보보호", "보안", "방화벽", "침입방지"),
        "communication": ("정보통신", "통신망", "네트워크"),
    }
    value = compact(value)
    fields = {
        field for field, words in patterns.items()
        if any(word in value for word in words)
    }
    if any(marker in value for marker in ("리스사선정", "계약은행", "펀드평가사선정")):
        fields.discard("information_system")
    return fields


def amount_similarity(left: Any, right: Any) -> tuple[float, str | None]:
    left_number, right_number = number(left), number(right)
    if not left_number or not right_number:
        return 0.0, "amount_unknown"
    ratio = min(float(left_number), float(right_number)) / max(
        float(left_number), float(right_number)
    )
    return ratio, None if ratio >= 0.5 else "different_amount_range"
