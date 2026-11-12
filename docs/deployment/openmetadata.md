# OpenMetadata 배포와 업그레이드

OpenMetadata는 기술·거버넌스·Semantic Metadata의 권위 저장소다.
Teoria의 통합 Kubernetes 구성에서 별도 수명주기로 설치·업그레이드한다.
수집·일정·재시도는 Prefect가 소유하고, 공식 ingestion 이미지 기반의 일회성 Job을 사용한다.
기본 구성에 Airflow를 추가하지 않는다.

## 서버 준비

[통합 배포](kubernetes.md)의 DB·Secret을 준비한 뒤 실행한다.

```bash
source deploy/kubernetes/k3d/.local/session.env
bash deploy/kubernetes/k3d/local.sh deploy --component database
bash deploy/kubernetes/k3d/local.sh deploy --component openmetadata
```

| 구성 | 역할 |
|---|---|
| `platform-postgres`의 `openmetadata_db`·`openmetadata_user` | OpenMetadata 전용 DB·계정 |
| `openmetadata-search` | 전용 검색 인덱스 |
| `openmetadata-migrate` | 서버 시작 전 schema migration |
| `openmetadata-server` | UI·REST API, 내부 8585 포트 |

서버·migration·검색 정의는 `deploy/kubernetes/base/services/openmetadata/`가 소유한다.
서버 이미지는 검증한 버전으로 고정하고 변경 시 DB·검색 호환성과 백업·복구 절차를 함께 검증한다.
Teoria Application DB·Data DB와 OpenMetadata의 저장 책임은 구분한다.

운영 UI 접속은 조직의 Ingress·DNS·인증 정책으로 별도 준비한다.
임시 로컬 점검에는 다음 명령을 사용할 수 있다.

```bash
kubectl -n teoria port-forward service/openmetadata-server 8585:8585
```

## 플랫폼 연결과 메타데이터 수집

1. 관리자·bot 계정과 토큰을 준비한다.
2. 운영 ConfigMap의 `TEORIA_OPENMETADATA_BASE_URL`과 Secret의 `TEORIA_OPENMETADATA_AUTH_TOKEN`을 설정한다.
3. `local.sh deploy`로 Teoria를 갱신하고 데이터 자산 화면·연결 상태를 확인한다.
4. Teoria Data DB 동기화를 쓰려면 읽기 전용 `teoria_metadata` 계정과
   `OPENMETADATA_INGESTION_BOT_TOKEN`도 준비한다.
5. 원천 접근을 검증한 뒤 `TEORIA_METADATA_SYNC_SCHEDULE_ENABLED=true`로 바꾸고 배포해 일정을 활성화한다.

Metadata Worker의 pool은 `teoria-metadata`다. Worker는 process 방식으로 실행하지만 실제 ingestion은
`teoria` namespace의 일회성 Kubernetes Job으로 격리한다. 일반 Worker 이미지에 공식 ingestion dependency를 설치하지 않는다.
Job은 허용한 고정 이미지와 전용 인증정보만 사용한다. 모델·도메인 작업의 credential은 전달하지 않는다.

기준 위치:

- 공통 Flow·일정: `backend/config/metadata_management/prefect_deployments.yaml`
- 환경별 pool·실행 정책: `deploy/kubernetes/prefect/metadata_management.yaml`
- 이미지 빌드: `deploy/image_builds/openmetadata/Dockerfile`
- Teoria Data DB 수집 설정: `deploy/image_builds/openmetadata/ingestion/teoria-postgres.yaml.example`
- 실행 코드: `backend/src/teoria/platform/data/metadata/ingestion/`

위 기본 ingestion 설정은 기존 Teoria Data PostgreSQL을 대상으로 한다. 다른 원천에 그대로 적용하지 않는다.
OpenMetadata의 metadata·description·owner·tag·glossary·lineage를 Teoria DB에 복제하지 않는다.
서버 설치·API 연결·실제 ingestion 성공은 각각 확인하며 YAML 검증을 실제 운영 성공으로 기록하지 않는다.
