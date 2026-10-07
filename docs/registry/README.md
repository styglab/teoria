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

- Capability가 요청 시 직접 호출하는 API는 `platform/registries/sources/`에 둔다.
- `capability.exposure: public`인 계약만 Runtime discovery와 MCP Tool에 노출한다.
  다른 Capability가 조합 실행에 사용하는 지원 계약은 `internal`로 유지한다.
- Prefect만 지속 수집하는 API는 `pipelines/connectors/`에 둔다.
- 수집 DB를 Runtime이 읽으면 Database Source와 DB-to-Ontology Mapping을 만든다.
- 같은 API를 Source와 Connector 양쪽에 등록하지 않는다.

Source의 세부 작성 절차와 verification case 규칙은
[Source authoring](source-authoring.md)을 따른다.

## Runtime 계약

Domain은 독립 배포 경계가 아니라 namespace다. Object Type은 identity property와
업무 property를, Link Type은 source와 target을, Mapping은 Source record 변환을,
Capability는 검증된 입력·출력과 실행 조합을 정의한다.

Breaking change는 새 Registry version으로 발행한다. Runtime은 검증된 immutable
bundle과 checksum을 사용하며 Git 작업 파일을 운영 중에 임의로 읽어 바꾸지 않는다.

## 검증

```bash
uv run --locked --package teoria-platform pytest platform/tests
uv run --locked --package teoria-platform teoria validate platform/registries

uv run --locked --package teoria-pipelines pytest pipelines/tests
uv run --locked --package teoria-pipelines teoria-pipelines validate pipelines
uv run --locked --package teoria-pipelines --group validation \
  teoria-pipelines validate-integration pipelines \
  --platform-registries platform/registries
```

검증기는 schema, 참조, Mapping 타입, Capability graph, Source request/response와
Database Source relation을 확인한다. Provider 계약 변경은 정적 검증 외에 모든
Operation의 Build 검증을 수행하고 credential이 있으면 Live 검증도 수행한다.
