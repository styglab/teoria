"""Rank metadata for document review; never assert specification contents.

No commodity codes, model names, downloads, parsers, or external calls belong here.
"""

from dataclasses import dataclass
import re
import unicodedata


RULE_VERSION = "attachment_review_v3"
SELECTED_REVIEW_PRIORITIES = frozenset({"first_review"})
DIRECT_ROLES = ("규격서", "사양서", "시방서", "구매규격")
RELATED_ROLES = (
    "현품설명서", "제안요청서", "과업지시서", "물품내역서", "구매내역서",
    "품목명세서", "물품명세서",
)
RELATED_ROLES_V2 = RELATED_ROLES + ("규격비교조사표", "산출내역서", "용도설명서", "인프라구성도")
AUXILIARY_TERMS = (
    "양식", "서식", "평가기준", "평가항목", "평가표", "평가서", "작성안내",
    "제출안내", "제출서류", "검토확인서", "작성요령", "제출요령", "샘플", "견본", "예시",
)
MIXED_ROLES = ("입찰공고", "공고문", "공고서", "계약조건", "계약특수조건")
REFERENCE_ROLES = (
    ("공고문", ("공고문", "공고서", "입찰공고")),
    ("공고서", ("공고문", "공고서", "입찰공고")),
    ("특수조건", ("특수조건",)),
    ("현품설명서", ("현품설명서",)),
    ("제안요청서", ("제안요청서",)),
    ("과업지시서", ("과업지시서",)),
    ("내역서", ("내역서",)),
)
REFERENCE_CUES = ("참조", "참고", "따름", "의함", "첨부", "별첨", "붙임")
NEGATIVE_REFERENCES = (
    "해당없", "참조하지", "참고하지", "미첨부", "미제공", "별도제공", "추후제공",
)


@dataclass(frozen=True, slots=True)
class AttachmentReviewPriority:
    original_filename: object
    normalized_filename: str
    source_reference: str
    priority: str
    reason: str
    matched_roles: tuple[str, ...] = ()
    auxiliary_terms: tuple[str, ...] = ()
    mixed_roles: tuple[str, ...] = ()
    reference_matches: tuple[str, ...] = ()
    content_state: str = "not_reviewed"
    rule_version: str = RULE_VERSION


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\s_\-·()\[\]{}【】\u200b\ufeff]", "", value)


def prioritize_attachment(
    filename: object, *, source_reference: str = "", rule_version: str = RULE_VERSION,
) -> AttachmentReviewPriority:
    """Choose review order from common evidence; every result stays unverified.

    A missing filename, mixed-role file, or sole attachment is never promoted by
    item membership. A caller retains the complete attachment list separately.
    """
    if rule_version not in {"attachment_review_v1", "attachment_review_v2", "attachment_review_v3"}:
        raise ValueError("unsupported attachment review rule version")
    if filename is None or (isinstance(filename, str) and not _normalize(filename)):
        return AttachmentReviewPriority(filename, "", source_reference, "manual_review", "missing_filename", rule_version=rule_version)
    if not isinstance(filename, str):
        return AttachmentReviewPriority(filename, "", source_reference, "manual_review", "invalid_filename", rule_version=rule_version)
    name = _normalize(filename)
    direct = tuple(term for term in DIRECT_ROLES if term in name)
    related_terms = RELATED_ROLES if rule_version == "attachment_review_v1" else RELATED_ROLES_V2
    related = tuple(term for term in related_terms if term in name)
    auxiliary = tuple(term for term in AUXILIARY_TERMS if term in name)
    mixed = tuple(term for term in MIXED_ROLES if term in name)
    reference = _normalize(source_reference)
    references = tuple(dict.fromkeys(
        role for role, filenames in REFERENCE_ROLES
        if role in reference and any(alias in name for alias in filenames)
        and any(cue in reference for cue in REFERENCE_CUES)
        and not any(negative in reference for negative in NEGATIVE_REFERENCES)
    ))
    if auxiliary:
        priority, reason = "manual_review", "auxiliary_or_conflicting_role"
    elif references and rule_version != "attachment_review_v3":
        priority, reason = "first_review", "explicit_source_reference"
    elif direct and not mixed:
        priority, reason = "first_review", "explicit_specification_filename"
    elif direct and mixed:
        priority, reason = "manual_review", "mixed_document_roles"
    elif related and not mixed:
        priority, reason = "additional_review", "possible_requirement_document"
    else:
        priority, reason = "manual_review", "insufficient_metadata_evidence"
    return AttachmentReviewPriority(
        filename, name, source_reference, priority, reason,
        direct + related, auxiliary, mixed, references, rule_version=rule_version,
    )
