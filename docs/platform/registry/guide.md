# Registry guide

Registry는 Platform Runtime이 검증하고 실행하는 선언형 계약이다. Business
Ontology authoring과 Pipeline orchestration을 담지 않는다.

## 구성

| Registry | 역할 |
|---|---|
| Core | Data Type과 Value Set |
| Domain | Runtime Object, Link, Mapping, Capability |
| Source | Runtime이 직접 호출하는 API 또는 Database relation |

ID는 `snake_case`, 참조는 namespace를 포함한 완전한 ID를 사용한다. 외부
Provider의 wire field와 code는 원문 표기를 유지한다. 변경 가능한 상태를 모두
별도 Object로 만들지 않고, 업무상 독립된 이력일 때만 observation/event 객체로
모델링한다.

## Source와 Connector 선택

- Capability가 요청 시 직접 호출하는 API는 `backend/contracts/runtime/sources/`에 둔다.
- `capability.exposure: public`인 계약만 Runtime discovery와 MCP Tool에 노출한다.
  다른 Capability가 조합 실행에 사용하는 지원 계약은 `internal`로 유지한다.
- Prefect만 지속 수집하는 API는 `backend/contracts/ingestion/connectors/`에 둔다.
- 수집 DB를 Runtime이 읽으면 Database Source와 DB-to-Ontology Mapping을 만든다.
- 같은 API를 Source와 Connector 양쪽에 등록하지 않는다.

Source의 세부 작성 절차와 verification case 규칙은
[Source authoring](source_authoring.md)을 따른다.

## Runtime 계약

`domains/<domain>/`은 업무 소유권을 나타내며 독립 배포 경계가 아니다.
Runtime 계약 namespace는 YAML의 `runtime_contract.id`로 식별한다. 하나의
업무 Domain이 여러 Runtime 계약을 소유할 수 있다.

아래 트리는 `backend/contracts/runtime/` 기준이다.

```text
domains/
├── company/
│   ├── runtime_contracts/company.yaml
│   ├── capabilities/
│   └── mappings/
└── public_procurement/
    ├── runtime_contracts/public_procurement.yaml
    ├── capabilities/
    └── mappings/
```

파일명은 계약 ID와 일치해야 하며 소유 Domain 폴더명과 계약 ID를 같게 만들
필요는 없다. 로더는 이전에 발행한
`domains/<namespace>/runtime_contract.yaml` 구조도 읽지만 새 계약은 소유 Domain의
`runtime_contracts/<contract_id>.yaml`에 작성한다. 중복 계약 ID는 위치와 무관하게
거부한다.

Object Type은 identity property와
업무 property를, Link Type은 source와 target을, Mapping은 Source record 변환을,
Capability는 검증된 입력·출력과 실행 조합을 정의한다.

Registry checksum에는 파일 경로도 포함되므로 위치만 바꿔도 checksum이 달라진다.
새 구조를 운영에 사용하려면 새 Registry release와 검증된 Runtime bundle을 만든다.
기존 Published release·artifact 경로와 내용은 직접 수정하지 않는다.

Breaking change는 새 Registry version으로 발행한다. Runtime은 검증된 immutable
bundle과 checksum을 사용하며 Git 작업 파일을 운영 중에 임의로 읽어 바꾸지 않는다.

원본 `backend/contracts/runtime/`는 사람이 작성하는 draft 계약만 보관하며 release 상태나
`.release.json`을 저장하지 않는다. 발행 명령은 커밋된 원본을 변경하지 않고 지정한
Artifact Store에 version 디렉터리와 `manifest.json`을 생성한다.

```bash
uv run --locked --project backend --extra api teoria publish \
  backend/contracts/runtime \
  --version YYYY.MM.DD.REVISION \
  --output /path/to/registry_artifacts \
  --git-commit "$(git rev-parse HEAD)"
```

따라서 Registry 변경은 한 번만 커밋한다. 생성된 manifest와 Runtime bundle은 Git이
아니라 Artifact Store가 보관하고, 운영 전환은 검증된 bundle의 `active.json`을
원자적으로 교체한다.

## 검증

```bash
uv run --locked --project backend --all-extras --all-groups pytest backend/tests
uv run --locked --project backend --extra api teoria validate backend/contracts/runtime

uv run --locked --project backend --all-extras --all-groups pytest backend/tests
uv run --locked --project backend teoria-pipelines validate backend
uv run --locked --project backend --extra api \
  teoria-pipelines validate-integration backend \
  --platform-registries backend/contracts/runtime
```

검증기는 schema, 참조, Mapping 타입, Capability graph, Source request/response와
Database Source relation을 확인한다. Provider 계약 변경은 정적 검증 외에 모든
Operation의 Build 검증을 수행하고 credential이 있으면 Live 검증도 수행한다.

## 세부 작성 안내

- [Capability](capabilities.md): 입력, 실행 단계와 결과 계약
- [Mapping](mappings.md): Source 필드 변환과 객체 materialization
- [Source 작성과 검증](source_authoring.md): 원문 대조와 Operation별 Build·Live 입력
