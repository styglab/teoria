"""External semantic grading, kept outside the Harness2 proposer context."""
from __future__ import annotations

from pathlib import Path

from .codex_runner import CodexRunner


async def review_names(cases: list[dict], runner: CodexRunner, output: Path) -> dict:
    if not cases:
        return {}
    result = await runner.generate(
        "규격서 구조화 답안의 장비 귀속과 속성 의미만 비교하는 독립 채점자다. 주어진 question, "
        "expected, actual에서 owner가 같은 실제 장비·부품 인스턴스인지, attribute가 같은 측정 "
        "의미인지 판단하라. 단순 이름 차이·한국어/영어 동의어는 허용하되 서버 RAM과 GPU RAM, "
        "서로 다른 장비, 기본/부스트 클럭, 점유높이/수용높이 혼동은 허용하지 말라. "
        "source quotation이 같다는 사실만으로 같은 귀속이라고 판단하지 말라. owner에 상위 "
        "장비 이름이 생략돼도 question과 actual 정보에서 유일하게 식별되면 허용한다. "
        "문제만 보고 누락된 귀속을 임의 보충하지 말고 불확실하면 false. Return JSON "
        "{matches:[{case_id,owner_equivalent:boolean,attribute_equivalent:boolean,reason:string}]}. "
        "모든 case_id를 정확히 한번 포함한다. 다른 기준이나 숫자 채점을 바꾸지 말라.",
        {"cases": cases}, output,
    )
    matches = result.get("matches", [])
    if not isinstance(matches, list):
        raise ValueError("semantic judge did not return matches")
    by_id = {m["case_id"]: m for m in matches}
    if len(matches) != len(by_id) or set(by_id) != {c["case_id"] for c in cases}:
        raise ValueError("semantic judge omitted or duplicated a case")
    for match in matches:
        if any(type(match.get(field)) is not bool for field in ("owner_equivalent", "attribute_equivalent")):
            raise ValueError("semantic judgement must be boolean")
    return by_id
