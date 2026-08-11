from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any


SELECTION_VERSION = "1.4.1"
DEFAULT_DOCUMENT_CHAR_BUDGET = 40_000

_FULL_DOCUMENT_NAME = re.compile(r"입찰\s*공고|공고문|표준\s*공고", re.IGNORECASE)
_LARGE_SUPPLEMENT_NAME = re.compile(
    r"제안\s*요청|요청서|규격서|과업\s*지시|시방서|설계서|품목\s*목록|"
    r"산출\s*내역|내역서",
    re.IGNORECASE,
)
_PRIMARY_REQUIREMENT = re.compile(
    r"입찰.{0,10}참가.{0,10}자격|참가\s*자격|자격\s*요건|공동\s*(수급|계약)|"
    r"직접\s*생산|중소기업|소상공인|여성기업|장애인기업|사회적기업|창업기업|"
    r"비영리\s*법인|휴업|폐업|파산|회생\s*절차|자본\s*잠식|"
    r"법인등기부.{0,12}(본점|소재)|세부품명번호|공급물품.{0,8}등록|"
    r"소프트웨어\s*사업자|업종\s*코드|면허|"
    r"지역.{0,6}(제한|소재)|실적|신용\s*평가|유효\s*기간|부정당|제재",
    re.IGNORECASE,
)
_OMISSION_GUARD = re.compile(
    r"기술.{0,8}인력|보유.{0,8}인력|전문\s*인력|재직|경력|자격증|"
    r"제조사?|공급사|총판|정품|납품|하도급|재하도급|인증|확인서|"
    r"등록.{0,8}(업체|사업자|하여야|필수)|법률.{0,8}(자격|요건)|"
    r"공인\s*인증서.{0,20}(차용|대여)|인증서.{0,20}(차용|대여)|"
    r"(보유|구비|갖추|등록|발급).{0,16}(하여야|해야|필수|자에 한)",
    re.IGNORECASE,
)
_REQUIREMENT_HEADING = re.compile(
    r"^\s*(?:\d+[.)]?\s*)?(?:입찰\s*)?(?:참가\s*)?(?:자격|요건|제한사항|공동계약|"
    r"제출서류|등록조건)\s*$",
    re.IGNORECASE,
)
_NEXT_HEADING = re.compile(r"^\s*(?:제?\s*\d+\s*[장조절]|\d+(?:\.\d+)*[.)])\s*\S+")


def select_eligibility_blocks(
    document: dict[str, Any], semantic_block_ids: set[str] | None = None,
    max_chars: int = DEFAULT_DOCUMENT_CHAR_BUDGET,
) -> dict[str, Any]:
    """Select likely eligibility blocks under a hard per-document character budget."""
    blocks = _refine_blocks(document.get("content", {}).get("blocks", []))
    file_name = str(document.get("file_name") or "")
    original_chars = _block_chars(blocks)
    if (
        original_chars <= max_chars
        and (len(blocks) <= 120 or _FULL_DOCUMENT_NAME.search(file_name)
             or not _LARGE_SUPPLEMENT_NAME.search(file_name))
    ):
        return _with_selection(
            document, blocks, "full_document", len(blocks), [], original_chars, max_chars,
        )

    selected = set(range(min(50, len(blocks))))
    passes: list[str] = ["leading_blocks"]

    page_hits = {
        index for index, block in enumerate(blocks)
        if isinstance(block.get("page"), int) and block["page"] <= 10
    }
    if page_hits:
        selected.update(page_hits)
        passes.append("leading_pages")

    primary_hits = _matching_indexes(blocks, _PRIMARY_REQUIREMENT)
    if primary_hits:
        _add_context(selected, primary_hits, len(blocks), radius=3)
        passes.append("requirement_terms")

    heading_hits = _matching_indexes(blocks, _REQUIREMENT_HEADING)
    if heading_hits:
        for index in heading_hits:
            selected.update(_heading_section(blocks, index))
        passes.append("requirement_sections")

    # This pass is intentionally independent from the main retrieval terms. It catches
    # variants that the initial test missed, such as personnel, manufacturer, and
    # subcontracting restrictions in the latter part of an RFP.
    guard_hits = {
        index for index in _matching_indexes(blocks, _OMISSION_GUARD)
        if index not in selected
    }
    if guard_hits:
        _add_context(selected, guard_hits, len(blocks), radius=3)
        passes.append("omission_guard")

    # Optional dense-retrieval results are unioned with exact-term retrieval. The
    # selector remains deterministic when no embedding service is configured.
    semantic_hits = {
        index for index, block in enumerate(blocks)
        if str(block.get("block_id")) in (semantic_block_ids or set())
    }
    if semantic_hits:
        _add_context(selected, semantic_hits, len(blocks), radius=3)
        passes.append("semantic_retrieval")

    selected = _fit_indexes_to_budget(blocks, selected, max_chars)
    chosen = [block for index, block in enumerate(blocks) if index in selected]
    return _with_selection(
        document, chosen, "focused_with_omission_guard", len(blocks), passes,
        original_chars, max_chars,
    )


def deduplicate_semantic_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse PDF/HWP renderings of the same notice while retaining provenance aliases."""
    canonical: list[dict[str, Any]] = []
    for document in sorted(documents, key=_canonical_document_rank):
        normalized = _normalized_document_text(document)
        requirement_fingerprint = _requirement_fingerprint(document)
        duplicate_index = next(
            (index for index, existing in enumerate(canonical)
             if _document_similarity(normalized, _normalized_document_text(existing)) >= 0.88
             and requirement_fingerprint == _requirement_fingerprint(existing)),
            None,
        )
        if duplicate_index is None:
            canonical.append(document)
            continue
        existing = canonical[duplicate_index]
        aliases = [*existing.get("semantic_duplicate_documents", []), {
            "document_id": document.get("document_id"),
            "file_name": document.get("file_name"),
        }]
        canonical[duplicate_index] = {**existing, "semantic_duplicate_documents": aliases}
    return canonical


def _refine_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refined: list[dict[str, Any]] = []
    for block in blocks:
        text = str(block.get("text") or "").strip()
        if len(text) <= 900:
            refined.append({**block, "char_start": 0, "char_end": len(text)})
            continue
        parts = _text_spans(text)
        if len(parts) == 1:
            refined.append({**block, "char_start": 0, "char_end": len(text)})
            continue
        for index, (start, end) in enumerate(parts, start=1):
            refined.append({
                **block,
                "block_id": f"{block['block_id']}~{index}",
                "text": text[start:end].strip(),
                "char_start": start,
                "char_end": end,
                "parent_block_id": block["block_id"],
            })
    return refined


def _text_spans(text: str, max_chars: int = 900) -> list[tuple[int, int]]:
    boundaries = [match.end() for match in re.finditer(r"\n+|(?<=[.!?다함됨음])\s+(?=[※①-⑳가-하0-9「『])", text)]
    spans: list[tuple[int, int]] = []
    start = 0
    for boundary in [*boundaries, len(text)]:
        if boundary - start < max_chars and boundary != len(text):
            continue
        end = boundary
        while end - start > max_chars:
            cut = text.rfind(" ", start, start + max_chars)
            if cut <= start:
                cut = start + max_chars
            spans.append((start, cut))
            start = cut
            while start < len(text) and text[start].isspace():
                start += 1
        if end > start:
            spans.append((start, end))
            start = end
            while start < len(text) and text[start].isspace():
                start += 1
    return [(start, end) for start, end in spans if text[start:end].strip()]


def _canonical_document_rank(document: dict[str, Any]) -> tuple[int, int, str]:
    name = str(document.get("file_name") or "")
    suffix = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    return (name.strip() == "표준공고서", 0 if suffix == "pdf" else 1, name)


def _normalized_document_text(document: dict[str, Any]) -> str:
    text = " ".join(str(block.get("text") or "") for block in document["content"]["blocks"])
    return "".join(character for character in unicodedata.normalize("NFKC", text).casefold()
                   if character.isalnum())


def _requirement_fingerprint(document: dict[str, Any]) -> frozenset[str]:
    return frozenset(
        "".join(character for character in unicodedata.normalize("NFKC", text).casefold()
                if character.isalnum())
        for block in document["content"]["blocks"]
        if (text := str(block.get("text") or ""))
        and (_PRIMARY_REQUIREMENT.search(text) or _OMISSION_GUARD.search(text))
    )


def _document_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    length_ratio = min(len(left), len(right)) / max(len(left), len(right))
    if length_ratio < 0.75:
        return 0.0
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


def _matching_indexes(blocks: list[dict[str, Any]], pattern: re.Pattern[str]) -> set[int]:
    return {
        index for index, block in enumerate(blocks)
        if pattern.search(str(block.get("text") or ""))
    }


def _add_context(selected: set[int], indexes: set[int], size: int, radius: int) -> None:
    for index in indexes:
        selected.update(range(max(0, index - radius), min(size, index + radius + 1)))


def _heading_section(blocks: list[dict[str, Any]], start: int) -> range:
    stop = min(len(blocks), start + 31)
    for index in range(start + 1, stop):
        if _NEXT_HEADING.search(str(blocks[index].get("text") or "")):
            stop = index
            break
    return range(start, stop)


def _block_chars(blocks: list[dict[str, Any]]) -> int:
    return sum(len(str(block.get("text") or "")) for block in blocks)


def _fit_indexes_to_budget(
    blocks: list[dict[str, Any]], selected: set[int], max_chars: int,
) -> set[int]:
    """Keep high-signal blocks first, then restore source order for citation stability."""
    def priority(index: int) -> tuple[int, int]:
        block = blocks[index]
        text = str(block.get("text") or "")
        score = 0
        if _PRIMARY_REQUIREMENT.search(text):
            score += 8
        if _OMISSION_GUARD.search(text):
            score += 5
        if _REQUIREMENT_HEADING.search(text):
            score += 4
        if isinstance(block.get("page"), int) and block["page"] <= 10:
            score += 2
        if index < 20:
            score += 1
        return (-score, index)

    kept: set[int] = set()
    used = 0
    for index in sorted(selected, key=priority):
        size = len(str(blocks[index].get("text") or ""))
        if kept and used + size > max_chars:
            continue
        kept.add(index)
        used += size
        if used >= max_chars:
            break
    if not kept and blocks:
        kept.add(min(selected) if selected else 0)
    return kept


def _with_selection(document: dict[str, Any], blocks: list[dict[str, Any]],
                    strategy: str, original_count: int, passes: list[str],
                    original_chars: int, max_chars: int) -> dict[str, Any]:
    return {
        **document,
        "content": {**document.get("content", {}), "blocks": blocks},
        "selection": {
            "version": SELECTION_VERSION,
            "strategy": strategy,
            "original_block_count": original_count,
            "selected_block_count": len(blocks),
            "omitted_block_count": original_count - len(blocks),
            "original_char_count": original_chars,
            "selected_char_count": _block_chars(blocks),
            "char_budget": max_chars,
            "passes": passes,
        },
    }
