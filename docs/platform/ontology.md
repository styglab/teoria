# Ontology와 Semantic Binding

Business Ontology에는 여러 시스템과 시간에 걸쳐 유지되는 업무 의미만 둔다.
API 응답, Capability 출력, 화면 projection과 평가 결과는 Runtime 계약이지
Business Object가 아니다.

Teoria의 실행 의미는 네 경계로 분리한다.

- Ontology는 Object, Property와 Relationship으로 업무 세계를 정의한다.
- Capability는 Ontology를 이용하는 query, compute, decision, action 능력이다.
- CapabilityVersion은 semantic requirement, 입출력, 구현과 정책을 고정한 불변 계약이다.
- Runtime Artifact는 호환성이 검증된 Ontology, Binding, Registry와 CapabilityVersion
  집합을 checksum으로 고정한다.

CapabilityVersion은 Ontology revision 자체에 pin하지 않고 필요한 stable concept를
선언한다. Artifact compile은 이를 Published Ontology의 immutable concept ID로
해석하며 선언된 필수 요구사항을 해석할 수 없으면 publish를 차단한다. Lifecycle과
특정 Artifact에 대한 compatible/incompatible 판정은 서로 다른 상태로 관리한다.

기존 Published Ontology 변경은 현재 Published version에서 새 Draft를 생성해 수행한다.
업무 의미가 같은 stable concept는 승계하고, 화면 projection이나 Capability 응답은
Business Object로 추가하지 않는다. 검토·승인·게시된 새 version만 Runtime bundle에
포함하며 새 의미 계약을 사용하는 배포는 새 bundle을 사용한다. 이전 bundle은 복구를 위해 보존한다.

## 모델 경계

물품 Ontology의 게시 경계는 `goods`다. 물품분류마다 별도의 Ontology namespace를 만들지 않는다.
서버 등 물품 유형은 이 Ontology가 정의하는 업무 사전으로 연결하고, 분류번호별 추출 표현·단위·적용 범위는
승인 프로파일이 관리한다. 관리 주체나 검토·게시 주기를 독립시킬 근거가 있을 때 별도 Ontology를 검토한다.
현재 작성 입력은 `backend/authoring/ontology_blueprints/goods.yaml`이다.

| 개념 | 의미 |
|---|---|
| `goods.classification_scheme` | 물품 분류체계 판본 |
| `goods.classification_entry` | 대·중·소·세 분류와 세부품명 등 공식 분류항목 |
| `goods.classification_assignment` | 문서 물품에 대한 출처별 분류 주장과 검증 상태 |
| `goods.item_type` | 업무 물품 유형 정의 사전의 항목 |
| `goods.characteristic_definition` | 표준 특성 정의 사전의 항목 |
| `goods.specified_service` | 설정·설치·연동시험 등 서비스 항목 |
| `goods.supply_scope` | 문서별 물품·작업·자료의 납품 범위 |
| `goods.supply_membership` | 공급·기존·외부 제공·시험 대상 등 범위별 역할 |
| `goods.specified_context` | 공간·시험 대상·참고 모델 등 요구 적용 문맥 |
| `goods.specified_deliverable` | 제출이 요구되는 설명서·성적서·도면 등 자료 |
| `goods.item_relation_statement` | 설치·호환·데이터·전원 연결 요구 |
| `goods.specification_document` | 특정 원본 버전의 규격서 |
| `goods.specified_item` | 문서가 지시하는 물품·구성 대상 |
| `goods.property_statement` | 대상의 특성에 관한 원문 값·조건 명세 |
| `goods.composition_statement` | 대상 사이의 구성·수량·포함 조건 명세 |
| `goods.requirement_statement` | 속성 하나로 축약하기 어려운 의무·조건 |
| `goods.evidence` | 특정 문서 버전의 원문 구절·위치 근거 |

사용자의 초기화 요청으로 기존 `goods` 0.2.0과 `computer_server` 모델·후보·프로파일·Binding·관찰을
운영에서 삭제했다. 현재 `goods` 1.0.0은 객체 17개·속성 93개·관계 50개의 Draft이며 구조 검증을 통과했다.
새 모델의 게시·승인 프로파일·새 명세 계약에 따른 재추출은 아직 수행하지 않았다.
물품 유형과 구성품 역할, 문서 계층과 물리적 구성을 구분한다. 원문 값·조건·근거와 표준 의미를 혼용하지 않는다.
실제 인스턴스 본문은 Data DB/파일/S3에 두고 Application DB의 의미 정의·승인 이력과 분리한다.
삭제 범위와 새 Draft ID는
`backend/authoring/ontology_migrations/applied/2026_10_specification_goods_reset/receipt.yaml`에 기록했다.
기존 `teoria`의 Published version과 예전 namespace는 이력으로 보존한다.
분류 계층·물품 유형·구성 관계를 구분하며 서비스는 물리 구성품과 별도 연결한다.
분류 없이 검증하는 문서 그래프 계약과 네 샘플의 대표 작성 예시를 추가했다.
원문 명칭 사전의 저장·자동 승인·재사용 API를 추가했다. 유형 31개·특성 14개를 실제 저장했다.
현재 정책은 `source_literal_v1`이며 의미 동등성·동의어·단위 환산을 자동 승인하지 않는다.
새 모델의 자동 그래프 생성·Published 모델·Runtime 조회 연결은 후속 단계다.
추출 표준은 `pipeline_selected_draft`이고 Business Ontology 승인·게시와 별도다.

## 규격서 물품 모델의 발전 방향

목표는 규격서가 어떤 물품·구성품을 어떤 속성·조건·관계로 기술하는지 표현하는 것이다.
검색·표준화·검토·문서 변경 확인·비교·추천과 AI 질의는 이 모델의 활용이다.
기존 서버·메모리 조회 모델은 제거하고 규격서 물품 모델을 Draft에서 다시 작성했다.

공식 설계 지침과 제품 특성·근거 표준을 조사한
[규격서 물품 모델 설계안](../architecture/specification_goods_model.md)을 후속 검토 기준으로 사용한다.
이 설계안은 새 Published Object type의 확정 목록이 아니다.

- **표준 의미:** 물품 유형·속성·관계의 지속 가능한 정의. 분류·속성·값·단위를 구분한다.
- **문서별 명세:** 해당 문서가 지시하는 대상, 구성 명세, 속성·조건 명세와 원문 근거.
- **해석과 승인:** 원문 언급이 어떤 표준 의미로 해석됐는지에 대한 문맥별 매핑·검토 이력.

물품과 구성품은 문맥상 역할을 구분한다. 같은 메모리도 단독 구매 물품 또는 서버의 구성품이 될 수 있다.
규격서 내 항목을 제조사 제품 모델이나 실물 자산으로 동일시하지 않는다.
문서 계층·물품 구성·분류 상하위는 다른 관계다. 수량·필수 여부·적용 조건·근거를 가진 구성 관계는
별도 구성 명세로 표현할 수 있어야 한다.

native Property는 객체의 고정 필드를 정의한다. 물품별 특성 사전은 `characteristic_definition`으로
업무 정의·값 종류·단위 정책을 표현하고 문서의 속성 명세가 관계로 참조한다.
수치 외에도 문자열·범위·집합·선택 조건, 반복·상충 진술, 보류 상태를 보존한다.
규격서·명세에 지속적인 업무 식별과 검토 대상의 의미가 있다면 객체 타입으로 검토할 수 있지만,
추출 JSON이나 일회성 Capability 응답을 그대로 Business Object로 게시하지 않는다.
저장 위치와 객체의 업무 의미는 별개이며 Runtime Mapping이 승인 의미와 실제 데이터를 연결한다.

AI는 검증 가능한 조회·탐색 기능과 인증된 검토·교정 기능을 사용한다.
개념 동등성·물리적 구성·제품 충족을 이름이나 유사도만으로 확정하지 않는다.
현재 의미 모델과 산출물은 유지하며 후속 구조 변경은 검토·승인·게시와 명시적 이관을 따른다.

## Semantic path

기본 연결은 다음 순서다.

```text
Physical Asset → OpenMetadata Glossary Term → Stable Ontology Concept
Capability ────────────────────────────────→ Stable Ontology Concept
API Field ─────────────────────────────────→ Stable Ontology Concept
```

Data Asset 직접 Binding도 가능하지만 Glossary Term Binding보다 우선하지 않는다.
API Field Binding은 활성 Source Registry에서 Operation과 원본 필드가 검증된 경우만
승인한다.

## 식별자와 version

- Stable Concept ID는 version 간 의미 식별자다.
- revision ID는 특정 Ontology version의 편집 단위다.
- Published version은 불변이며 변경은 그 version에서 새 Draft를 생성한다.
- lifecycle은 `draft → in_review → approved → published → deprecated`다.
- publish 전에 구조 검증, Binding 호환성 검사와 deterministic artifact compile을
  통과해야 한다.
- Binding은 `draft → approved/rejected → deprecated` 상태와 불변 review 기록을 갖는다.

## Authoring과 Runtime

Authoring DB 모델을 Runtime contract로 직접 사용하지 않는다. Publish가 생성한
artifact는 stable concept, property와 relationship을 포함하며 checksum으로
식별한다. Runtime Registry의 Object/Link는 Capability 입출력 materialization
계약으로 계속 독립적으로 존재한다.

개발 환경은 빠른 authoring 검증을 위해 원본 Registry를 직접 읽을 수 있다.
운영 Runtime bundle은 Registry release, Published Ontology artifact와 compile
시점의 Approved Binding snapshot을 함께 고정한다. Loader는 version 디렉터리의
`manifest.json`, `bundle.json`과 각 구성요소 checksum을 대조한 뒤에만 bundle을
적재한다. 원본 Registry에는 release 파일을 쓰지 않으며 Artifact Store의
`manifest.json`이 Registry release provenance의 단일 권위다.
Artifact store의 `active.json` 교체는 atomic rename으로 수행하며 rollback은
검증된 이전 version을 다시 activate하는 방식으로 처리한다.

## Ontology 변경과 이관

Published version에서 새 Draft를 만들고 필요한 개념·속성·관계를 수정한다.
검토·승인·게시 후 [Runtime bundle](runtime.md)을 구성해 배포한다. Stable Concept ID를
의미 식별자로 유지하고 version별 revision ID를 Binding의 의미 식별자로 사용하지 않는다.

구형 YAML Object를 추가하거나 제거하는 이관에는
`backend/authoring/ontology_migrations/pending/<migration>/ontology_v2.yaml` 분류를 함께 작성한다.
이관 묶음 이름은 `YYYY_MM_<purpose>`를 사용한다. manifest를 명시해 보고서를 실행한다.

```bash
uv run --locked --project backend --extra api teoria ontology-migration-report \
  --manifest backend/authoring/ontology_migrations/pending/2026_10_goods_focus/ontology_v2.yaml
uv run --locked --project backend --all-extras --all-groups pytest backend/tests
```

위 경로는 현재 보관된 분류 manifest의 예다. 새 변경에는 그 변경의 manifest를 지정한다.
적용 후 대상 Ontology version과 artifact checksum을 기록하고 묶음을 `applied/`로 옮긴다.
`applied/`는 이미 검토·게시된 입력과 결정 기록이므로 수정하거나 현재 구성처럼 재실행하지 않는다.
현재 권위는 Application DB에서 게시한 Ontology와 immutable artifact다.

초기 통합은 `applied/2026_10_initial_unification/`, 공고 문맥과 Stable Key 교정은
`applied/2026_10_bid_notice_context/`, `applied/2026_10_bid_notice_stable_key_correction/`에
보존되어 있다. 시점별 수치와 중간 입력은 이력으로 읽고 현재 계약으로 복제하지 않는다.

Ontology 작성 코드는 `backend/src/teoria/features/semantic_modeling/ontology/`, Binding은 `binding/`, 관리 API는
각 기능의 `admin_router.py`에서 찾는다.

현재 원문 등록 319개는 표준 개념 사전이 아니다. 원문 등록 ID는 source_term_ref로 연결하며 표준 개념 참조를 대체하지 않는다.

[물품 사전](goods_dictionary.md)의 표준 정의와 원문 매핑은 Application DB의 업무 의미 항목이다. 승인된 사전 개정도 Published Ontology schema 또는 Runtime artifact 게시를 대신하지 않는다.
