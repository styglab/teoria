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
| [물품 모델](../architecture/specification_goods_model.md) | 문서·물품·구성·속성·분류·서비스·근거 |
| [사전](goods_dictionary.md) | 원문 표현·표준 정의·승인 매핑 |
| [프로파일](../procurement_specification_processing/normalization_profiles.md) | 게시 의미를 문서에 적용하는 고정 규칙 |

현재 [goods 작성 입력](../../backend/authoring/ontology_blueprints/goods.yaml)은 Draft다.
일반 추출 그래프와 사전의 승인 기록을 이 Draft의 게시·전체 인스턴스 적재로 표시하지 않는다.
실제 관찰 본문은 파일/S3, 실행·참조는 Data DB, 의미 정의·승인은 Application DB가 맡는다.

## Authoring과 Runtime

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
코드 위치는 [저장소 구조](../architecture/repository-structure.md), 사용 화면은 [Admin UI](admin_ui.md)를 참고한다.
