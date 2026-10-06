# Teoria

Teoria는 AI-Native Metadata & Ontology Platform이다. OpenMetadata가 데이터와 semantic/governance metadata를 설명하고, Teoria가 Business Ontology, Semantic Binding, Metadata Intelligence, Capability semantics와 향후 Context Engine을 제공한다. Prefect는 데이터 수집·변환·동기화 workflow를 담당한다.

공공조달은 플랫폼 전체가 아니라 첫 vertical domain이다. 조달에서 검증한
Source→Metadata→Ontology→Capability→Context 경로를 다른 업무 도메인으로
확장하되, 조달 고유 모델과 정책을 Platform 공통 계약으로 일반화하지 않는다.

```text
External API ─▶ Prefect ─▶ Teoria Data DB ─▶ OpenMetadata
                                            Technical + Semantic Metadata

AI Client ─▶ MCP / API ─▶ Context Engine (future)
                               │
             ┌─────────────────┼─────────────────┐
             ▼                 ▼                 ▼
      Business Ontology   OpenMetadata      Capabilities
             └──────────── Semantic Binding ─────┘
```

저장소 권위는 다음과 같이 분리한다.

| Store | 소유 데이터 |
|---|---|
| `teoria_data` | 수집·정규화된 실제 데이터 |
| `prefect` | Workflow 실행·스케줄·로그 상태 |
| `openmetadata_db` | Technical, Governance, Semantic Metadata |
| `teoria_app` | Business Ontology, Binding, Intelligence 운영정보 |

로컬 Compose에서는 `teoria_data`를 Data Plane PostgreSQL에 단독 배치하고,
나머지 세 database는 `platform-postgres` 인스턴스를 공유한다. database와
role은 계속 분리되어 운영 환경에서 독립 인스턴스로 다시 분리할 수 있다.

OpenMetadata entity는 Teoria에 복제하지 않고 ID/FQN/version을 가진 `MetadataTargetRef`로 참조한다.

Admin 쓰기 API는 명시적인 인증·역할 경계를 사용한다. 로컬 개발은
`TEORIA_ADMIN_AUTH_MODE=disabled`가 기본이지만 공유·운영 배포에서는
`bearer`와 `TEORIA_ADMIN_API_TOKEN`을 설정해야 한다. Semantic Binding은
`draft → approved/rejected → deprecated` 생명주기와 변경 불가능한 검토
기록을 사용한다.

Business Ontology authoring은 Stable Concept과 version별 revision을
분리한다. Published version은 PostgreSQL에서도 수정할 수 없으며, Draft
검토·승인 후 deterministic Runtime Artifact를 생성해야만 게시된다.

## 구성

| 경로 | 책임 |
|---|---|
| `platform/` | Business Ontology, Semantic Binding, Metadata Intelligence, Source·Capability Runtime |
| `platform/admin_ui/` | Semantic Registry 관리자용 React UI |
| `pipelines/` | Connector, Prefect Flow, raw·정규 적재, DB migration |
| `mcp/` | Capability를 MCP Tool로 제공 |
| `packages/provider_api/` | Platform·Pipelines가 공유하는 Provider API wire 계약과 HTTP 실행 |
| `deploy/` | 지원되는 로컬 Compose와 실험 단계의 배포 스캐폴드 |
| `docs/` | 아키텍처와 작성·운영 규칙 |

상세 경계는 [Repository Structure](docs/architecture/repository-structure.md)를 따른다.
`packages/`는 장래 기능의 대기 장소가 아니다. 둘 이상의 프로젝트가 실제로
공유하고 독립 테스트할 수 있는 설치형 계약만 이 경계로 추출한다.

## 시작

```bash
cp deploy/compose/.env.example deploy/compose/.env
export TEORIA_ENV_FILE=deploy/compose/.env
uv sync --locked --all-packages --all-groups
```

테스트와 계약 검증:

```bash
uv run --locked --package teoria-provider-api pytest packages/provider_api/tests
uv run --locked --package teoria-platform pytest platform/tests
uv run --locked --package teoria-pipelines pytest pipelines/tests
uv run --locked --package teoria-mcp pytest mcp/tests

uv run --locked --package teoria-platform teoria validate platform/registries
uv run --locked --package teoria-pipelines teoria-pipelines validate pipelines
uv run --locked --package teoria-pipelines --group validation \
  teoria-pipelines validate-integration pipelines \
  --platform-registries platform/registries
```

운영 Runtime은 원본 Registry나 authoring table 대신 Registry, Published Ontology와
Approved Binding을 함께 고정한 Runtime bundle을 사용한다.

```bash
uv run --locked --package teoria-platform teoria publish platform/registries \
  --version YYYY.MM.DD.REVISION --output dist/registry
uv run --locked --package teoria-platform teoria compile-runtime-bundle \
  dist/registry/YYYY.MM.DD.REVISION --output dist/runtime \
  --version YYYY.MM.DD.REVISION \
  --database-url "$TEORIA_APP_DATABASE_URL"
uv run --locked --package teoria-platform teoria activate-artifact dist/runtime \
  --version YYYY.MM.DD.REVISION
export TEORIA_RUNTIME_ARTIFACT_STORE=dist/runtime
```

MCP STDIO:

```bash
uv run --locked --package teoria-mcp teoria-mcp
```

Prefect와 Data DB:

```bash
docker compose --env-file deploy/compose/.env \
  -f deploy/compose/compose.yaml \
  up --build -d
```

OpenMetadata Metadata Foundation까지 함께 실행:

```bash
docker compose --env-file deploy/compose/.env \
  -f deploy/compose/compose.yaml \
  --profile metadata up --build -d
```

OpenMetadata는 Prefect와 같은 기본 Compose 안에 있으며 `metadata` 프로필로 선택 실행한다. 자세한 ingestion과 credential 설정은 [OpenMetadata 개발 통합](deploy/compose/openmetadata/README.md)을 참고한다.

이 프로필은 Airflow를 실행하지 않는다. PostgreSQL metadata ingestion은
Prefect가 스케줄하는 일회성 OpenMetadata ingestion container로 실행하며,
개발환경에서는 `metadata-ingestion` 프로필의 `openmetadata-ingestion-job`을
직접 실행할 수 있다.

기본 Compose는 nginx의 8081 포트만 공개한다. `metadata` 프로필을 켜면 OpenMetadata UI/API용 8585 포트가 추가된다. Platform Admin UI는 `http://localhost:8081/`, Prefect UI는 `http://localhost:8081/prefect/`, Runtime API docs는 `http://localhost:8081/runtime-api/docs`, OpenMetadata는 `http://localhost:8585/`에서 확인한다.

`deploy/experimental/k3s/`는 향후 Kubernetes 배포를 위한 스캐폴드이며 현재
지원되는 운영 배포 계약이 아니다.

## 문서

- [플랫폼 구성과 사용 가이드](docs/platform-guide.md)
- [제품 개발 로드맵](docs/roadmap.md)
- [문서 안내](docs/README.md)
- [Architecture](docs/architecture/overview.md)
- [Ontology와 Semantic Binding](docs/architecture/ontology.md)
- [Source 작성](docs/registry/source-authoring.md)
- [Registry Guide](docs/registry/README.md)
- [Pipeline과 Prefect](docs/ingestion/prefect.md)
- [MCP](docs/mcp.md)
