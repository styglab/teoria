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

입찰체크 Ontology 변경은 현재 Published version에서 새 Draft를 생성해 수행한다.
업무 의미가 같은 stable concept는 승계하고, 화면 projection이나 Capability 응답은
Business Object로 추가하지 않는다. 검토·승인·게시된 새 version만 Runtime bundle에
포함하며 새 의미 계약을 사용하는 배포는 새 bundle을 사용한다. 이전 bundle은 복구를 위해 보존한다.

## 모델 경계

공공조달 모델은 하나의 shared ontology 안에서 다음 경계를 유지한다.

| 영역 | 대표 개념 |
|---|---|
| Identity | `LegalEntity`, `BusinessRegistration`, `Organization` |
| Procurement lifecycle | `ProcurementCase`, `BidNotice`, `BidOpening`, `Award`, `Contract` |
| Qualification | `Qualification`, `Industry`, `RegisteredIndustry`, `Sanction` |
| Observation | Source별 관찰, 식별 assertion, provenance |

동명이거나 이름이 비슷하다는 이유로 객체를 합치지 않는다. Provider가 제공한
식별자와 검증된 연결을 사용하고, 서로 다른 원천의 충돌은 값을 덮어쓰기보다
원 관찰과 authority policy를 보존한다. 계약 snapshot을 계약 사건이나 version
history로 오해하지 않는다.

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
`platform/ontology_migrations/pending/<migration>/ontology_v2.yaml` 분류를 함께 작성한다.
이관 묶음 이름은 `YYYY_MM_<purpose>`를 사용한다. manifest를 명시해 보고서를 실행한다.

```bash
uv run --locked --package teoria-platform teoria ontology-migration-report \
  --manifest platform/ontology_migrations/pending/2026_10_runtime_contract_classification/ontology_v2.yaml
uv run --locked --package teoria-platform pytest platform/tests
```

위 경로는 현재 보관된 분류 manifest의 예다. 새 변경에는 그 변경의 manifest를 지정한다.
적용 후 대상 Ontology version과 artifact checksum을 기록하고 묶음을 `applied/`로 옮긴다.
`applied/`는 이미 검토·게시된 입력과 결정 기록이므로 수정하거나 현재 구성처럼 재실행하지 않는다.
현재 권위는 Application DB에서 게시한 Ontology와 immutable artifact다.

초기 통합은 `applied/2026_10_initial_unification/`, 공고 문맥과 Stable Key 교정은
`applied/2026_10_bid_notice_context/`, `applied/2026_10_bid_notice_stable_key_correction/`에
보존되어 있다. 시점별 수치와 중간 입력은 이력으로 읽고 현재 계약으로 복제하지 않는다.

Ontology 작성 코드는 `platform/src/teoria/ontology/`, Binding은 `binding/`, 관리 API는
`admin/ontology_authoring_api.py`와 `admin/binding_api.py`에서 찾는다.
