"""Explain development failures and label uncertainty without opening holdout data."""
from __future__ import annotations

import json
from pathlib import Path

from .codex_runner import CodexRunner


async def find_improvements(root: Path, runner: CodexRunner) -> dict:
    def load(path):
        return json.loads(path.read_text())

    selected = load(root / "selection.json")["chosen"]
    report = load(root / "reports" / f"{selected}_development.json")
    cases, sources = [], {}
    for document in report["documents"]:
        identity = document["document_id"]
        labels = load(root / "labels/development" / f"{identity}.json")["questions"]
        answers = load(root / "predictions" / selected / "development" / identity / "answers.json")
        for row in document["rows"]:
            if not row["passed"]:
                label = next(q for q in labels if q["question_id"] == row["question_id"])
                actual = [a for a in answers.get("answers", []) if a.get("question_id") == row["question_id"]]
                cases.append({"case_id": f"{identity}/{row['question_id']}", "label": label,
                              "answers": actual, "failures": row["failures"]})
                sources[identity] = load(root / "sources/development" / f"{identity}.json")
    return await runner.generate(
        "개발용 규격서와 실패 사례만 보고 업데이트 사항을 찾아라. 실패를 전부 모델 오류로 "
        "단정하지 말고 정답 자체의 오해·모호한 aggregation/configuration·인용 채점 한계도 검토한다. "
        "고정한 정답이나 점수는 수정하지 말라. 구체적 근거 case_id를 붙여 prompt_updates, "
        "code_updates, label_issues 배열과 limitations 배열을 가진 JSON을 반환한다. "
        "prompt_updates/code_updates 각 항목은 issue,change,evidence_case_ids를 가진다. "
        "label_issues는 case_id,status(ambiguous/likely_incorrect),reason을 가진다. "
        "소프트웨어·운영조건은 하드웨어 속성과 구분해 구조화하며 수치 요구를 무조건 버리지 않는다. "
        "추가 모듈·추상화를 이유 없이 제안하지 말고 실제 실패에 대응하는 수정만 제안하라. "
        "이는 제안이며 테스트나 정확도 개선을 이미 달성했다고 주장하지 말라.",
        {"development_sources": sources, "failures": cases, "selected_prompt": (root / "selected_prompt.md").read_text()},
        root / "improvements.json",
    )
