# Teoria architecture

Teoria는 세 코드 프로젝트, 하나의 공유 라이브러리, OpenMetadata
Metadata Foundation으로 구성한다.

```text
pipelines ──SQL write──▶ Teoria Data DB ◀──SQL read── platform
mcp ──Runtime HTTP API────────────────────────────────▶ platform

platform ──▶ teoria-provider ◀── pipelines
platform ──REST reference/write-back──▶ OpenMetadata
PostgreSQL ──metadata ingestion───────▶ OpenMetadata
```

| 구성 | 책임 |
|---|---|
| Semantic Platform | Registry, 검증·발행, Source 실행, Mapping, Capability Runtime |
| Data Pipelines | Connector, Prefect Flow·Task, raw·정규화·적재, DB migration |
| MCP Gateway | MCP protocol과 Runtime API 변환 |
| Provider library | API wire schema, 요청 생성, 응답 검증, retry와 오류 |
| OpenMetadata | Technical/Semantic Metadata, Glossary, Tag, Owner, Lineage, Quality |

Teoria Application DB는 Business Ontology, Semantic Binding, Suggestion과
Review만 저장한다. OpenMetadata entity 본문은 복제하지 않는다.

로컬 Compose는 부하 경계에 따라 두 PostgreSQL 인스턴스를 사용한다.

```text
postgres (Data Plane)
└── teoria_data
    ├── ingestion
    └── public_procurement

platform-postgres (Control/Application Plane)
├── teoria_app       (role: teoria_app)
├── prefect          (role: prefect)
└── openmetadata_db  (role: openmetadata_user)
```

세 Control database는 물리 인스턴스만 공유하며 schema, owner, credential,
migration과 connection URL은 독립적이다. 운영 부하가 증가하면 접속 URL만
변경해 Prefect나 OpenMetadata를 다시 별도 PostgreSQL로 분리할 수 있다.

## 원칙

- 프로젝트 간 연결은 HTTP, SQL 계약 또는 versioned Registry Bundle을 사용한다.
- 수집 API는 `pipelines/connectors`, Runtime 직접 호출 API·DB는 `platform/registries/sources`가 소유한다.
- Pipeline 정규화와 Semantic Mapping을 분리한다.
- MCP는 목표 운영 구조에서 Source 키나 DB 권한을 갖지 않는다.
- `packages/provider`는 라이브러리이며 서비스·DB·Registry를 갖지 않는다.
- 하나의 `uv.lock`을 공유하되 프로젝트별 `pyproject.toml`과 Dockerfile로 독립 배포한다.

MCP STDIO는 `TEORIA_MCP_RUNTIME_MODE=remote`만 지원하며 Runtime API를 HTTP로 호출한다.
MCP는 Platform을 embedded import하지 않고 Source 인증정보나 Data DB 권한도 갖지 않는다.
세부 소유권은 [Repository Structure](repository-structure.md)를 따른다.
