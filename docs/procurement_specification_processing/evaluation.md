# 규격서 추출 품질 평가

**같은 원본·모델·파서·사례로 수정 전후를 비교**한다. 출력 개수나 실행 성공을 정확도로 간주하지 않는다.
평가 대상은 실제 공통 추출 Task 00–05다. 사전·표준 적용·운영 DB 완료·배포는 별도 검증한다.

## 평가 순서

| 단계 | 하는 일 |
|---|---|
| prepare | 원본·설정·사례·분할·채점기를 고정하고 사용 이력 기록 |
| baseline | 수정 전 실제 파싱·추출 실행 |
| 코드 수정 | 원문 근거가 있는 결함의 소유 모듈과 최소 회귀 테스트 수정 |
| candidate | 같은 고정 입력으로 수정 후 실행 |
| finish | 점수·회귀·테스트·환경 변경 확인, 결과 기록과 임시 산출물 정리 |

평가 실행은 기존 CLI를 사용한다. 별도 샘플러·채점기·정리 스크립트를 만들지 않는다.
[improve-specification-processing 스킬](../../.agents/skills/improve_specification_processing/SKILL.md)이
원문 분석·수정·검증을 조립한다. 사람이 매번 단계별 명령을 입력할 필요는 없다.

```bash
uv run --project backend --locked --group orchestration teoria-pipelines specification evaluate schema
uv run --project backend --locked --group orchestration teoria-pipelines specification evaluate prepare --manifest /data/evaluation.json
uv run --project backend --locked --group orchestration teoria-pipelines specification evaluate baseline --cycle-id example_cycle
# 기준 실행 후 소유 코드를 수정한다.
uv run --project backend --locked --group orchestration teoria-pipelines specification evaluate candidate --cycle-id example_cycle
uv run --project backend --locked --group orchestration teoria-pipelines specification evaluate finish --cycle-id example_cycle
```

중단은 `evaluate abort --cycle-id example_cycle`을 사용한다.
분리한 요약 위치는 `evaluate --state-dir PATH prepare ...`처럼 단계 이름 앞에 지정한다.
다른 작업의 코드 변경이 섞이지 않도록 작업 사본을 분리한다. 코드·파서 변경을 감지하면 비교를 중단한다.

## 어떤 문서를 평가하나

| selection_mode | 입력과 분할 | 판정 한계 |
|---|---|---|
| `classified_random` 기본 | 분류·공고 metadata를 검증한 원본을 그룹별 무작위 분할 | 기본 서버 분류 4321150102, 목표 10개. 실제 독립 그룹·노출 이력에 따라 한계 표시 |
| `fixed_sources` | 명시한 기존 원본 전체를 development에, 별도 원본은 regression에 배치 | 알려진 원본 비교. sampled_documents=0, 독립 검증·자동 accepted로 표시하지 않음 |

기본 모드는 분류 metadata의 해시·공고/분류 JSON pointer를 실제 확인한다. 파일명으로 분류하지 않는다.
같은 공고·양식·동일 바이트 그룹은 분할하지 않고 과거 사용 원본·공고·양식을 신규 표본에서 제외한다.

분류 없는 기존 원본은 `selection_mode: fixed_sources`, `classification_code: null`을 명시한다.
문서의 분류·공고·분류 근거도 생략한다. 근거를 만들어 넣거나 기본 검증을 우회하지 않는다.
같은 바이트 중복을 거부하고 노출 이력을 누적한다. 테스트·사례가 좋아져도 독립 validation이 없으면 inconclusive다.
실제 악화나 테스트 실패는 rejected를 유지한다.

## 입력 계약

`schema` 명령이 현재 입력 형식의 기준이다.

| 필드 | 의미 |
|---|---|
| cycle_id | 새 비교 ID |
| case_contract_version | 현재 2 |
| documents, regression_documents | 원본 URI·해시·출처와 고정 사례 |
| model, parser_python | 비교할 모델과 파서 Python |
| sample_size, seed | 기본 모드의 표본 목표와 고정 난수 |
| history_reviewed, excluded_notices, excluded_sha256 | 과거 노출 확인과 제외 근거 |
| concurrency, model_concurrency, model_timeout_seconds | 실행 범위·동시 호출·제한 |
| purpose, replay_of | 일반 추출 개선 또는 별도의 평가기 보정 재실행 |

모델을 고정하지 않거나 원문·사례가 부족하면 개선을 확정하지 않는다.
Parser 버전뿐 아니라 소스와 설치 패키지 해시도 고정하고 실행 전후 확인한다.
평가 Flow는 별도 임시 Prefect 환경에서 실행하며 운영 DB에 행을 만들지 않는다.

## 사례가 확인하는 것

| 사례 | 확인 |
|---|---|
| 엔티티 | 원문 근거가 있는 대상의 존재·필요한 상위 대상 |
| 관계 | 출발·도착·방향·종류·원문 근거 |
| 요구조건 | 대상·값·단위·연산·역할·범위·원문 구절과 명시한 조건 |

사례는 AI 작성 silver와 실제 사람 검토 human_reviewed를 구분한다.
원문으로 확인해 고정한 entity_aliases만 사용하고 유사 문자열을 임의로 허용하지 않는다.

- evidence_mode=existence는 대상 존재, mention은 지정 구절까지 일치를 확인한다.
- owner는 동명 대상의 상위 문맥을 구별한다.
- qualifiers_raw=null은 한정자를 주석하지 않았다는 뜻이다.
- 기본 required_subset은 명시한 필수 조건을 확인한다. exact와 빈 배열은 조건이 없어야 한다는 별도 주장이다.
- forbidden_qualifiers는 원문에 없는 금지 조건을 검사한다.
- 같은 원문 위치의 동일 관찰 반복과 다른 위치의 실제 반복 기재를 구분한다.

사례에 없는 문서 전체 요구조건의 재현율이나 모든 추가 조건의 동등성까지 측정하지 않는다.
실패 문서를 분모에서 제외하지 않는다. 부분 사례 일치 수치를 전체 정확도로 환산하지 않는다.

## 판정과 기준 보정

기본 개선 판정은 개발 사례 개선·검증/회귀 악화 없음·필요한 사례·테스트 성공을 함께 요구한다.
부족한 사례·환경 변경·같은 코드·고정 원본만의 비교는 한계를 기록한다.
검증 결과는 candidate 코드가 고정된 뒤 finish에서 공개한다.

원문과 라벨·채점기가 충돌하면 진행 중 사이클을 중단한다. 실행 중 기준을 수정해 점수를 올리지 않는다.
보정은 새 manifest의 `purpose: grader_calibration`, `replay_of: 이전 cycle_id`로 분리해
prepare → baseline → finish만 실행한다. 원본·분할·노출 이력은 유지하며 판정은 baseline_recorded다.

## 정리와 보존

finish/abort는 평가용 파싱·청크·모델 응답·전체 그래프·로그·임시 Prefect 상태를 정리한다.
강제 종료 후 남은 작업도 abort로 정리한다. 원본·운영 S3·공유 DB·기준 표준을 삭제하지 않는다.
일반 업무 실행의 영구 산출물 보존과 다른 정책이다.

누적 `.artifacts/specification_improvement/state.json`·`index.md`에는 입력·코드·사례·환경 해시,
노출 이력·전후 수치·판정·정리 용량을 남긴다. 게시 Ontology나 authoritative metadata를 변경하지 않는다.

[기존 네 원본 평가](../../archive/documentation/verification/goods_relation_repair_2026_10_28.md)는
고정 사례 점수와 구성 규칙의 동작 확인이 다른 검증임을 보여준다.
원문 사례의 회귀 계약은 `backend/tests/features/specification_processing/evaluation/`에 있다.
