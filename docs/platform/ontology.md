# Ontology와 Semantic Binding

Ontology는 여러 문서·시스템에서 유지할 **업무 개념·속성·관계의 의미**를 정의한다.
Semantic Binding은 그 개념을 외부 자산·용어·기능에 연결한다.

## 모델 경계

| 구분 | 역할 |
|---|---|
| Business Ontology | 업무 Object·Property·Relationship 정의 |
| Semantic Binding | Stable Concept와 용어·자산·API·Capability의 의미 연결 |
| Runtime Mapping | 원본 레코드를 실행 Object·Link로 변환 |
| Capability | 조회·계산·판단·실행 능력과 입출력·정책 계약 |
| Runtime artifact | 호환성을 검증한 게시 의미·Binding·Registry의 고정 묶음 |

API 응답·화면 projection·일회성 평가 결과를 그대로 Business Object로 만들지 않는다.
CapabilityVersion의 필수 의미는 게시 artifact의 Stable Concept에서 해석하며,
Lifecycle 상태와 특정 artifact에 대한 호환성 판정은 구분한다.

## 식별자와 version

- Stable Concept ID는 version이 달라져도 유지하는 의미 식별자다.
- revision ID는 특정 version의 편집 단위다.
- Published version은 직접 수정하지 않는다. 변경은 새 Draft에서 한다.
- Ontology의 순서는 `draft → in_review → approved → published → deprecated`다.
- Binding은 초안·승인/거절·중단 상태와 판정 이력을 보존한다.

Admin 쓰기의 actor는 인증 principal에서 가져온다. 본문 문자열을 승인 주체로 신뢰하지 않는다.
AI 결과는 제안이며, 승인·적용 성공 전 authoritative metadata를 변경하지 않는다.

## Semantic path

```text
데이터 자산 → OpenMetadata Glossary Term → Teoria Ontology 개념
Capability / API Field ─────────────────→ Teoria Ontology 개념
```

자산 직접 Binding도 허용하지만 Glossary Term 연결보다 우선하지 않는다.
OpenMetadata는 system·entity ID·type·FQN·필요한 version의 MetadataTargetRef로 참조한다.
entity 본문을 복제하지 않는다. API Field Binding은 활성 Source 계약의 Operation·원본 필드를 검증한 경우만 승인한다.

## 물품 모델

물품의 의미 경계는 `goods`다. 분류번호나 서버·메모리별로 namespace를 나누지 않는다.
물품 유형, 구성 역할, 분류 계층, 원문 값·조건·근거는 구분한다.

| 문서 | 내용 |
|---|---|
| [물품 모델](../domains/goods/model.md) | 문서·물품·구성·속성·분류·서비스·근거 |
| [사전](../domains/goods/expression_links.md) | 원문 표현·근거·게시 개념의 승인 연결 |
| [프로파일](../domains/goods/specifications/normalization_profiles.md) | 게시 의미를 문서에 적용하는 고정 규칙 |

현재 [goods 작성 입력](../../backend/authoring/ontology_blueprints/goods.yaml)은 2.0.0 Draft다.
`server`·`memory_module`의 업무 속성을 native Property로 정의하고, 문서별 항목·속성 명세에는
게시 개념 참조를 둔다. 기존 `item_type`·`characteristic_definition`을 별도 정의 원장으로 사용하지 않는다.
일반 추출 그래프와 사전의 승인 기록을 이 Draft의 게시·전체 인스턴스 적재로 표시하지 않는다.
실제 관찰 본문은 파일/S3, 실행·참조는 Data DB, 의미 정의·승인은 Application DB가 맡는다.

## Authoring과 Runtime

게시 정의의 읽기 계약은 `GET /v1/admin/ontology-authoring/versions/{version_id}/publication`이다.
Admin 인증을 요구하며 현재 `published` 상태의 실제 artifact만 `{ontology, content}`로 반환한다.
`ontology`에는 version_id·namespace·version·checksum이 있고 본문의 identity·checksum도 검증한다.
미게시·deprecated version은 이 조회에서 허용하지 않는다. 과거 고정 Runtime bundle의 재현·복구는
기존 artifact 적재 경로를 사용한다. 사전의 등록·표현 연결 없이 게시 정의를 조회할 수 있다.

`publication_contracts.py`는 Source와 무관한 게시 참조·본문·개념 owner/관계 endpoint 검증을
소유한다. 문서 처리는 entity/attribute/relation이라는 추출 용어로만 projection을 변환한다.
사전 snapshot에 담긴 게시 본문은 호환 실행 복사본이며 새로운 정의 원장이 아니다.
checksum 검증만으로 승인 권위가 생기지 않으므로 Admin 조회 또는 검증된 Runtime bundle의
publication provenance를 함께 확인한다.

작성 DB 모델을 Runtime contract로 직접 사용하지 않는다.
Runtime bundle은 Published Ontology·승인 Binding·Registry release 등을 고정하고 checksum을 검증한다.
운영 Runtime은 bundle을 적재하며 원본 Registry나 작성 DB를 직접 읽지 않는다.
복구는 검증된 이전 artifact를 다시 활성화한다. 자세한 절차는 [Runtime](runtime.md)을 따른다.

## Ontology 변경과 이관

1. Published version에서 새 Draft를 만든다.
2. 의미가 같은 Stable Concept는 유지하고 변경 내용을 검토한다.
3. 구조·Binding 호환성·artifact compile을 검증하고 승인·게시한다.
4. 새 Runtime bundle을 생성·검증한 뒤 적용한다.

기존 YAML Object를 추가·제거하는 이관은 pending manifest를 작성하고 명시적인 manifest로
`teoria ontology-migration-report`를 실행한다. applied 이력과 게시 artifact는 수정하지 않는다.
작성안만 변경하는 경우 `draft_objects`에 추가·제거 분류와 근거를 기록한다. 보고서의 이 목록은
Runtime Object 이관 건수·게시 대상 검증과 별도로 표시하며 의미 승인이나 적용 완료를 뜻하지 않는다.
코드 위치는 [저장소 구조](../architecture/repository-structure.md), 사용 화면은 [Admin UI](admin_ui.md)를 참고한다.

### Blueprint에서 별도 Draft 준비

기존 Draft를 보존하며 새 작성 입력을 반영할 때는 `ontology_owner` 권한의 인증된 Admin API를 사용한다.
일반 `create_draft`의 게시 기반 정책과 별도이며 기존 Draft를 먼저 게시할 필요가 없다.

1. `POST /v1/admin/ontology-authoring/versions/{id}/blueprint-preview`에 `blueprint`를 보낸다.
2. 추가·제거·수정, 유지하는 Stable Concept 수, 차단 사유를 검토한다.
3. `POST /v1/admin/ontology-authoring/versions/{id}/blueprint-drafts`에 같은 `blueprint`,
   `expected_plan_checksum`, `rationale`을 보낸다.

적용은 ontology 잠금과 단일 transaction 안에서 계획을 재확인하고 구조 검증에 실패하면 롤백한다.
원본 변경 후 오래된 계획은 거절한다. 같은 주체의 동일 요청은 변경되지 않은 준비 Draft만 재사용한다.
감사에는 인증된 주체·원본 checksum·작성 입력·계획·결과 checksum을 기록한다.
원본이 미게시이면 감사 provenance만 남기고, 게시 원본이면 새 Draft의 정상 게시 기반으로 기록한다.
규칙·지표가 있는 원본, 과거 key 재사용, 개념 종류·소유 대상·관계 endpoint 변경,
승인 Binding 대상 제거는 자동 준비에서 차단하고 별도 검토한다.

## 연결·적용 규칙 변경 영향

`GET /v1/admin/ontology-authoring/versions/{version_id}/binding-impact`는 물품 작성 기능이 연결된
Admin 구성에서 `dependency_impact`를 함께 제공한다. 기준 버전과 Draft를 Stable Concept ID로
비교해 정의·소유 대상·자료형·cardinality·단위 정책·관계·규칙의 변경/제거를 찾는다.
관련 문서 프로파일·사전 표현 연결·의미를 선언한 API Mapping·승인 Semantic Binding의
재검토 목록을 버전 검토 화면에 표시한다. 작성 기능별 공개 조회 경계로 읽고 기록을 수정하지 않는다.

개념이 같아도 고정 게시 버전을 전환할 때는 재검토한다. 기존 고정 산출물·연결·결과는 보존하며
이 조회 자체로 승인·게시·자동 재매핑하지 않는다. 기존의 제거된 승인 Binding 검사와 별도인
추가 영향 보고서다. 새 bundle의 의미 검증과 프로파일 승인 검사는 계속 적용한다.
