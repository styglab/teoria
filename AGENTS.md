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

## Naming convention

저장소 내부에서 Teoria가 소유하는 파일, 디렉터리와 ID는 기본적으로
`snake_case`를 사용한다. 문서와 코드라는 이유로 규칙을 나누지 않는다.

- Python 클래스와 React 컴포넌트는 `PascalCase`를 사용한다.
- 환경변수는 `UPPER_SNAKE_CASE`를 사용한다.
- CLI 명령, Docker 서비스·이미지와 배포 리소스는 `kebab-case`를 사용한다.
- `Dockerfile`, `README.md`, `AGENTS.md`, `SKILL.md`, `pyproject.toml`,
  `package-lock.json`처럼 도구가 고정하거나 생태계 관례가 명확한 이름은 유지한다.
- 외부 Provider가 정의한 wire name, field와 code는 원본 표기를 유지한다.
- 기존 `docs/`의 `kebab-case` 경로는 링크 호환을 위해 일괄 변경하지 않는다.
  새 파일부터 `snake_case`를 적용하고 기존 파일은 별도 호환 계획 없이 이름만
  바꾸지 않는다.

## Metadata and knowledge authority

[AI-Native Metadata Platform](docs/architecture/ai-native-metadata-platform.md)의 책임 경계를 유지한다.
[Platform Guide](docs/platform-guide.md)와 [Product Roadmap](docs/roadmap.md)을 현재 구현과 동기화한다.

- Prefect는 Workflow와 Data Operations를 소유한다. Metadata 의미나 Ontology를 소유하지 않는다.
- OpenMetadata ingestion schedule과 retry도 Prefect가 소유한다. 기본 배포에 Airflow를 추가하지 않고 공식 ingestion image를 ephemeral Job으로 실행하며, 일반 Prefect Worker 이미지에 OpenMetadata ingestion dependency를 설치하지 않는다.
- OpenMetadata는 Technical Metadata와 Governance/Semantic Metadata의 authoritative source다. Data Asset, Schema, Description, Owner, Tag, Glossary, Domain, physical lineage, quality와 usage를 Teoria DB에 복제하지 않는다.
- Teoria Application DB는 Business Ontology, Semantic Binding, Metadata Intelligence의 Suggestion/Review/Application과 Context 설정만 소유한다.
- Business Ontology에는 지속 가능한 업무 의미만 둔다. API 응답, Capability 응답과 Runtime projection을 Business Object로 만들지 않는다.
- Runtime Mapping(`source record -> runtime object`)과 Semantic Binding(`ontology concept <-> term/asset/API/capability`)을 혼용하지 않는다.
- OpenMetadata 연결은 `MetadataTargetRef` 값 객체로만 표현한다. system, entity ID, entity type, FQN과 필요한 version 이외의 OpenMetadata entity 상태를 저장하지 않는다.
- 기본 semantic path는 `Physical Asset -> OpenMetadata Glossary Term -> Teoria Ontology`다. Direct Data Asset binding은 허용하지만 Glossary Term binding보다 우선하는 것으로 간주하지 않는다.
- Capability는 Business Ontology 및 OpenMetadata와 독립된 knowledge source다. Ontology와의 의미 연결은 `CapabilityTargetRef`를 사용하는 Semantic Binding으로 표현한다.
- API Field binding은 활성 Source Registry 계약에서 원본 필드와 Operation이 검증된 경우에만 승인한다. 이름 유사성으로 authoritative binding을 만들지 않는다.
- AI 결과는 Suggestion이며 authoritative metadata가 아니다. Review/Approval과 적용 성공 전에는 OpenMetadata나 published Ontology를 변경하지 않는다.
- Admin 쓰기 API는 인증된 principal을 변경 주체로 기록한다. 요청 body의 reviewer/actor 문자열을 권위 정보로 신뢰하지 않는다.
- Binding은 draft/review/approve 또는 reject/deprecate 생명주기를 거치며 승인 기록을 보존한다.
- Ontology Binding은 version별 revision ID가 아니라 Stable Concept ID를 의미 식별자로 사용한다.
- Published Ontology revision은 직접 수정하지 않는다. 변경은 Published version에서 새 Draft를 생성해 검토·승인·게시한다.
- Authoring DB 모델을 Runtime contract로 직접 사용하지 않는다. Runtime은 Published version에서 생성된 immutable artifact를 사용한다.
- 기존 YAML Ontology Object를 추가·제거하면 `platform/ontology-migrations/ontology-v2.yaml` 분류도 함께 갱신하고 `teoria ontology-migration-report`를 실행한다.
- 운영 환경에서는 `TEORIA_ADMIN_AUTH_MODE=bearer`와 별도 Admin token을 사용한다. 개발용 disabled mode를 외부에 노출하지 않는다.

Application DB migration을 변경하면 새 순번 migration만 추가하고 이미 적용된 SQL을 변경하지 않는다. 다음을 함께 검증한다.

```bash
uv run --locked --package teoria-platform pytest platform/tests
docker compose -f deploy/compose/compose.yaml config --quiet
```

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
  -f deploy/compose/compose.yaml \
  config --quiet
```

- Flow의 주요 단계는 Prefect Task로 표현해 UI에서 실행 순서와 실패 지점을 식별할 수 있어야 한다.
- 원본 응답 저장과 정규 적재가 모두 성공한 뒤에만 Checkpoint를 갱신한다.
- migration은 새 순번 파일로 추가하고 이미 적용된 SQL을 변경하지 않는다.

MCP 변경 후 다음 명령을 실행한다.

```bash
uv run --locked --package teoria-mcp pytest mcp/tests
```
