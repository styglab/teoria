# Teoria

Teoria는 AI-Native Metadata & Ontology Platform이다. OpenMetadata가 데이터 자산과
기술·거버넌스 metadata를, Teoria가 Business Ontology·Semantic Binding·Metadata
Intelligence·Capability와 Context 실행을 담당한다. Prefect는 수집·변환·동기화를 관리한다.
현재 활성 업무는 명시 입력 규격서의 파싱·물품 정보 추출·표준 후보 관리와 물품 Ontology 구축이다.
법령 수집·조회는 메타데이터 진단의 근거 저장소로 운영한다.
이전 기업·공고·계약·낙찰 분석과 조달 API 수집은 `archive/procurement_services/`에 비활성 보관한다.

```text
규격서 → Pipelines / Prefect → 원문·추출 산출물 + Data DB 실행·참조
                                       ↓ metadata
                                  OpenMetadata
                                       ↕ Semantic Binding
AI Client → MCP / Runtime API → Capability·Context ← Ontology
```

추출 결과와 물품 Ontology·Capability의 연결은 후속 구현이다. 현재 활성 Registry는
공통 타입만 포함하며 이전 조달 Capability를 노출하지 않는다.

## 시작

[시작과 역할별 작업](docs/platform-guide.md)에서 환경 설정, 스택 실행과 작업 흐름을
확인한다. 전체 문서는 [문서 목차](docs/index.md), 시스템의 책임 경계는
[아키텍처](docs/architecture/overview.md)를 따른다.

## 저장소 구성

| 위치 | 책임 | 안내 |
|---|---|---|
| `backend/` | 기능별 Python 백엔드·API·MCP·Prefect 실행 | [구조와 소유권](docs/architecture/repository-structure.md) |
| `frontend/` | React 관리 UI | [UI 개발](docs/platform/admin_ui.md) |
| `deploy/` | 로컬 Compose·EC2 K3s·GitHub 자동 배포 | [K3s 배포](docs/deployment/k3s.md) |
| `docs/` | 사용·개발·운영 안내와 검증 기록 | [목차](docs/index.md) |

Python 의존성의 기준은 `backend/pyproject.toml`과 `backend/uv.lock`이다.
API·MCP·규격서·법령·메타데이터 Worker는 역할별 이미지와 권한으로 분리한다.
OpenMetadata entity를 Teoria DB에 복제하지 않으며 MCP는 Runtime API만 호출한다.
운영 Runtime은 게시된 Ontology·승인된 Binding·Registry를 고정한 checksum 검증 bundle을
사용한다. 자세한 개발 규칙은 [저장소 구조](docs/architecture/repository-structure.md)를 따른다.

현재 Compose 전환 상태는 [통합 백엔드 운영 재배포](docs/verification/backend_consolidation_deployment_2026_10_25.md), 남은 기능은 [로드맵](docs/roadmap.md)을 따른다.

## 자주 찾는 문서

- [환경 설정](docs/deployment/configuration.md), [Compose](docs/deployment/compose.md), [EC2 K3s](docs/deployment/k3s.md), [OpenMetadata](docs/deployment/openmetadata.md)
- [Registry 작성](docs/platform/registry/guide.md), [Ontology](docs/platform/ontology.md), [Runtime 배포](docs/platform/runtime.md)
- [Prefect 운영](docs/pipelines/prefect.md), [배포 목록](docs/pipelines/deployments.md)
- [Admin UI](docs/platform/admin_ui.md), [자산 진단](docs/platform/metadata/asset_assessment.md)
- [제품 로드맵](docs/roadmap.md), [검증 기록](docs/verification/index.md)
