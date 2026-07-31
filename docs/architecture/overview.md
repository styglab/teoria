# Teoria architecture

Teoria는 세 배포 프로젝트와 하나의 공유 라이브러리로 구성한다.

```text
pipelines ──SQL write──▶ Teoria Data DB ◀──SQL read── platform
mcp ──Runtime HTTP API(target)────────────────────────▶ platform

platform ──▶ teoria-provider ◀── pipelines
```

| 구성 | 책임 |
|---|---|
| Semantic Platform | Registry, 검증·발행, Source 실행, Mapping, Capability Runtime |
| Data Pipelines | Connector, Prefect Flow·Task, raw·정규화·적재, DB migration |
| MCP Gateway | MCP protocol과 Runtime API 변환 |
| Provider library | API wire schema, 요청 생성, 응답 검증, retry와 오류 |

## 원칙

- 프로젝트 간 연결은 HTTP, SQL 계약 또는 versioned Registry Bundle을 사용한다.
- 수집 API는 `pipelines/connectors`, Runtime 직접 호출 API·DB는 `platform/registries/sources`가 소유한다.
- Pipeline 정규화와 Semantic Mapping을 분리한다.
- MCP는 목표 운영 구조에서 Source 키나 DB 권한을 갖지 않는다.
- `packages/provider`는 라이브러리이며 서비스·DB·Registry를 갖지 않는다.
- 하나의 `uv.lock`을 공유하되 프로젝트별 `pyproject.toml`과 Dockerfile로 독립 배포한다.

현재 MCP STDIO는 Runtime API 구현 전까지 embedded Runtime을 사용하는 개발 호환 모드다. 세부 소유권은 [Repository Structure](repository-structure.md)를 따른다.
