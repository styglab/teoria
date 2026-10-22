# 공고 이해와 재귀 구성 트리 기반 규격 분석

2026-10-22 합의한 처리 순서를 구현한 **오프라인 분석 배치 v3 (`composition_first_batch_v3`)**다.
기존 문서 전체 대상 일괄 추출 → `link` 경로와 문자 수 기반 분할 코드는 제거했다.
이미 확보한 원본·파싱 결과만 입력으로 사용한다. 다운로드·파서·OCR·DB·Prefect·
Runtime API·Registry·Ontology 게시에는 연결하지 않는다.

실행 코드는 Pipelines의 조달 규격 기능이 소유한다.
[단계 조립·CLI](../../pipelines/src/teoria_pipelines/domains/public_procurement/specification_intelligence/semantic_batch.py),
[데이터 계약·검사](../../pipelines/src/teoria_pipelines/domains/public_procurement/specification_intelligence/semantic_ir.py),
[고정 사전 재사용·의미 평가](../../pipelines/src/teoria_pipelines/domains/public_procurement/specification_intelligence/semantic_evaluation.py)를
기준으로 한다. JSON Schema는 계약 모델의 `model_json_schema()`에서 생성한다.

## 모델링 기준

사용자가 비교·검색하는 중심 대상은 서버·랙·모니터·키보드 같은 **납품 품목**이다.
CPU·메모리는 서버 내부 규격을 설명하는 문맥에서 **구성 규격 대상**이다.
‘교체용 CPU 4개 별도 공급’처럼 독립 공급 근거가 있으면 CPU도 납품 품목이 된다.
단어 사전으로 역할을 고정하지 않고 문서의 납품 지시와 목록·표·본문을 함께 판단한다.
별도 가격·품목 코드·수량 기재는 품목 식별의 필수 요건이 아니다.

| 구분 | 예 | 표현 |
|---|---|---|
| 발주 묶음 | 서버 시스템 1식 | `delivery_group` 대상과 발주 포함 관계 |
| 납품 품목 | 서버 2대, 랙 1대 | `delivery_target` 대상 |
| 내부 규격 대상 | 서버 A의 CPU 구성 | 품목을 `owner_item_id`로 참조하는 대상 |
| 속성 의미 | 코어 수, 용량 | 요구조건의 의미, 이후 사전 정의에 매핑 |
| 조건 | 16코어 이상 | 원문 값·단위·연산자·한정자 |
| 외부 문맥 | 기보유 스위치, 참고 장비 | `existing` / `external` 대상 |

내부 대상도 연결을 위해 ID를 갖지만 실제 제조번호가 있는 제품 개체를 뜻하지 않는다.
구성 대상을 반드시 만들거나 고정된 품목 → 구성품 → 속성 3단계를 강제하지 않는다.
문서 제목·들여쓰기·표의 부모 관계를 물리 구성으로 복사하지 않는다.

## 단계와 산출물

```text
저장된 원본·파싱·파서 실행 기록
  → prepare: 입력·계약·프롬프트 고정
  → identify: 구매 목적·최상위 납품 대상 → 구성품 → 구성품의 구성품
  → review_structure: 원문 전체와 구성 트리 대조, 명백한 오류 시 속성 추출 차단
  → extract: 주요 구성품 하위 트리별 속성·조건 연결 + 공통·미귀속 구간 추출
  → resolve: 문서 전체의 동일 대상 연결·귀속·관계 정리
  → validate: 원문 대조·누락·과분리·오귀속 검토
  → integrate: 문서 간 공통 의미 사전·매핑 제안
  → finalize: 그래프·사전 초안·검토·미해결 목록 저장
```

| 단계 | 입력과 처리 | 산출물 |
|---|---|---|
| prepare | 원본·native JSON·파서 기록의 SHA-256, 파서·버전·성공·OCR 비활성 확인 | `manifest.json`, `contract.json`, `inputs/`, `prompts/`, `freeze.json` |
| identify | 구매 목적·통합 범위·재귀 구성 트리·관련 node ID 식별 | `identify/<document_id>.json` |
| review_structure | 전체 문서와 구매 경계·구성 계층을 먼저 대조 | `review_structure/<document_id>.json` |
| extract | 품목 목록을 고정하고 각 품목의 관련 원문에서 구성 대상·조건·관계를 함께 추출 | `extract/<document_id>.json`, 품목별 추론 응답 |
| resolve | 원문 전체와 추출 관찰을 대조해 동일 대상 연결과 조건 귀속·관계 정리 | `resolve/<document_id>.json` |
| validate | 원문 전체와 그래프를 대조하고 종류별 오류·모호성 기록 | `validate/<document_id>.json` |
| integrate | 문서 내 검증을 마친 관찰의 표준 의미 통합, map/hold/exclude 판단 | `integration.json` |
| finalize | 모든 선행 receipt와 의존 입력을 재확인해 새 결과 디렉터리에 저장 | 최종 파일 묶음 |

### 1. 입력과 문서 구조

`prepare`는 파싱을 실행하지 않는다. `document_evidence.py`가 저장된 kordoc 결과의
제목·문단·표·셀·부모·페이지·좌표·병합 범위를 근거 노드로 표현한다. 누락된 파서 구조를
복원했다고 주장하지 않는다. 이미지·OCR 필요 경고는 미확인 영역으로 남긴다.

### 2. 공고 이해와 재귀 구성 트리

`ItemInventory.purchase_summary`와 `scope_evidence`는 무엇을 왜 구매하며 통합 납품 범위가
어디까지인지 설명한다. `entries`는 엔티티·단일 category·직접 부모(parent)·근거·관련
`node_ids`를 가진다. 부모를 재귀적으로 연결하므로 깊이 제한이 없다. 구성품도 엔티티이며,
속성은 각 엔티티를 설명하는 값·조건이다. 제목과 표 헤더는 원문 구조로만 보존한다.

category는 `delivery_item`, `bundle`, `component`, `service`, `existing`, `external`,
`unknown` 중 하나다. 문맥별 의미를 복수 role로 나열하지 않는다. schema도 단일 role만
허용하고 validator는 category별 정확한 값을 검사한다. component의 role 값은 `component`다.
하드웨어와 소프트웨어 모두 구성품이며, 물리 포함 여부는 `physical_part_of` 관계로 구분한다.

`parent.parent_id`는 바로 위 부모, `owner_item_id`는 최상위 납품 품목이다. 관계는 일반 구성
`component_of`, 명시적 물리 포함 `physical_part_of`, 묶음 소속 `delivery_member_of`,
서비스 대상 `service_for`로 구분한다. 근거 없는 부모를 확정하지 않으며 부모 불명 구성품은
candidate로 남긴다. 부모 누락·순환·다른 최상위 품목 소속을 검사한다.

`review_structure`는 구매 범위와 구성 트리를 별도 추론으로 대조한다. 명백한 과분리·누락·
잘못된 포함 관계가 error로 남으면 속성 추출을 차단한다. 모호성은 후속 검토에 남긴다.
이 모델 검토는 독립 정답이나 사람 승인이 아니다.
`supported`는 추출 근거가 있다는 뜻이며 사람 승인 상태가 아니다. 불명확한 대상은
`candidate`로 보존한다. 같은 장비의 명칭과 모델명을 별도 품목으로 과분리하지 않는다.

모든 텍스트 노드는 하나 이상의 대상 관련 구간, `shared_node_ids`(공통),
`unresolved_node_ids`(미귀속·기타)에 포함되어야 한다. 소속을 모른다고 버리지 않는다.
여러 품목이 같은 표·헤더를 공유할 수 있으므로 구간 중첩은 허용한다.

`BatchInput.structure_feedback`는 문서 ID별 이전 모델 검토 제안을 고정하는 선택 입력이다.
새 revision에서만 사용하며 원문 사실이나 승인 정보로 취급하지 않는다. identify는 원문을
다시 대조해 타당한 지적만 반영한다.

### 3. 품목별 구성·규격 추출

코드가 검토된 구성 트리에서 주요 구성품 가지별 추출 작업을 만든다. 하위 구성품이 있거나
명칭·수량 외의 전용 원문 구간이 있는 가지를 나누고, 공통 부속품과 상위 대상의 규격은
나머지 작업에 묶는다. 문자 수로 자르지 않는다. `entity_scope_ids`는 각 작업의 직접 대상
범위이며 다른 가지의 속성을 추출하는 것을 차단한다. 모든 가지의 소속 납품 품목 ID는 유지한다.

관련 표는 머리글·단위·병합 문맥을 잃지 않도록 전체 셀을 함께 제공한다. 보강한 셀은
`supporting_node_ids`로 구분하며 원래 대상 배정을 바꾸지 않는다. 첫 행을 무조건 헤더로
가정하거나 다른 품목 행의 값을 현재 품목으로 복사하지 않는다. 보강 구간은 인용·검사할 수
있지만 그 구간에만 등장하는 품목별 요구를 중복 추출하지 않는다.

새 배치의 기본값은 `extraction_layout=table`, `extraction_partition=subtree`다.
이 필드가 없는 이전 고정 실험은 당시 `inventory/item` 계획으로 검증한다. 입력·프롬프트·
작업 계획을 바꾸는 실행은 새 revision에 만들며 이전 성공으로 집계하지 않는다.
확인한 부모 관계는 `structure_<entity_id>` 관계로 그래프에 보존하며 resolve가 제거·변경할 수 없다. 입력은 고정한 품목 목록, 해당 품목의 관련 원문,
원문 구조 이해에 필요한 상위 노드다. 별도 공통 작업은 공통·미귀속 구간과 개별 품목에
배정되지 않은 문맥 대상·발주 묶음 구간을 처리한다. 품목이 없는 문서도 공통 작업으로
처리할 수 있다. 구성·속성·관계는 같은 문맥에서 함께 추출한다.

추출 중 새 납품 품목을 추가할 수 없다. 발견한 누락은 이슈로 남기고 새 revision의
식별 단계를 수정한다. 새 관찰 ID는 작업별 접두어로 분리하며 다른 품목의 원문을
인용하는 것을 거부한다. 대상 목록에 있는 기존 대상의 ID는 재사용한다.

요구조건은 다음을 구분한다.

- `subject_id`: 직접 규격 대상. 서버 A의 CPU 구성 등.
- `item_ids`: 조건이 적용되는 납품 품목 목록.
- `scope`: `item` / `common` / `cross_item` / `unknown`.
- `qualifiers`: CPU당·전체·모듈당, 장착·지원·기보유, 측정 기준.
- `evidence`: 값 셀·헤더·각주 등 복수 원문 근거.

예를 들어 서버 A의 CPU 코어 수 조건은 `subject_id=CPU 구성`, `item_ids=[서버 A]`다.
코어 수 16과 ‘이상’이 명확해도 CPU당인지 전체인지 불명확하면 한정자만 unknown으로 둔다.
공통 보증 조건을 모든 품목에 자동 복사하지 않는다. AND/OR/IF는 구성 계층과 분리한다.

### 4. 동일 대상과 관계 정리

`ResolutionProposal.identities`는 `alias_id → canonical_id`와 양쪽 관찰을 연결하는
원문 근거를 갖는다. 서버명과 모델명이 같은 대상이라는 판단을 표현하되 원래 대상과
그 근거는 삭제하지 않는다. 조건의 대상과 품목 참조는 canonical ID로 정리한다.
같은 유형이라는 이유로 서로 다른 서버나 NIC를 병합하지 않는다.

수정할 수 있는 조건 정보는 직접 대상·적용 품목·scope뿐이다. 값·단위·연산자·한정자·
원문 근거·기존 조건 논리는 바꾸거나 삭제할 수 없다. 잘못된 추출은 새 revision에서
수정한다. 다른 품목의 내부 대상을 같은 대상으로 병합하거나 품목과 내부 대상을
병합하는 것을 거부한다.

발주 포함(`delivery_member_of`), 물리 구성(`physical_part_of`), 규격 대상(`specifies`),
연결(`connected_to`), 호환(`compatible_with`)을 구분한다. 관계마다
`explicit` / `interpreted` / `ambiguous`와 이유·근거를 보존한다.
`cross_task_groups`로 추출 작업 사이의 AND/OR/IF를 근거와 함께 추가할 수 있다.
기존 논리 그룹은 보존하고 새 ID는 `resolved_`로 시작한다. 문서 그래프는 단일 부모 트리가 아니다. 동일성·물리 구성·발주 포함·조건 논리의 순환을 검사한다.

### 5. 원문 검증

코드 검사는 원문 인용·참조·값·연산자·차원·귀속 일관성·구간 확인 범위를 검사한다.
차원은 스키마의 선택값으로 제한하고 추출 입력에 단위별 차원표를 제공한다.
예를 들어 개수·코어 수·포트 수의 차원은 `count`이며 `quantity` 같은 임의 코드를 만들지 않는다.
별도 모델 검토는 다음 문제를 원문과 대조한다.

- 납품 품목 누락과 과분리, 내부 구성품의 품목 오인
- 다른 품목으로의 조건 오배정과 동일 대상 오병합
- 서버당·부품당·전체 수량, 총용량·모듈당 용량, 장착·지원 혼동
- 근거 없는 관계, 조건 누락과 논리 손실

검토 입력에는 코드가 구성한 `processing_history`도 포함한다. 이전 추출 작업의
`source_node_ids`, 식별 응답·수정 응답의 존재, 초기 응답을 현재 계약으로 재검사한 오류를
제공한다. 단계별 `issues`는 모델 처리·해석 메모이며 원문 사실이나 승인 기록이 아니다.
이전 단계에 존재했던 필드가 현재 검토 입력의 최상위에 없다는 이유로 원문 오류를
만들지 않도록 처리 이력과 문서 근거를 구분한다.

검토는 그래프 해시에 고정하고 모든 대상·조건·관계·동일성·논리 그룹과 완전성 항목을
확인한다. `error`가 있으면 의미 통합과 고정 사전 재사용을 차단한다. `ambiguity`는
미해결 목록에 남긴다. 검토가 예측을 몰래 수정하거나 원문을 대체하지 않는다.
함께 수정할 수 있는 원문 필드·차원·연산자·관계 오류는 관찰 ID와 함께 모아서 전달한다.
첫 오류만 고친 뒤 다음 오류에서 다시 실패하는 것을 줄인다. 원문에 속성명이 없으면
`property_raw=null`이고 해석한 속성 의미는 `meaning`에 남긴다.
코드 검사와 모델 검토 통과는 독립 정확도나 사람 승인이 아니다.

### 6. 표준 의미 매핑과 저장

문서 내부의 동일 대상 연결과 문서 간 표준 개념 매핑은 다르다. RAM·주기억장치는
문맥이 일치할 때 공통 개념에 연결하고 요구값은 해당 문서 조건에 남긴다.
통합 입력의 `required_observation_refs`가 사전 매핑 대상의 정확한 목록이다.
대상·요구조건·관계 관찰만 포함하며 논리 그룹·coverage·issues·동일성 연결 자체는 포함하지 않는다.
매핑 누락·초과 오류에는 해당 ID를 명시한다.
미해결 속성은 hold하고 작업·서비스·기능 조건은 그래프에 보존하되 제품 속성 사전에서는
exclude한다. 같은 대상으로 연결한 별칭 관찰은 서로 다른 개념으로 매핑할 수 없다.

현재 `integrate`는 사전 **초안 구축**이다. 별도 `semantic_evaluation run`은 동일한
식별·추출·정리·검증 경로 뒤에 고정 사전을 재사용하는 **오프라인 실험**이다.
게시 사전 승인·증분 확장·운영 처리 흐름은 구현하지 않았다. 의미 관리·승인은 Platform이
소유하며 Pipeline이 Capability/Mapping Runtime을 호출하지 않는다.

최종 파일은 `inventories.json`, `document_graphs.json`, `validations.json`,
`dictionary.json`, `mappings.json`, `unresolved.json`, `summary.json`, `freeze.json`이다.
사전은 항상 suggestion이며 `human_reviewed=false`, `published=false`다.

## 실행과 재처리

입력 manifest 형식은 다음과 같다. 세 입력 경로는 절대 경로이고 실제 SHA-256을 사용한다.

```json
{
  "batch_id": "server_composition_v3",
  "documents": [{
    "document_id": "server_01",
    "notice_number": "notice_01",
    "source_path": "/absolute/original.hwpx",
    "source_sha256": "<64자리 SHA-256>",
    "native_path": "/absolute/native.json",
    "native_sha256": "<64자리 SHA-256>",
    "parse_record_path": "/absolute/parse_record.json",
    "parse_record_sha256": "<64자리 SHA-256>"
  }]
}
```

```bash
uv run --locked --package teoria-pipelines python -m \
  teoria_pipelines.domains.public_procurement.specification_intelligence.semantic_batch \
  prepare --manifest /path/to/request.json --output-dir /path/to/new_batch

uv run --locked --package teoria-pipelines python -m \
  teoria_pipelines.domains.public_procurement.specification_intelligence.semantic_batch \
  run --batch /path/to/new_batch --stage all --concurrency 2 --timeout 240

uv run --locked --package teoria-pipelines python -m \
  teoria_pipelines.domains.public_procurement.specification_intelligence.semantic_batch \
  finalize --batch /path/to/new_batch --output-dir /path/to/new_result
```

`--stage identify|review_structure|extract|resolve|validate|integrate`로 한 단계만 실행할 수 있다.
`context`는 단계 입력을 저장하고 `accept`는 같은 검사를 거쳐 직접 작성한 제안을
제출한다. 직접 작성한 제안은 자동 추출 성능으로 집계하지 않는다. extract 제출 형식은
`{"parts": [ItemExtraction, ...]}`이며 모든 품목·공통 작업이 필요하다.
`context --stage extract --document-id server_01 --task-id item_000`으로 개별 입력을 확인할 수 있다.

동시 실행은 1~4개로 제한한다. 하위 트리 작업도 같은 호출 제한을 공유하며, 실패하면 형제 작업을 취소한다. 성공한 부분 응답은 동일 입력 재개 시 재검사한다. 호출마다 제한 시간을 적용하며 기본값은 240초다.
스키마·계약 오류는 한 번 수정 호출 후 실패하며 호출 실패를 수작업 예측이나 다른 모델로
대체하지 않는다. 실패 단계·시간·오류를 파일에 남긴다. 성공한 단계는 결과와 선행 입력의
receipt가 일치할 때만 재사용한다. 입력·프롬프트·해석을 바꾸면 새 배치 디렉터리를 만든다.
기존 v1/v2 배치는 이어 실행하지 않으며 `link`, `review`, `--chunk-chars`는 제거했다.
원본·파싱 입력에서 새 manifest로 시작한다.

## 검증 순서와 현재 한계

먼저 서버 한 건, 이후 다품목 문서와 다음 반례를 검증한다. 문서 전체의 원자 조건 정답을
확보하기 전에는 전체 추출 정밀도·재현율로 보고하지 않는다.

| 사례 | 확인할 결과 |
|---|---|
| 서버·랙·모니터·키보드 함께 납품 | 각각 품목이며 내부 부품으로 합치지 않음 |
| CPU 별도 공급 | CPU도 품목, 서버 내부 CPU 규격과 구분 |
| 같은 종류의 서버 두 품목 | 각 CPU·용량 조건의 소속 보존 |
| 서버명·모델명·별도 페이지 설명 | 같은 대상 연결, 원래 관찰 보존 |
| 공통 보증·기보유 장비·미귀속 조건 | 자동 복사·삭제 없이 범위 보존 |
| 표 헤더·병합 셀·이미지 미확인 | 구조 근거와 확인 한계 보존 |

```bash
uv run --locked --package teoria-pipelines pytest pipelines/tests
```

과거 v1/v2 실행 기록은 당시 결과이며 v3 정확도·시간으로 재사용하지 않는다.
Harness2·검색 평가와 원본·파싱 corpus는 보존한다. 데이터 확대보다 소수 문서의
자동 처리 성공·실패·시간과 품목 누락·과분리·오귀속·오병합 평가를 먼저 확인한다.


2026-10-22 교체의 코드 검사·실제 서버 문서 실행·실패와 수정·최종 저장 결과는
[v2 교체 검증 기록](verification/item_first_pipeline_2026_10_22.md)을 따른다.
서버 1건은 추출·정리·원문 검토·통합·저장 경로를 확인했으며 최종 상태는 needs_review다.
이 결과를 독립 정확도나 신규 문서 일반화 성능으로 간주하지 않는다.

현재 v3의 변경·테스트·네 샘플 실행은 [재귀 구성 트리 검증 기록](verification/composition_tree_pipeline_2026_10_22.md)에 기록한다.
