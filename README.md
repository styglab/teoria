# Teoria

Teoria는 AI-Native Metadata & Ontology Platform이다. OpenMetadata가 데이터 자산과
기술·거버넌스 metadata를, Teoria가 Business Ontology·Semantic Binding·Metadata
Intelligence·Capability와 Context 실행을 담당한다. Prefect는 수집·변환·동기화를 관리한다.
공공조달은 이 경로를 검증하는 첫 vertical domain이다.

```text
Provider API → Pipelines / Prefect → Data DB → OpenMetadata
                                      ↓           ↕ Semantic Binding
AI Client → MCP / Runtime API → Capability·Context ← Ontology
```

## 시작

[시작과 역할별 작업](docs/platform-guide.md)에서 환경 설정, 스택 실행과 작업 흐름을
확인한다. 전체 문서는 [문서 목차](docs/index.md), 시스템의 책임 경계는
[아키텍처](docs/architecture/overview.md)를 따른다.

## 저장소 구성

| 위치 | 책임 | 안내 |
|---|---|---|
| `platform/` | Ontology·Binding·Metadata Intelligence·Registry·Runtime·Admin UI | [개발](docs/platform/development.md) |
| `pipelines/` | Connector·Prefect·수집·정규화·Data DB | [개발](docs/pipelines/development.md) |
| `mcp/` | Runtime HTTP API를 사용하는 MCP Gateway | [실행·연결](docs/mcp/gateway.md) |
| `packages/provider_api/` | Provider wire 계약과 HTTP 실행 라이브러리 | [패키지](docs/packages/provider_api.md) |
| `deploy/` | 로컬 Compose·EC2 K3s·GitHub 자동 배포 | [K3s 배포](docs/deployment/k3s.md) |
| `docs/` | 사용·개발·운영 안내와 검증 기록 | [목차](docs/index.md) |

프로젝트는 각자의 `pyproject.toml`을 사용하고 루트 `uv.lock`을 공유한다.
OpenMetadata entity를 Teoria DB에 복제하지 않으며 MCP는 Runtime API만 호출한다.
운영 Runtime은 게시된 Ontology·승인된 Binding·Registry를 고정한 checksum 검증 bundle을
사용한다. 자세한 개발 규칙은 [저장소 구조](docs/architecture/repository-structure.md)를 따른다.

## 자주 찾는 문서

- [환경 설정](docs/deployment/configuration.md), [Compose](docs/deployment/compose.md), [EC2 K3s](docs/deployment/k3s.md), [OpenMetadata](docs/deployment/openmetadata.md)
- [Registry 작성](docs/platform/registry/guide.md), [Ontology](docs/platform/ontology.md), [Runtime 배포](docs/platform/runtime.md)
- [Prefect 운영](docs/pipelines/prefect.md), [배포 목록](docs/pipelines/deployments.md)
- [Admin UI](docs/platform/admin_ui.md), [자산 진단](docs/platform/metadata/asset_assessment.md)
- [제품 로드맵](docs/roadmap.md), [검증 기록](docs/verification/index.md)
