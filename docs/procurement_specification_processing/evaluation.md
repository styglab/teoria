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
실행기 실패 시 완료한 development/regression 묶음의 점수와 종료 코드·예외 유형·Teoria 코드 위치는
요약에 남긴다. 원문 본문·모델 응답·예외 메시지와 전체 로그는 보존하지 않는다.
전체 묶음이 끝나지 않은 기록은 평가 완료나 품질 승인으로 간주하지 않는다.
분리한 요약 위치는 `evaluate --state-dir PATH prepare ...`처럼 단계 이름 앞에 지정한다.
다른 작업의 코드 변경이 섞이지 않도록 작업 사본을 분리한다. 코드·파서 변경을 감지하면 비교를 중단한다.

## 어떤 문서를 평가하나

| selection_mode | 입력과 분할 | 판정 한계 |
|---|---|---|
| `classified_random` 기본 | 분류·공고 metadata를 검증한 원본을 그룹별 무작위 분할 | 기본 서버 분류 4321150102, 목표 10개. 실제 독립 그룹·노출 이력에 따라 한계 표시 |
| `unclassified_random` | 분류 없는 새 로컬 원본을 해시·양식 그룹으로 분할 | 이력·양식 확인이 필요하며 분류는 null 유지 |
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
| purpose, replay_of | 일반 추출 개선, 평가기 보정 또는 기존 고정 표본의 품질 관측 재실행 |

모델을 고정하지 않거나 원문·사례가 부족하면 개선을 확정하지 않는다.
`purpose: quality_assessment`와 `replay_of`는 중단했던 표본의 현재 품질을 관측할 때 사용한다.
원본·사례·표본 전체·분할·실행 설정을 보존하고 `prepare → baseline → finish`로 한 번 실행한다.
판정은 `assessment_recorded`이며 개선 승인이나 새로운 독립 검증을 뜻하지 않는다.
`resume_from`에 정리가 완료된 이전 `quality_assessment` 실행 ID를 지정하면 이미 점수를
저장한 정상 문서만 재사용한다. 원본·사례·분할·모델·실행 설정·processor·grader·파서 실행 환경이
모두 같고 문서별 점수 checksum이 일치해야 한다. 실패 문서는 다시 실행하며 미완료 문서는
원래 분모에 남긴다. 부분 완료라도 기술 실행이 성공한 문서는 재사용할 수 있다.
이 기능은 평가 재개이며 일반 문서 처리의 단계 checkpoint 재사용과 별개다.
Parser 버전뿐 아니라 소스와 설치 패키지 해시도 고정하고 실행 전후 확인한다.
평가 Flow는 별도 임시 Prefect 환경에서 실행하며 운영 DB에 행을 만들지 않는다.

## 사례가 확인하는 것

| 사례 | 확인 |
|---|---|
| 엔티티 | 원문 근거가 있는 대상의 존재·필요한 상위 대상 |
| 관계 | 출발·도착·방향·종류·원문 근거 |
| 구성 목록 (`compositions`) | 지정 부모의 직접 구성 전체를 원문 목록과 대조. 누락·잘못 추가·동명 대상 중복도 실패로 처리 |
| 수량 (`quantities`) | `declared_quantities`의 대상·원문 수량·단위·근거. 다른 대상의 수량이나 중복 수량은 불인정 |
| 요구조건 | 대상·값·단위·연산·역할·범위·원문 구절과 명시한 조건 |

사례는 AI 작성 silver와 실제 사람 검토 human_reviewed를 구분한다.
원문으로 확인해 고정한 entity_aliases만 사용하고 유사 문자열을 임의로 허용하지 않는다.

구성 목록 사례는 원문에서 **직접 구성의 전체 범위가 확인되는 부모만** 작성한다.
같은 자식을 가리키는 구성/구매 범위 관계가 함께 있어도 한 대상으로 세고, 서로 다른
대상이 같은 이름으로 중복 추가되면 실패한다. `PC SYSTEM`을 데이터 처리 시스템 아래에서
최상위로 올린 경우처럼, 존재하는 구성품의 잘못된 승격도 잡는다. 미주석 하위 계층 전체의
정확도를 의미하지 않으며 구성 목록 검사는 표준 적용이나 별도 서비스를 실행하지 않는다.
원본 기반 사례는 [lcms_composition_cases.json](../../backend/tests/features/specification_processing/evaluation/fixtures/lcms_composition_cases.json)에 유지한다.
이 사례는 직접 구성 9개·PC의 부모·명시 수량 9건을 다룬다. 악세서리의 미기재 수량은 분모에 넣지 않는다.

모델명 뒤에 성능값이 붙은 원문 명칭도 먼저 확인한다. 예를 들어 CPU의 모델명과
`모델명 3.50GHz 8‑코어 16‑스레드 48MB`가 같은 대상의 원문 표현임이 확인되면,
별도 보정 사이클에서 두 표현을 명시적인 동의 명칭으로 고정할 수 있다.
단순 접두어 일치나 모델 번호가 다른 이름은 인정하지 않는다. 관계 방향과 속성의
소유 대상·값·단위·조건 검사는 그대로 유지한다. 이전 명칭 불일치가 해소된 것은
평가 기준 보정이며 추출 로직의 개선 점수로 보고하지 않는다.

진공펌프 원문은 구매 범위의 `고효율 진공펌프`, 표지의 `인버터제어형 진공펌프`,
동일 구매 대상의 기술 표에 적힌 `진공펌프`를 구분해 표기한다.
[vacuum_power_cases.json](../../backend/tests/features/specification_processing/evaluation/fixtures/vacuum_power_cases.json)은
이 원문 대응을 명시적인 별칭으로 고정해 600 kW·425 kW 두 사례를 확인한다.
추출 결과의 대상 ID를 합치거나 유사 명칭을 포괄적으로 허용하지 않는다. 같은 별칭으로
매칭되는 대상이 여러 개면 요구조건 소유는 계속 불명확한 것으로 판정한다.

핵심 표시명과 긴 원문 명칭을 분리한 결과도 원문으로 확인한 별칭만 고정한다.
농기계 원문의 두 Target/반사체 항목은 용도와 수량이 다르므로 별도 대상으로 유지한다.
[farm_target_cases.json](../../backend/tests/features/specification_processing/evaluation/fixtures/farm_target_cases.json)은
이름 분리·상위 구성·각각의 5 EA 이상/2 EA 이상 조건을 확인하는 알려진 원본의 silver 사례다.
짧은 명칭을 허용해도 대상 통합·수량 교환·비교 연산 반전은 인정하지 않는다.
이 보정은 일반적인 이름 유사성 매칭이나 신규 문서의 독립 검증을 의미하지 않는다.
해당 사례의 적용 범위 라벨과 관계의 지정 근거 구절은 보정 실행에서 불일치가 남았다.
값·단위·연산 일치와 구분해 검토해야 하며, 이 사례 전체의 일치를 검증 완료로 간주하지 않는다.

서버의 모델명·구성 관계·주요 사양·수량·지원 한도 보정 사례는
[server_component_cases.json](../../backend/tests/features/specification_processing/evaluation/fixtures/server_component_cases.json)에
원본 해시와 함께 유지한다. 알려진 샘플의 회귀 기준이며 새 문서 검증으로 계산하지 않는다.

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

## 반복 개선 운영

개선 요청 한 번에 최대 3사이클을 수행하고, 연속 2회 개선이 없으면 종료한다.
에이전트가 새 원본 확보·원문 대조 사례 작성·코드 수정·검증을 수행한다. 상시 백그라운드 작업이나
정기 실행 배포는 추가하지 않는다. 기존 10개 샘플은 회귀용으로 유지하며 신규 검증으로 재포장하지 않는다.

```bash
uv run --project backend --locked teoria-pipelines specification evaluate status
uv run --project backend --locked teoria-pipelines specification evaluate discover --root .artifacts/sample --limit 100
```

`discover`는 로컬 원본의 경로·해시·크기·사용 이력을 반환한다. 심볼릭 링크, 생성 산출물의 sources
하위 폴더와 상태 폴더는 탐색하지 않는다. 파일당 25 MiB, 총 해시 입력 256 MiB, 후보 최대 1000개,
탐색 파일 10000개·폴더 1000개로 제한하고 제한 도달은 bounded로 알린다. 분류·양식·정답 사례는
만들지 않는다. previously_used=false도 과거 노출이 없다는 증명은 아니며 외부 이력 확인이 필요하다.

분류 없는 새 원본은 `selection_mode: unclassified_random`, `classification_code: null`로
지정할 수 있다. 실제 template_family와 사용 이력을 확인하고 분류코드를 추정하지 않는다.
파일 해시·양식 그룹을 통째로 개발/검증에 나누며 회귀 원본 및 과거 사용 그룹은 신규 표본에서
제외한다. 공고번호 null을 같은 공고로 묶지 않는다. 이력 확인 또는 양식 정보가 부족하면
최종 판정은 inconclusive이며, 독립 그룹·고정 사례·회귀 실행이 부족해도 개선을 확정하지 않는다.

추출 평가 통과 뒤 전체 검증은 기존 `teoria-pipelines specification run --manifest ...`로 실행한다.
전용 검증 Data DB·산출물 경로·Prefect 환경, 고정 표준/사전 snapshot을 사용하고 자동 승인과
추출 재사용은 끈다. 실제 Task 00–09 완료·부분 상태, DB catalog/result 조회, 산출물 checksum,
웹의 구성·속성·원문 표시를 확인한다. 추출 CLI가 이 DB/UI 검증을 대신 수행하는 것은 아니다.
격리 환경이 없으면 통합 검증 미실행을 기록하고 배포 완료로 보고하지 않는다.

최종 보고를 기록한 뒤 평가의 최종 결과·중간 결과·모델 응답·로그·진단 ZIP·화면 캡처·임시
복사본을 정리한다. 입력 원본과 사용자가 제공한 manifest, 코드 수정과 최소 회귀 사례,
state.json/index.md의 비교·사용 이력만 보존한다. 통합 검증은 전용 환경을 제거하거나 해당
실행 소유의 행·객체만 참조 확인 후 정리하고 결과를 보고한다. 운영 결과의 보존 정책은 바꾸지 않는다.
로컬 정리 실패는 cleanup=pending으로 남으며 `status` 확인 후 `abort`로 재시도한다.
정리 재시도가 이미 완료한 비교 판정을 덮지 않는다. 테스트 실패·회귀의 rejected 판정도
모델 미고정·동일 코드·독립 검증 부족 때문에 inconclusive로 덮지 않는다.

## 외부 추출 도구 비교

동일한 고정 원본으로 외부 추출 도구를 비교할 때도 `prepare → baseline`으로 원본·사례·
현재 파이프라인 실행을 먼저 고정한다. 외부 도구의 실제 출력을 기존 추출 corpus 계약으로
변환하고, 원문 node ID·리터럴 값·소유 대상을 보존한다. 변환 중 유사 이름 매칭이나 값·단위
추정을 넣어 점수를 보완하지 않는다. 라이브러리별 파서/모델/프롬프트/분할 설정 차이를 기록한다.

```bash
uv run --project backend --locked --group orchestration teoria-pipelines specification evaluate compare \
  --cycle-id tool_comparison_example --corpora /tmp/teoria_specification_eval_.../corpora.json
```

`corpora.json`은 `[{"name":"tool_name","path":"/tmp/teoria_specification_eval_.../tool.json",
"settings":{"model":"pinned_model","parser":"same_parsed_input"}}]` 형태다.
이 파일과 corpus는 모두 해당 사이클 작업공간 내부에 있어야 한다. 도구별 실패 문서도
고정 사례 분모에 남기며 기존 scorer로 비교한다. 결과는 누적 state의 `tool_comparison`에
보존하고 작업공간 전체를 정리한다. 판정은 `comparison_only`이며 수정 전후 품질 승인이나
배포 성공으로 기록하지 않는다. 파서 변환 성공률·문자열 보존 검사도 추출 정확도와 구분한다.

## 개선안의 품질 조건 검사

```bash
uv run --project backend --locked --extra api --group orchestration \
  teoria-pipelines specification evaluate quality-check --cycle-id example_cycle
```

이 명령은 기존 누적 평가 기록을 읽으며 새 추출·채점·정리를 실행하지 않는다. 통과에는
accepted 개선 평가, 현재 코드 revision 일치, 테스트 성공, 정리 완료, 노출 이력 확인,
개발·검증·회귀의 고정 사례 전부 일치와 측정 오류 0건을 요구한다. validation은 사람이
검토한 정답이어야 한다. 기록·지표 누락은 통과시키지 않으며 blocked이면 종료 코드 1을 반환한다.
이 기준은 관측된 실패가 없는 개선안을 선별하는 보수적인 초기 기준이다.

통과 범위는 고정된 추출 사례다. 문서 전체 재현율, 모든 조건의 의미 동등성, 표준 적용,
DB·S3·UI 연동이나 운영 배포 성공을 인증하지 않는다. 출력은 항상 `deployment_ready: false`와
남은 통합 검증을 구분한다. 현재 배포 스크립트의 강제 gate에는 아직 연결하지 않았다.
기존 샘플은 모두 노출된 회귀 자료이며 새 원본과 사람 검토 정답을 확보해야 독립 품질 승인을 진행할 수 있다.
