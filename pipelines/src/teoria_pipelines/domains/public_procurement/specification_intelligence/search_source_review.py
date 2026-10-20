"""Reconcile extracted numerical requirements against source before dictionary building."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from .codex_runner import CodexRunner
from .search_evaluation import save_json


SOURCE_REVIEW_INSTRUCTION = """규격서 원문만 기준으로 수치 요구조건 facts를 검토·보완하라.
질문이나 정답은 제공하지 않는다. 빠진 요구조건, 잘못된 귀속·부등호·범위를 고쳐라.
하드웨어 이외의 소프트웨어 수량, 사용자 수, 보증·운영 수치도 각각의 올바른 owner에 보존한다.
소프트웨어·운영 요구를 하드웨어 성능 속성에 섞거나 모두 제외하지 말라.
모델명·공고번호·문단 번호·일정 숫자를 장비 속성으로 만들지 말라. 명시된 기술 세대는 구별한다.
configuration: 납품 구성량 installed, 지원 가능량 supported, 기존 비교 대상 existing,
설치/지원 구별과 무관한 물성 not_applicable, 원문으로 결정 불가 unknown.
aggregation: owner 안의 합계·부품 개수 total, 개별 부품 한 개의 측정값 per_instance,
슬롯당 값 per_slot, 합산 구별 없음 not_applicable, 결정 불가 unknown.
예를 들어 서버 안 CPU 2개는 total, CPU 한 개의 코어 수는 per_instance다.
기본/부스트, 최대지원/설치, 부품당/전체, 장비 간 요구조건을 구별한다.
속성 이름은 표현·설치 상태를 붙여 늘리지 말고 측정 의미를 드러낸 영어 snake_case로 한다.
각 fact는 owner,attribute,value(원문 수치 토큰 문자열),unit(단위 없으면 빈 문자열),
operator(eq/ge/le/gt/lt/unknown),configuration,aggregation,quote의 8개 필드만 가진다.
quote는 해당 값이 있는 원문의 완전한 구간 그대로. 단위·숫자·비교 방향을 추정하지 않는다.
Return JSON {"facts":[...],"review_notes":[수정·제외 이유 문자열]}.
"""


async def review_development(root: Path, variant: str, runner: CodexRunner) -> str:
    async def one(path):
        source = json.loads((root / "sources/development" / f"{path.parent.name}.json").read_text())
        result = await runner.generate(SOURCE_REVIEW_INSTRUCTION,
            {"source": source, "facts": json.loads(path.read_text())},
            root / "source_review/development" / path.parent.name / "reviewed_facts.json")
        save_json(root / "source_review/development" / path.parent.name / "facts_for_dictionary.json", {"facts": result["facts"]})
        print(f"source review development {path.parent.name}", flush=True)
    await asyncio.gather(*(one(path) for path in sorted((root / "predictions" / variant / "development").glob("*/facts.json"))))
    return "source_review"
