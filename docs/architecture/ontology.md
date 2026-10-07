# Ontology and semantic binding

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
포함하며 이전 Published artifact는 신규 배포에 사용하지 않는다.

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
`manifest.json`, 내장 `.release.json`, `bundle.json`과 각 구성요소 checksum을
대조한 뒤에만 bundle을 적재한다.
Artifact store의 `active.json` 교체는 atomic rename으로 수행하며 rollback은
검증된 이전 version을 다시 activate하는 방식으로 처리한다.

적용 완료된 Ontology migration manifest는 `platform/ontology_migrations/applied/`에
불변 이력으로 보관한다. Object를
추가하거나 제거하면 `ontology_v2.yaml` 분류도 갱신하고 다음을 실행한다.

```bash
uv run --locked --package teoria-platform teoria ontology-migration-report
uv run --locked --package teoria-platform pytest platform/tests
```

과거 `company`와 `procurement` Ontology를 통합한 상세 이전 과정, 특정 날짜의
profiling 수치와 제거된 호환 명칭은 현재 계약이 아니다. 필요한 사실은 Git
이력과 migration manifest에서 확인한다.
