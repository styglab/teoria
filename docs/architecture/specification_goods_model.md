# 규격서의 물품·구성품·분류·속성 모델

목표는 **어떤 물품이 무엇으로 구성되고, 어떤 특성과 조건을 요구하며, 근거가 어디에 있는지** 표현하는 것이다.
검색·비교·변경 확인은 이 구조를 사용하는 기능이다.
현재 작성 입력은 [goods.yaml](../../backend/authoring/ontology_blueprints/goods.yaml)의 goods Draft다.
현재 추출 JSON이 이 Draft의 전체 객체로 자동 적재·게시되는 것은 아니다.

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
| `item_type` | 물품 유형의 공통 정의 |
| `characteristic_definition` | 특성의 뜻·값 종류·차원·단위 정책 |
| `classification_scheme` | 분류체계와 판본 |
| `classification_entry` | 해당 판본의 분류 항목 |
| `classification_assignment` | 대상에 대한 출처별 분류 주장·검증 상태 |
| `specified_service` | 설치·설정·시험 등 작업 항목 |
| `supply_scope` | 문서가 정한 납품 범위 |
| `supply_membership` | 대상이 납품 범위에서 맡는 역할 |
| `specified_context` | 적용 장소·시험 대상·참조 조건 등 문맥 |
| `specified_deliverable` | 지침서·성적서 등 납품 자료 |
| `item_relation_statement` | 데이터 전송·호환·고정·연계 등 대상 간 관계 |

객체의 고정 필드는 Ontology Property로 정의한다. 물품별 다양한 특성의 공통 정의는 사전 항목으로 관리한다.
사전 항목 ID와 Ontology schema의 Stable Concept ID는 서로 다르다.

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
[물품 사전](../platform/goods_dictionary.md)에서 저장 내용·승인·재사용 범위를 확인한다.
Published 개념을 문서에 적용하는 규칙은 [정규화 프로파일](../procurement_specification_processing/normalization_profiles.md)이 맡는다.

## 현재 구현과 설계의 경계

| 구현 | 상태 |
|---|---|
| 일반 추출 그래프·구성·속성·근거·보류 | 파이프라인에서 생성·저장 |
| 원문 사전·표준 정의·승인 매핑 | 별도 저장·개정·조회 구현 |
| `DocumentGoodsGraph` 작성 계약 | [대표 예시](../../backend/authoring/specification_examples/four_sample_graphs.yaml)의 구조·참조 검사 가능 |
| goods Draft의 전체 인스턴스 적재·게시·Runtime 조회 | 후속 작업 |

[네 문서 평가](../../archive/documentation/verification/goods_relation_repair_2026_10_28.md)와
[운영 Worker 확인](../../archive/documentation/verification/goods_relation_deployment_2026_10_28.md)을 구분해 읽는다.
현재 검증은 전체 정확도나 새 물품 검색·비교의 완성을 뜻하지 않는다.

## 설계 참고

[Palantir 설계 지침](https://www.palantir.com/docs/foundry/ontology/ontology-best-practices/),
[W3C 다항 관계](https://www.w3.org/TR/swbp-n-aryRelations/),
[SKOS](https://www.w3.org/TR/skos-reference/), [QUDT](https://www.qudt.org/pages/QUDToverviewPage.html)를 참고했다.
물품을 중심으로 탐색하되 수량·조건·근거가 있는 관계는 별도로 표현하고 실제 업무 질문으로 검증한다.
이전 대안·샘플별 분석은 [설계 기록](../../archive/documentation/architecture/specification_goods_model_2026_10_27.md)에 보존했다.
