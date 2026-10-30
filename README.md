# Teoria

Teoria는 데이터 자산과 업무 의미를 연결하는 **AI-Native Metadata & Ontology Platform**이다.
OpenMetadata의 데이터 자산을 탐색하고, Ontology와 의미 연결을 작성하며, AI가 만든 변경안을 검토한다.
**FormatID — 규격서 기반 물품 구조화·분석**은 첫 업무 앱이다. 물품·구성품·속성·조건을 원문 근거와 함께 추출한다.

## 어디서 시작하나

| 하려는 일 | 안내 |
|---|---|
| 제품과 화면 이해 | [사용 안내](docs/platform-guide.md) |
| FormatID 처리와 Codex 사용 단계 확인 | [파이프라인](docs/procurement_specification_processing/pipeline.md) |
| 물품·구성품·분류·속성 모델 이해 | [물품 모델](docs/architecture/specification_goods_model.md) |
| 로컬 실행·환경 설정 | [Compose](docs/deployment/compose.md) · [환경 설정](docs/deployment/configuration.md) |
| 개발 위치와 책임 확인 | [저장소 구조](docs/architecture/repository-structure.md) |
| 구현 상태와 다음 작업 확인 | [로드맵](docs/roadmap.md) |

전체 문서는 [문서 목차](docs/index.md), 실제 실행 결과는 [검증 기록](docs/verification/index.md)에서 찾는다.

## 서비스 실행과 종료

명령은 저장소 루트에서 실행한다. 종료 전에는 Prefect에서 신규 실행·스케줄을 멈추고
실행 중인 작업이 끝났는지 확인한다.

### Docker Compose

공통 기반에 `mlops`(학습·배포·데모 서빙), `semantic`(Metadata·Ontology·Runtime),
`formatid`(규격서 기반 물품 구조화·분석)를 선택한다.
`.env`·이미지·선택 기능의 인증과 게시 artifact를 준비한다.

```bash
# 전체 구성 확인 → 명시적 빌드 → 초기화·등록·실행
bash deploy/compose/deploy.sh config --all
bash deploy/compose/deploy.sh build --all
bash deploy/compose/deploy.sh deploy --all

# 선택 실행 예시: MLOps만 사용 (위 전체 구성 대신 선택)
bash deploy/compose/deploy.sh deploy --modules mlops

# 성공한 배포에서 저장한 구성으로 상태 확인·중지·재시작·삭제
bash deploy/compose/deploy.sh status
bash deploy/compose/deploy.sh stop
bash deploy/compose/deploy.sh start
bash deploy/compose/deploy.sh down
```

`start`는 재빌드·migration을 하지 않는다. 초기화 작업은 완료 후 컨테이너를 제거하며,
`down`도 데이터 볼륨·이미지를 보존한다. 구성 변경 전에는 기존 구성으로 `down`한다.
배포 성공 후 현재·직전 이미지를 보존하고 사용하지 않는 Teoria 이미지를 정리한다.
자세한 준비·종료·정리 기준은 [Compose 운영 안내](docs/deployment/compose.md)를 따른다.

### K3s

EC2 배포 계정에서 kubeconfig·Secret·게시 Runtime artifact를 준비한 뒤 실행한다.
이미지가 GHCR에 게시된 커밋의 배포 파일을 사용하고, 아래 세 인자를 실제 값으로 바꾼다.

```bash
# 실행·재배포·중지 후 재개: COMMIT_SHA는 40자리 커밋 SHA
bash deploy/k3s/deploy.sh ghcr.io/owner/repository COMMIT_SHA teoria.example.com

# 상태 확인: 상시 서비스와 별도 실행 Job
kubectl -n teoria get deploy,statefulset,pod,job
kubectl -n teoria-pipelines get pod,job

# Teoria 중지: 실행 Job이 모두 종료된 뒤 API·Worker, DB·검색 순으로 축소
kubectl -n teoria scale deployment --all --replicas=0
kubectl -n teoria get pod
```

API·Worker 등 Deployment의 Pod가 종료된 것을 확인한 뒤 DB·검색도 중지한다.

```bash
kubectl -n teoria scale statefulset --all --replicas=0
kubectl -n teoria wait --for=delete pod --timeout=300s
```

Deployment·StatefulSet·PVC·Secret과 K3s 클러스터는 유지한다. 별도 실행 Job은 replica 축소로 중지되지 않는다.
Pod만 삭제하면 자동 재생성되므로 종료에는 replica를 0으로 설정한다.
재개 명령은 migration·등록을 다시 수행하고 배포 파일의 replica 설정을 적용하므로,
선택형 Worker와 운영 override도 확인한다. 자동 배포가 실행되면 서비스가 재개될 수 있다.
일반 종료에 namespace·PVC 삭제나 K3s 제거 명령을 사용하지 않는다.
최초 설치·자동 배포·검증 범위는 [K3s 운영 안내](docs/deployment/k3s.md)를 따른다.

## 코드 구조

| 위치 | 내용 |
|---|---|
| `backend/src/teoria/` | API·업무 기능·외부 연결·Prefect 실행 |
| `frontend/` | 관리 화면과 FormatID 앱 |
| `deploy/` | Compose·K3s의 서비스·Prefect 실행 정책 |
| `docs/` | 현재 사용·설계·개발·운영 안내 |
| `archive/` | 비활성 코드와 [과거 문서](archive/documentation/index.md) |

Python 의존성은 `backend/pyproject.toml`·`backend/uv.lock`에서 관리한다.
API·Runtime·MCP·각 Worker는 별도 이미지와 권한을 사용한다.
현재 구현과 후속 계획은 구분한다. 규격서 추출 결과가 자동으로 Published Ontology가 되지는 않는다.
