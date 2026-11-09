# 규격서의 물품·구성품·분류·속성 모델

목표는 **어떤 물품이 무엇으로 구성되고, 어떤 특성과 조건을 요구하며, 근거가 어디에 있는지** 표현하는 것이다.
검색·비교·변경 확인은 이 구조를 사용하는 기능이다.
현재 작성 입력은 [goods.yaml](../../../backend/authoring/ontology_blueprints/goods.yaml)의 goods 2.0.0 Draft다.
현재 추출 JSON이 이 Draft의 전체 객체로 자동 적재·게시되는 것은 아니다.

업무 의미는 native Object·Property·Relationship로 정의하고, 문서의 값·조건·근거는
별도 관찰로 그 게시 개념을 참조한다. 현재 최소 업무 유형은 `goods.server`와
`goods.memory_module`이다. 분류코드마다 새 유형을 만들거나 모든 품목 속성을 한 객체에 모으지 않는다.

## 먼저 구분할 것

| 구분 | 예시 | 의미 |
|---|---|---|
| 물품 항목 | 특정 규격서의 시험장치 | 그 문서가 지시하는 대상 |
| 물품 유형 | 열화상카메라 | 여러 문서에서 사용하는 공통 정의 |
| 구성 관계 | 시험장치에 카메라가 포함됨 | 대상 사이의 포함·구성 진술 |
| 특성 정의 | 최대 측정온도 | 어떤 특성을 뜻하는지에 대한 공통 정의 |
| 속성 명세 | +1,000 ℃ 이상 | 특정 대상에 대한 값·단위·조건 |
| 원문 근거 | 표의 행·문단·인용 | 해당 해석을 확인할 위치 |

물품과 구성품은 문맥상의 역할이다. 카메라는 단독 구매 물품일 수도 있고 시험장치의 구성품일 수도 있다.
문서별 항목을 이름만으로 제조사 제품 모델·실물 자산과 합치지 않는다.

## 모델 목록

| 객체 | 저장하는 의미 |
|---|---|
| `specification_document` | 특정 원본 버전의 규격서 |
| `specified_item` | 그 문서의 물품·구성 대상 |
| `composition_statement` | 상위·하위 대상, 수량·조건·근거를 가진 구성 진술 |
| `property_statement` | 대상의 특성에 대한 원문 값·조건과 해석 |
| `requirement_statement` | 속성 하나로 축약하기 어려운 의무·조건 |
| `evidence` | 문서 버전의 원문 위치·인용 |
| `server` | 서버 업무 대상 유형; 전체 시스템 메모리 용량·소켓당 지원 상한·슬롯 수의 native Property |
| `memory_module` | 개별 시스템 메모리 모듈 유형; 모듈당 용량의 native Property |
| `classification_scheme` | 분류체계와 판본 |
| `classification_entry` | 해당 판본의 분류 항목 |
| `classification_assignment` | 대상에 대한 출처별 분류 주장·검증 상태 |
| `specified_service` | 설치·설정·시험 등 작업 항목 |
| `supply_scope` | 문서가 정한 납품 범위 |
| `supply_membership` | 대상이 납품 범위에서 맡는 역할 |
| `specified_context` | 적용 장소·시험 대상·참조 조건 등 문맥 |
| `specified_deliverable` | 지침서·성적서 등 납품 자료 |
| `item_relation_statement` | 데이터 전송·호환·고정·연계 등 대상 간 관계 |

객체의 고정 필드와 여러 소스가 공유하는 물품 특성의 업무 의미는 Ontology에서 작성·검토·게시한다.
위 모델 목록은 goods Draft의 작성 모델이며 사전에서 별도 정의를 작성하는 근거가 아니다.
사전은 원문 표현·문맥·근거와 게시 Stable Concept ID의 승인 연결만 관리한다.
사전 표현 ID·문서 대상 ID·Ontology Stable Concept ID는 서로 다르다.

이전 Draft의 `item_type`·`characteristic_definition`과 그 정의 객체를 잇던 관계는 새 작성안에서
제거했다. 기존 DB·applied 이력·고정 artifact는 변경하지 않는다. 문서의 `specified_item`에는
`type_concept_ref`, `property_statement`에는 `property_concept_ref`를 둔다. 참조는 게시 버전의
version_id·namespace·version·checksum과 Stable Concept ID를 함께 가진다.

`DocumentGoodsGraph`에도 같은 명시적 참조가 있으며 `type_ref`·`characteristic_ref`의 기존
`draft:` 문자열은 미해결 후보의 호환 표기다. 문자열이나 사전 ID를 게시 개념 ID로 간주하지 않는다.
고정 문맥을 사용한 그래프 검사는 개념 종류·버전·속성 owner를 대조하고 원문 관찰을 바꾸지 않는다.
checksum이 맞는 문맥만으로 현재 게시 권위·의미 동등성·승인이 확인되는 것은 아니다.

## 최소 메모리 의미와 원문 관찰

| 게시 전 업무 정의 | 적용 범위 | 구분할 값 |
|---|---|---|
| `goods.memory_module.capacity` | 모듈 하나 | 서버 전체 합계·GPU 메모리·지원 상한 |
| `goods.server.system_memory_capacity` | 서버 전체 | 모듈당 값·소켓당 상한 |
| `goods.server.memory_capacity_per_socket_limit` | CPU 소켓당 지원 한도 | 공급/장착 용량 |
| `goods.server.memory_slot_count` | 서버 전체 슬롯 수 | 공급 모듈 수·사용 슬롯 수 |

위 정의는 현재 Draft의 Stable Key이며 승인된 운영 개념 ID가 아니다. 기준/허용 단위는
Property가 소유하고 Blueprint에서도 `quantity_dimension`·`allowed_units`를 보존한다.
요구조건은 Property의 확정값으로 쓰지 않고 대상·게시 Property 참조·값·연산자·역할·범위·근거를
가진 관찰로 저장한다. 제품 명시값과 측정값도 같은 Property를 참조하되 정보 성격을 구분한다.

[서버 메모리 부분 예시](../../../backend/authoring/specification_examples/server_memory_graph.yaml)는
기존 서버 XLSX 원본의 SHA-256을 대조한 미게시 검토 자료다. 모듈당 32GB·공급 2개·소켓당 지원
3TB·전체 슬롯 32개를 구분한다. 원문에 없는 전체 공급 용량 64GB를 생성하지 않으며,
문서의 `per_socket`을 프로세서당·모듈당 범위나 전체 공급 용량으로 바꾸지 않는다.

## 물품과 구성품의 연결

```text
규격서
└─ 납품 범위
   ├─ 시험장치
   │  └─ 구성: 열화상카메라
   │     └─ 구성: 표준 렌즈
   ├─ 설치 작업 → 작업 대상: 시험장치
   └─ 사용 지침서
```

함께 납품한다고 모두 장비 부품은 아니다. 작업·문서는 납품 범위와 각자의 의미로 연결한다.
수량·필수 여부·조건·근거가 필요한 구성은 `composition_statement`로 보존한다.
상위 수량을 하위 구성품에 복제하지 않는다. 물리적 내부 장착과 일반 구성도 구분한다.

현재 추출에서 사용하는 관계는 다음과 같다. 이 이름은 추출 계약이며 Published Ontology 관계와 자동 동일시하지 않는다.

| 관계 | 방향·용도 |
|---|---|
| `in_procurement_scope` | 대상 → 구매 범위 |
| `component_of` | 구성 대상 → 상위 대상 |
| `physical_part_of` | 물리적 포함이 명시된 하위 → 상위 |
| `specification_for` | 상세 대상 → 포괄 명세 대상 |
| `service_for` | 작업 → 작업 대상 |
| `sends_data_to` | 발신 → 수신 |
| `compatible_with` | 호환 관계 |
| `same_target_as` | 동일 대상이라는 해석; 불확실하면 보류 |

문서의 제목·절·표 배치를 구성 관계로 자동 승격하지 않는다.
잘못된 유형·방향은 재판정하고 미해결·불확실·순환 관계는 보류한다.

## 분류 계층과 출처별 판정

대분류 → 중분류 → 소분류 → 세분류 → 세부품명은 **분류 계층**이다. 물품 구성 트리와 다르다.
분류는 관리기관·판본·코드를 함께 다룬다. 코드 접두사만으로 공식 부모·명칭을 만들어 내지 않는다.

- 원문 코드와 외부 metadata의 분류 주장을 출처별로 보존한다.
- 공식 체계와 대조한 항목만 확정 연결한다. 미해결·충돌 주장은 덮어쓰지 않는다.
- 주 물품의 분류를 하위 구성품에 전파하지 않는다.
- 물품분류번호·세부품명번호·물품식별번호·문서 행 번호를 구분한다.
- 분류가 없는 샘플은 없는 상태로 처리한다. 실제 데이터의 분류는 별도 근거로 받는다.

## 특성과 서비스

속성은 값만 저장하지 않는다. 대상·속성 의미·값·단위·연산·한정 조건·역할·범위·근거를 함께 보존한다.
납품 요구, 지원 한도, 기보유 사양, 선택·권장 조건을 섞지 않는다.
문자열·범위·허용차·집합 등도 필요하며, 현재 자동 값 검증이 모든 형태를 처리하는 것은 아니다.

설치·교육·검수는 서비스나 요구다. 관련 문서와 결과물도 장비 부품과 구분한다.
적용 문맥이 불분명한 항목은 검토 대상으로 남긴다.

## 원문 표현과 표준 정의

```text
원문 표현 → 승인된 의미 매핑 → 표준 개념 정의
```

예를 들어 원문의 ‘정격출력’을 인버터 문맥에서 정의한 전력 특성에 연결한다.
원문 표현이 존재한다는 사실은 동의어·의미 동등성의 증명이 아니다.
[물품 사전](expression_links.md)에서 저장 내용·승인·재사용 범위를 확인한다.
Published 개념을 문서에 적용하는 규칙은 [정규화 프로파일](specifications/normalization_profiles.md)이 맡는다.

## 현재 구현과 설계의 경계

| 구현 | 상태 |
|---|---|
| 일반 추출 그래프·구성·속성·근거·보류 | 파이프라인에서 생성·저장 |
| 원문 표현·승인 개념 연결 | 사전에서 저장·판정·조회; 업무 정의는 게시 Ontology 참조 |
| `DocumentGoodsGraph` 작성 계약 | [대표 예시](../../../backend/authoring/specification_examples/four_sample_graphs.yaml)의 구조·참조 검사 가능 |
| 소유 대상·scope 해석 제안 | 원래 문서 결과와 Draft/게시 작성 버전을 고정하고 별도 검토 산출물에 차이·근거 보관; 승인·적용은 수행하지 않음 |
| goods Draft의 전체 인스턴스 적재·게시·Runtime 조회 | 후속 작업 |

2.0.0 작성안은 새 pending manifest의 `draft_objects`로 추가/제거 의미를 별도 분류한다.
[이관 분류](../../../backend/authoring/ontology_migrations/pending/2026_11_goods_native_meaning/ontology_v2.yaml)는
실행 Registry의 legacy Object가 0개인 사실과 Draft 변경 4개를 구분한다. 과거 `goods.server` 등과의
Stable Concept ID 재사용·동등성은 자동 승인하지 않는다. 기존 Ontology가 있는 환경에서 bootstrap을
다시 실행해 내용을 덮어쓰지 않는다. 인증된 작성 API의 `blueprint-preview`에서 변경·차단 사유를
확인하고, 계획 checksum을 고정해 `blueprint-drafts`로 별도 Draft를 준비한다.
게시 기반이 없는 기존 Draft에서도 준비할 수 있으며 원본은 보존한다. 공통 Stable Concept ID는
유지하되 과거 버전에서만 존재하는 key 재사용·소유 대상 변경·승인 Binding 제거는 차단한다.
미게시 원본은 감사 이력에 기록하고 게시 기반인 것처럼 `based_on_version_id`에 넣지 않는다.
이 경로는 의미 승인·게시를 수행하지 않는다. 새 작성안을 적용하려고 이전 Draft를 먼저 게시해서는 안 된다.

단위 검증과 실제 Worker 실행은 구분한다.
현재 검증은 전체 정확도나 새 물품 검색·비교의 완성을 뜻하지 않는다.

## 설계 참고

[Palantir 설계 지침](https://www.palantir.com/docs/foundry/ontology/ontology-best-practices/),
[W3C 다항 관계](https://www.w3.org/TR/swbp-n-aryRelations/),
[SKOS](https://www.w3.org/TR/skos-reference/), [QUDT](https://www.qudt.org/pages/QUDToverviewPage.html)를 참고했다.
물품을 중심으로 탐색하되 수량·조건·근거가 있는 관계는 별도로 표현하고 실제 업무 질문으로 검증한다.
