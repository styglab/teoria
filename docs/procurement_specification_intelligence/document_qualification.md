# 3단계 문서 적합성 판정

## 책임과 현재 방식

파싱된 문서에 실제 발주 대상의 구체적인 요구규격이 있는지 판정한다.
현재 의미 판단은 [Codex 직접 분석](codex_analysis.md)으로 작성하고,
`document_qualification` 모듈은 제출 JSON의 입력 식별과 인용·참조를 검증한다.
이 모듈은 파싱이나 후속 구성 분석을 실행하지 않는다.

파일명만으로 규격 포함을 확정하는 대안은 비용이 작지만 본문을 보장하지 못한다.
본문 규칙 기반 판정은 별도 평가가 필요하다. 현재 권장안은 Codex 제안과
결정론적 근거 검증을 분리한 오프라인 실행이며 별도 모델 API를 호출하지 않는다.

## 고정한 v1 계약

입력은 성공한 kordoc native JSON과 `QualificationSubmission`이다.

| 필드 | 의미 |
|---|---|
| `schema_version` | `qualification_submission_v1` |
| `run_id`, `analysis_method` | 판정 실행 ID, 현재 `codex_interactive_reading` |
| `document_id`, `parse_run_id`, `native_sha256` | 분석한 문서·파싱 실행·native 파일 바이트 해시 |
| `source_sha256` | 수집·파싱 기록에서 제공한 원본 파일 해시 |
| `proposal` | 문서 역할, 구간별 판정·이유·정확한 인용문, 요약 |

출력 `QualificationRecord`는 `qualification_record_v1`이며 입력 submission과
검증 결과를 함께 보존한다. 결과에는 문서·실행·해시, 구간별 오류,
미확인 영역, `scope=supplied_parse_only`, `review_status=pending`이 포함된다.
원본 파일 해시는 입력 이력 값으로 보존하며 이 CLI가 원본 파일을 다시 읽어 검증하는 것은 아니다.
native 파일의 해시는 CLI가 실제 바이트에서 계산해 제출 해시와 비교한다.

계약의 기준은 소유 모듈의 Pydantic 모델과 `model_json_schema()`다.
이전 시험의 `qualification_proposal.json`은 proposal 본문이므로 v1 submission의
실행·입력 식별 필드를 추가해야 한다. 기존 시험 파일을 새 계약인 것처럼 해석하지 않는다.

## 검증 순서와 결정

1. 스키마, 문서·실행 ID, native SHA-256이 실제 입력과 일치하는지 확인한다.
2. 구간 ID 중복, 노드 존재, 인용문 일치와 이미지 근거 오용을 검사한다.
3. 유효한 양성 구간이 있으면 `REQUIREMENTS_FOUND`다. 다른 영역의 미확인은 보존한다.
4. 읽을 수 있는 본문이 없으면 `UNASSESSABLE`이다. 이미지 파일명은 본문으로 세지 않는다.
5. 근거 오류·모호한 판정·미확인 영역이 남은 음성 제안은 `AMBIGUOUS`다.
6. 나머지 음성은 `NO_REQUIREMENTS_FOUND_IN_REVIEWED_INPUT`이다. 전체 첨부 집합의 부재 판정이 아니다.

유효한 인용은 의미적 정확성이나 학습용 승인을 보장하지 않는다. 양성은
[구성 분석](composition_analysis.md)의 후보로 검토할 수 있다는 뜻이다.
현재 두 모듈은 자동 연결하지 않는다. 판단의 신뢰도 수치나 Precision은 생성하지 않는다.

## 단독 실행과 실패 처리

```bash
uv run --locked --package teoria-pipelines python -m \
  teoria_pipelines.domains.public_procurement.specification_intelligence.document_qualification \
  --native /path/to/native.json \
  --submission /path/to/qualification_submission.json \
  --output /path/to/new_qualification_record.json
```

출력 파일은 새로 생성하며 기존 파일을 덮어쓰지 않는다. 정상적인 음성·미확인 판정도
기록 저장에 성공하면 종료 코드 0이다. 스키마·입력 불일치·저장 오류는 종료 코드 2다.
내용에 따른 양성·음성은 저장된 `result.decision`으로 확인한다.
자동 재시도는 없으며 Codex 제안 수정 또는 재파싱 후 새 실행 ID·출력 파일로 다시 처리한다.
파싱 결과가 바뀌면 구성 분석도 새 native 해시로 입력을 준비하고 제안을 다시 작성한다.
판정 기록이 바뀌면 분석할 범위를 다시 검토한다. 현재 구성 분석 CLI가 문서 적합성
기록을 자동 재검증하는 것은 아니다.

실제 실행은 [기존 다품목 시험의 v1 계약 검증](codex_analysis_2026_10_20.md#v1-계약과-단독-실행-검증)에 기록한다.
