# Teoria

Teoria는 데이터 자산과 업무 의미를 연결하는 **AI-Native Metadata & Ontology Platform**이다.
OpenMetadata의 데이터 자산을 탐색하고, Ontology와 의미 연결을 작성하며, AI가 만든 변경안을 검토한다.
규격서 분석은 첫 업무 앱이다. 물품·구성품·속성·조건을 원문 근거와 함께 추출한다.

## 어디서 시작하나

| 하려는 일 | 안내 |
|---|---|
| 제품과 화면 이해 | [사용 안내](docs/platform-guide.md) |
| 규격서 처리와 Codex 사용 단계 확인 | [파이프라인](docs/procurement_specification_processing/pipeline.md) |
| 물품·구성품·분류·속성 모델 이해 | [물품 모델](docs/architecture/specification_goods_model.md) |
| 로컬 실행·환경 설정 | [Compose](docs/deployment/compose.md) · [환경 설정](docs/deployment/configuration.md) |
| 개발 위치와 책임 확인 | [저장소 구조](docs/architecture/repository-structure.md) |
| 구현 상태와 다음 작업 확인 | [로드맵](docs/roadmap.md) |

전체 문서는 [문서 목차](docs/index.md), 실제 실행 결과는 [검증 기록](docs/verification/index.md)에서 찾는다.

## 코드 구조

| 위치 | 내용 |
|---|---|
| `backend/src/teoria/` | API·업무 기능·외부 연결·Prefect 실행 |
| `frontend/` | 관리 화면과 규격서 분석 앱 |
| `deploy/` | Compose·K3s·Prefect 배포 설정 |
| `docs/` | 현재 사용·설계·개발·운영 안내 |
| `archive/` | 비활성 코드와 [과거 문서](archive/documentation/index.md) |

Python 의존성은 `backend/pyproject.toml`·`backend/uv.lock`에서 관리한다.
API·Runtime·MCP·각 Worker는 별도 이미지와 권한을 사용한다.
현재 구현과 후속 계획은 구분한다. 규격서 추출 결과가 자동으로 Published Ontology가 되지는 않는다.
