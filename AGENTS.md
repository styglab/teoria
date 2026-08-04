# Teoria repository instructions

## Project boundary

변경 전에 [Repository Structure](docs/architecture/repository-structure.md)를 읽고 소유 프로젝트를 결정한다.

- 의미 정의, Semantic Registry, 사용자 요청 실행과 Runtime은 `platform/`에 둔다.
- 지속 수집, Connector, Prefect, 정규화, 적재와 Data DB migration은 `pipelines/`에 둔다.
- MCP protocol과 Runtime HTTP client는 `mcp/`에 둔다.
- MCP는 목표 운영 구조에서 Runtime API만 호출한다. 현재 embedded mode는 Runtime API 구현 전까지의 호환 경로다.
- Pipeline 실행 코드에서 Platform의 Capability 또는 Mapping Runtime을 직접 호출하지 않는다.
- Provider API wire 계약, 요청 생성, 응답 검증과 HTTP 실행만 `packages/provider/`의 `teoria-provider`를 사용한다.
- 프로젝트 사이에 일반적인 `common`, `shared`, `utils` 패키지를 만들지 않는다.

## Provider contract work

Source Registry를 생성하거나 수정하기 전에 `docs/registry/source-authoring.md`를 끝까지 읽고 그 절차와 체크리스트를 따른다.

- Semantic Runtime이 직접 호출하는 API만 `platform/registries/sources/`에 둔다.
- Prefect 등 Pipeline Worker만 호출하는 API는 `pipelines/connectors/`에 두고 `docs/ingestion/connectors.md`를 따른다.
- 수집·정규화된 DB를 Runtime이 직접 조회하면 `platform/registries/sources/`에 Database Source와 DB-to-Ontology Mapping을 만든다.

Provider Reference 문서에서 신규 Source와 verification case를 생성·검증하거나 기존 Source를 원문 대조할 때는 저장소 Skill `$author-source-registry`를 사용한다. 사용법은 `docs/skills/source-registry-author.md`에 있다.

- 새 Source는 `docs/registry/templates/source.yaml`을 복사해 시작한다.
- Source 필드와 요청 파라미터 ID는 제공기관의 원본 표기를 보존한다.
- Teoria가 정의하는 Source, Object, Operation ID는 `snake_case`를 사용한다.
- 문서에 없는 의미를 추측하여 필드, 타입, 필수 여부나 코드를 만들지 않는다.
- 실제 API 키, 개인정보, 비공개 요청·응답은 Registry, Reference, 테스트와 로그에 기록하지 않는다.
- 인증정보는 역할에 따라 `TEORIA_SOURCE_<SOURCE_ID>_API_KEY` 또는 `TEORIA_CONNECTOR_<CONNECTOR_ID>_API_KEY` 환경변수 이름으로만 참조한다.
- Source Registry, Provider Reference metadata와 Operation별 verification case를 함께 관리한다.
- 대응 계약이 아직 없으면 Reference `metadata.yaml`에 `status: draft`를 사용하고, 계약을 추가하는 변경에서 `status: active`로 승격한다.

Source 관련 변경 후 다음 명령을 실행한다.

```bash
uv run --locked --package teoria-platform pytest platform/tests
uv run --locked --package teoria-platform teoria validate platform/registries
```

Connector 관련 변경 후 다음 명령을 실행한다.

```bash
uv run --locked --package teoria-pipelines pytest pipelines/tests
uv run --locked --package teoria-pipelines \
  teoria-pipelines validate pipelines
uv run --locked --package teoria-pipelines --group validation \
  teoria-pipelines validate-integration pipelines \
  --platform-registries platform/registries
```

모든 Connector Operation에 대해 `teoria-pipelines verify connector --profile build`를 실행하고 credential이 있으면 Live까지 실행한다. 실제 API 호출에는 안전한 검증 데이터만 사용하고 출력과 보관 파일에 인증정보나 민감한 입력값이 포함되지 않았는지 확인한다.

Prefect Flow 또는 Data DB migration을 변경하면 Pipeline 단위 테스트에 더해 다음을 검증한다.

```bash
docker compose \
  -f deploy/compose.yaml \
  config --quiet
```

- Flow의 주요 단계는 Prefect Task로 표현해 UI에서 실행 순서와 실패 지점을 식별할 수 있어야 한다.
- 원본 응답 저장과 정규 적재가 모두 성공한 뒤에만 Checkpoint를 갱신한다.
- migration은 새 순번 파일로 추가하고 이미 적용된 SQL을 변경하지 않는다.

MCP 변경 후 다음 명령을 실행한다.

```bash
uv run --locked --package teoria-mcp pytest mcp/tests
```
