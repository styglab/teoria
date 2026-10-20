"""Source-grounded QA, notice-group split and deterministic typed answer grading.

Model-created labels are silver labels. Quotation checks do not establish their
semantic correctness; a separate Codex review and human review status are recorded.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .document_evidence import comparable_text

METRIC_VERSION = "v2_evidence_containment"


class RequirementAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner: str = Field(min_length=1)
    attribute: str = Field(min_length=1)
    value: str = Field(pattern=r"^[+-]?\d+(?:,\d{3})*(?:\.\d+)?$")
    unit: str
    operator: str = Field(pattern=r"^(eq|ge|le|gt|lt|unknown)$")
    configuration: str = Field(pattern=r"^(installed|supported|existing|not_applicable|unknown)$")
    aggregation: str = Field(pattern=r"^(per_instance|total|per_slot|not_applicable|unknown)$")
    quote: str = Field(min_length=1)


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: str
    question: str = Field(min_length=1)
    category: str
    expected: RequirementAnswer | None
    rationale: str = Field(min_length=1)


class QuestionSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    questions: list[Question] = Field(min_length=1)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def split_documents(documents: list[dict], *, exposed_sha256: set[str], seed: str) -> dict:
    """Connected notice/hash groups cannot cross the split; exposed groups stay dev."""
    if not documents or len({d["document_id"] for d in documents}) != len(documents):
        raise ValueError("nonempty corpus with unique document IDs required")
    groups: list[list[dict]] = []
    for doc in sorted(documents, key=lambda d: d["document_id"]):
        matches = [g for g in groups if any(
            x["notice_number"] == doc["notice_number"] or x["source_sha256"] == doc["source_sha256"]
            for x in g
        )]
        merged = [doc]
        for group in matches:
            merged.extend(group)
            groups.remove(group)
        groups.append(merged)
    eligible = [g for g in groups if not any(d["source_sha256"] in exposed_sha256 for d in g)]
    eligible.sort(key=lambda g: hashlib.sha256((seed + min(d["document_id"] for d in g)).encode()).hexdigest())
    target = math.ceil(len(documents) * .2)
    validation: list[dict] = []
    for group in eligible:
        if len(validation) >= target:
            break
        validation.extend(group)
    if len(validation) < target or len(validation) == len(documents):
        raise ValueError("insufficient unexposed groups for a 20% holdout")
    ids = {d["document_id"] for d in validation}
    return {
        "seed": seed, "policy": "notice_and_original_hash_connected_groups; exposed_groups_dev_only",
        "target_validation_fraction": .2, "actual_validation_fraction": len(validation) / len(documents),
        "development": [d for d in documents if d["document_id"] not in ids],
        "validation": validation,
        "prior_exposure": "retrospective split of an existing corpus; no claim of prospective unseen accuracy",
    }


def check_question_set(raw: dict, source: str) -> QuestionSet:
    result = QuestionSet.model_validate(raw)
    ids = [q.question_id for q in result.questions]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate question ID")
    for question in result.questions:
        if question.expected and comparable_text(question.expected.quote) not in comparable_text(source):
            raise ValueError(f"answer quote absent from source: {question.question_id}")
        if question.expected:
            if not value_in_quote(question.expected.value, question.expected.quote):
                raise ValueError(f"answer value absent from quotation: {question.question_id}")
    return result


def value_in_quote(value: str, quote: str) -> bool:
    # Keep spaces: stripping them turns model D7 followed by 96GB into D796GB.
    return bool(re.search(r"(?<![\d.])" + re.escape(value) + r"(?![\d.])", unicodedata.normalize("NFKC", quote)))


def normalized_value(value: str, unit: str) -> tuple[str, str]:
    """Exact numeric/unit equivalence only; never change meaning or scope."""
    units = {"tib": ("gib", Decimal(1024)), "gib": ("gib", Decimal(1)),
             "mib": ("gib", Decimal(1) / 1024), "ghz": ("mhz", Decimal(1000)),
             "mhz": ("mhz", Decimal(1)), "watt": ("w", Decimal(1))}
    key = comparable_text(unit).casefold()
    dimension, multiplier = units.get(key, (key, Decimal(1)))
    try:
        number = Decimal(value.replace(",", "").strip()) * multiplier
        if not number.is_finite():
            raise InvalidOperation
        return format(number.normalize(), "f"), dimension
    except InvalidOperation:
        return comparable_text(value).casefold(), key


def grade_answers(questions: QuestionSet, predictions: dict, source: str) -> dict:
    """Missing/malformed answers fail, including in the abstention denominator."""
    answers = predictions.get("answers", [])
    if not isinstance(answers, list):
        answers = []
    by_id: dict[str, list] = {}
    for answer in answers:
        if isinstance(answer, dict):
            by_id.setdefault(str(answer.get("question_id")), []).append(answer.get("answer"))
    rows = []
    for q in questions.questions:
        candidates = by_id.get(q.question_id, [])
        failures = []
        if len(candidates) != 1:
            failures.append("missing_or_duplicate_answer")
        elif q.expected is None:
            if candidates[0] is not None:
                failures.append("unsupported_answer")
        else:
            try:
                answer = RequirementAnswer.model_validate(candidates[0])
            except (ValueError, TypeError):
                failures.append("invalid_answer")
            else:
                if comparable_text(answer.quote) not in comparable_text(source):
                    failures.append("ungrounded_evidence")
                if not value_in_quote(answer.value, answer.quote):
                    failures.append("value_not_in_evidence")
                # Exact evidence passage anchors the equipment instance and attribute.
                # Its identity is deliberately stricter than a semantic LLM judge.
                if comparable_text(q.expected.quote) not in comparable_text(answer.quote):
                    failures.append("evidence_identity")
                if normalized_value(answer.value, answer.unit) != normalized_value(q.expected.value, q.expected.unit):
                    failures.append("value_or_unit")
                for key in ("operator", "configuration", "aggregation"):
                    if getattr(answer, key) != getattr(q.expected, key):
                        failures.append(key)
        rows.append({"question_id": q.question_id, "category": q.category,
                     "passed": not failures, "failures": failures})
    return {"total": len(rows), "passed": sum(r["passed"] for r in rows), "rows": rows,
            "metric": "expected source passage contained in quotation + value/unit + operator/configuration/aggregation; owner/attribute names reviewed separately"}


QA_INSTRUCTION = """규격서 원문만 읽고 한국어 질문·정답 6개를 작성하라. 기존 사전이나 추출 결과를 사용하지 않는다.
수치값을 묻는 명확한 질문 5개와 문서로 답할 수 없는 질문 1개를 만든다. 문서에 실제 있는
설치/최대지원, 모듈당/전체, CPU당/시스템전체, 기본/부스트, 장비별 구별을 질문에 명시하라.
없는 구별을 만들어내지 말라. 답할 수 없는 질문 expected는 null, 이유에는 왜 없는지 쓴다.
각 정답의 value는 원문 그대로의 수치 토큰, unit은 원문 단위, quote는 해당 값이 있는 원문의
완전한 한 줄/문장 그대로로 하라. 인접 값이나 다른 장비를 혼합하지 말라. 부등호는 ge/le/eq/gt/lt/unknown.
명시적인 이상/최소가 없으면 ge로 추정하지 말라. 요구사항과 제품의 실제 만족 여부를 구별하라.
attribute는 상태를 붙여 늘리지 않은 영어 snake_case 속성명, owner는 장비·부품을 식별하는 이름.
Return the supplied schema shape. Category는 value, configuration, aggregation, owner, operator, unanswerable 중 선택."""

REVIEW_INSTRUCTION = """독립 검토자로 원문과 질문·정답을 대조하라. 원문에 없는 값, 잘못된 단위·부등호·귀속·
설치와 최대지원의 혼동·CPU당과 전체 혼동·질문의 모호함·실제 답할 수 있는 미응답 문제를 고쳐라.
각 quote는 해당 수치가 있는 원문의 완전한 한 줄/문장 그대로. 정답 value는 인용 내 수치 토큰 그대로.
반드시 questions만 가진 동일 스키마 JSON을 반환하라. 정답을 검토했어도 사람 검토 완료라고 하지 말라."""

EXTRACTION_INSTRUCTION = """규격서를 검색 가능한 구조로 바꿔라. 모든 주요 장비별 수치 요구조건을 facts 배열에
추출하라. 각 fact는 owner, attribute(영어 snake_case), value(수치 토큰), unit, operator
(eq/ge/le/gt/lt/unknown), configuration(installed/supported/existing/not_applicable/unknown),
aggregation(per_instance/total/per_slot/not_applicable/unknown), quote를 가진다.
quote는 값이 있는 원문의 완전한 한 줄/문장 그대로. 하나의 문장에 수치 여러개면 fact 여러개.
최대 지원량과 납품 설치량, 기본/부스트 클럭, 모듈당/전체, 개별CPU/시스템전체를 분리하라.
표현이나 포함/지원 상태 차이만으로 새로운 attribute를 만들지 말고 configuration으로 표현하라.
관계·소프트웨어·운영조건을 하드웨어 수치 속성에 섞지 말라. 단위나 부등호를 추정하지 말라.
규격서 명시 요구값을 적고 제품 성능을 추정하지 말라. {"facts":[...]}를 반환하라."""

ANSWER_INSTRUCTION = """구조화된 facts만으로 질문에 답하라. 원문이나 외부 지식은 주어지지 않는다.
동일 장비·동일 속성·동일 설치/지원 범위의 fact를 선택하고 모든 필드를 그대로 복사하라.
질문에 해당하는 fact가 없거나 귀속이 불명확하면 answer:null. 다른 장비의 조건을 합치지 말라.
{"answers":[{"question_id":"...","answer":{fact의 모든 필드 또는 null}}]}를 반환하라.
추가 필드를 만들지 말라. 모든 질문에 응답하라."""
