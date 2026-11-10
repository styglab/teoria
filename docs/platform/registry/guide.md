# Runtime Registry

Registry는 Runtime이 검증·실행하는 선언형 계약이다. Business Ontology 작성과 Prefect 수집 계약은 별도다.

| 구성 | 책임 |
|---|---|
| Core | Data Type·Value Set |
| Domain | Runtime Object·Link·Mapping·Capability |
| Source | Runtime이 직접 호출하는 API·Database relation |

ID는 `snake_case`, 참조는 namespace를 포함한 완전한 ID다. Provider wire 이름·코드는 원문 그대로 둔다.
Runtime API는 `backend/contracts/runtime/sources/`, Pipeline 전용 API는
`backend/contracts/ingestion/connectors/`에 둔다. 같은 API를 양쪽에 등록하지 않는다.
수집 DB를 Runtime이 조회하면 Database Source와 DB Mapping이 필요하다.

## 계약 배치

`backend/contracts/runtime/domains/<domain>/runtime_contracts/<contract_id>.yaml`에 작성한다.
업무 도메인과 실행 계약 namespace는 같을 필요가 없다. 하나의 도메인이 여러 계약을 소유할 수 있다.
로더는 기존 `runtime_contract.yaml`도 읽지만 신규 계약은 위 규칙을 따른다. 중복 ID는 거부한다.
Object는 identity·property, Link는 양 끝 객체, Mapping은 값 변환, Capability는 실행 조합을 정의한다.

## Mapping

Mapping은 `Source record → Runtime Object` 변환이다. `Concept ↔ 용어·자산·API`의
[Semantic Binding](../ontology.md)과 구분한다. YAML의 기존 `ontology` 필드는 실행 계약 namespace다.

| 참조 | 형식 |
|---|---|
| API 필드 | `<source>.<operation>.request|response.<path>` |
| DB 필드 | `<source>.<relation>.<field>` |
| Runtime 대상 | `<object_type>.<property>` |

Property 아래 여러 항목은 독립 binding이다. 여러 필드를 함께 변환할 때만 이름 있는 객체로 묶는다.
`decode`는 응답→Property, `encode`는 입력→요청 변환이며 `role`은 같은 Object Type의 역할을 구분한다.
Codec 구현은 `platform/ontology/contracts/codecs/`에 둔다. 외부 codec ID는 게시 artifact 호환을 유지한다.
`materializations`가 객체 identity·Link를 만들며 생성 ID·고정값·수집시각을 binding에 섞지 않는다.

### 게시 의미 연결

선택적 `bindings.<target>[].meaning`에 아래 내용을 명시한다.

```yaml
meaning:
  ontology:
    version_id: 게시_버전_UUID
    namespace: goods
    version: '1'
    checksum: 게시_artifact_SHA256
  concept_id: 속성_Stable_Concept_UUID
  api_field_binding_id: 승인된_API_Field_Binding_UUID
  information_kind: declared_value
  scope: per_component
  unit:
    source_unit: TB
    canonical_unit: GB
    multiplier: '1000'
  operator: eq
  effective_at_field: effective_at
```

형태 설명용 예이며 실제 Source·UUID가 아니다. Provider 문서로 필드·단위를 검증한 뒤 승인 연결을 작성한다.
bundle 생성·적재 시 게시 버전·checksum·Stable Concept, 승인 Binding의 대상·버전·유효기간·주체,
타입·scalar cardinality·허용 단위·정보 성격·범위의 일치를 검사한다.
`represents`·`equivalent`만 지원하며 조건부·관련성 연결은 자동 적용하지 않는다.
현재 의미 경로는 scalar 숫자·텍스트와 단일 응답 필드만 지원한다. 임의 codec·qualifier·요청 필드에
의미 승인을 추정하지 않는다. 개발용 원본 Registry에는 검증된 의미 plan이 없으므로 이 경로를 실행하지 않는다.

요구조건·제조사 명시값·측정값은 검토한 의미 연결로 구분한다. 실제 측정 시각과 조회 시각도 구분한다.
결과의 `semantic_observations`에 정규값·원래 값/단위·개념·Source·Binding·Mapping·시점을 보존한다.
충돌은 관찰을 함께 유지하고 `semantic_conflicts`로 보류한다. 마지막 응답으로 덮어쓰지 않는다.
합성 검증은 `backend/tests/integration/test_document_api_meanings.py`이며 실제 API Live 품질 승인은 아니다.

## Capability

Capability는 입력·실행 단계·반환 Object/Link를 선언한다.
입력 `property`·`returns`는 `<runtime_contract>.<object_type>.<property>` 또는 객체/Link ID,
단계의 `call`은 `<source>.<operation>`을 참조한다. `steps` 순서로 실행한다.
입력→요청은 Mapping request binding과 encode, 응답→객체는 response binding과 decode를 사용한다.
전용 입력은 `data_type + field`로 직접 연결할 수 있다.

`kind`는 `query`·`compute`·`action`이다. `effects.reads/produces`는 조회·계산,
`effects.creates/updates`는 업무 변경을 선언한다. 기존 조회 계약의 기본 종류는 query다.
`exposure: public`만 discovery와 MCP Tool에 노출하며 조합용 계약은 internal로 유지한다.
MCP Tool 이름은 Capability ID다. Runtime은 timeout·retry·deadline·페이지 상한을 적용하고
identity로 병합한 객체·Link·provenance를 반환한다. 원본 응답은 명시적 진단에서만 포함한다.

고정 artifact의 읽기 전용 조회는 `kind: query`와 명시적으로 주입한 `processor`를 사용할 수 있다.
이 경우 `steps`와 함께 선언하지 않는다. Python import 경로를 Registry에서 실행하지 않으며
등록된 handler·입력·반환 타입·권한·deadline을 검증한다. 외부 HTTP·DB 조회는 기존 Source·Mapping 계약을 사용하고,
processor로 그 계약을 우회하지 않는다. 첫 사용은 [문서 요구조건 조회](../runtime.md#문서-요구조건의-게시-의미-조회)다.

## 검증·게시

```bash
uv run --locked --project backend --extra api teoria validate backend/contracts/runtime
```

검증기는 schema·참조·타입·Mapping·실행 graph·Source·DB relation을 검사한다.
Provider 계약은 [Source 작성 절차](source_authoring.md)의 Operation별 Build 검증과 credential이 있으면 Live 검증까지 수행한다.
전체 검사는 [개발 안내](../../development.md)를 따른다.
발행·bundle·전환·복구는 [Runtime](../runtime.md)에 한 번만 정의한다.
경로도 checksum에 포함되므로 위치 변경에도 새 release가 필요하다. 이미 게시한 artifact는 수정하지 않는다.
