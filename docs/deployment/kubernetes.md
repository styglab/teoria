# Kubernetes 통합 Teoria 배포

Metadata·Ontology·MLOps를 하나의 Teoria 실행 구성으로 운영한다.
API·UI·Runtime·Worker의 역할과 이미지·권한은 분리한다. 기능 조합별 설치 경로는 사용하지 않는다.
시작점은 [배포 안내](../../deploy/README.md)다.

## 공통 정의와 환경 차이

```text
deploy/kubernetes/
  deploy.sh                  단일 배포 진입점
  base/
    teoria/                  플랫폼 정의·권한·migration·등록 Job
    services/                PostgreSQL·MinIO·Prefect·MLflow·OpenMetadata·Redis
    domains/                 물품·법령 Worker·등록 Job
  overlays/
    generic/                 표준 Ingress·운영자가 지정한 저장소
    k3s/                     Traefik·local-path·노드 설치 설정
    k3d/                     Traefik·teoria-local 보존 저장소
  base/teoria/web_proxy/      공통 UI nginx 프록시
  prefect/                   pool·queue·실행 Job 정책
  harbor/                    독립 Registry 설치
```

모든 환경에서 Ingress 하나가 UI로 연결되고, 기존 UI nginx가 `/admin-api/`, `/runtime-api/`,
`/prefect/`, `/mlflow/`를 내부 서비스로 전달한다. MLflow 운영 화면은 Prefect 운영 계정으로 인증한다.
Traefik 전용 prefix Middleware와 별도 프록시 상시 컨테이너는 사용하지 않는다.
운영은 Teoria·Harbor 각각 DNS 이름과 HTTPS 443을 사용한다.
개발 IP 접근은 [k3d 원격 접속](k3d.md#원격-ip-접속)을 따른다.

## 배포 전에 준비할 것

Bash·Python 3·`flock`·Kustomize를 지원하는 kubectl과 대상 클러스터 접근 권한이 필요하다.
명령은 배포 에이전트·개발 PC·폐쇄망 내부 운영 PC에서 실행할 수 있으며 GitHub Actions가 필수는 아니다.

1. `KUBECONFIG`, 대상 노드, Ingress controller·IngressClass를 확인한다.
2. 플랫폼·Harbor 이미지와 TLS·Registry pull 인증을 준비한다.
3. [envs/dev·prod](../../deploy/kubernetes/envs/README.md)의 예시로 역할별 실제 env 파일을 준비하고
   대상 context를 명시해 Secret을 등록한다.
4. 연결 ConfigMap과 이미 검토·게시된 Runtime artifact를 준비한다.
5. 일반 Kubernetes에는 Runtime·정책 산출물을 공유할 RWX StorageClass를 지정한다.

플랫폼 namespace는 `teoria`, 수집 실행은 `teoria-pipelines`, 모델 실행은 `teoria-models`다.
모델 namespace의 `model-images`·`model-workload` Secret도 사전에 준비한다.
운영 API는 bearer 인증을 사용하며 개발용 disabled 인증을 외부에 노출하지 않는다.

최초 OpenMetadata 관리자·bot 계정과 Runtime artifact는 운영자가 별도로 준비한다.
빈 저장소에서 `runtime-artifact-check`로 멈추는 것은 정상이다. 배포는 authoring YAML을 자동 승인·게시하지 않는다.
구체적인 초기 데이터 준비는 [k3d 안내](k3d.md#인증정보와-최초-데이터)를 따른다.

## 연결·도메인 실행 설정

[환경별 설정 도구](../../deploy/kubernetes/envs/README.md)에서 실제 `connections.env`를 준비하고 등록한다.

```bash
# k3d 예시. 다른 클러스터는 해당 kubeconfig와 context를 사용한다.
export KUBECONFIG="${TEORIA_K3D_KUBECONFIG:-deploy/kubernetes/k3d/.local/kubeconfig}"
bash deploy/kubernetes/envs/settings.sh init --env dev
# envs/dev/connections.env와 필요한 인증정보 파일을 수정한 후:
bash deploy/kubernetes/envs/settings.sh apply --env dev --context k3d-teoria --role connections
```

기존 ConfigMap 이름을 유지한다. 배포는 예시를 자동 등록하거나 기존 값을 덮어쓰지 않는다. ConfigMap이 없거나 필요한 키가 빠지면 변경 전에 중단한다.
이전에 MLOps만 설치했다면 OpenMetadata 연결·토큰·Runtime artifact·Data DB와 아래 운영 설정을 추가해야 한다.

| 설정 | 기본값 | 역할 |
|---|---|---|
| `TEORIA_METADATA_SYNC_SCHEDULE_ENABLED` | `false` | 기존 Teoria Data DB 메타데이터 동기화 일정 |
| `TEORIA_SPECIFICATION_PROCESSING_ENABLED` | `false` | FormatID·물품 작성 API·규격서 Worker·선언된 일정 |
| `TEORIA_LEGAL_INFORMATION_ENABLED` | `false` | 법령 API·Worker·선언된 일정 |

도메인 활성화 전 원천·API 인증·객체 저장소·모델 추론 인증 등 소유 기능의 실행 조건을 별도로 충족한다.
파일의 값을 `true`로 바꾸고 `--role connections`로 등록한 뒤 플랫폼을 배포하면 해당 API가 활성화되고 도메인 Worker가 1개 실행된다.
`false`이면 API는 비활성화하고 Worker는 0개로 두며 해당 Flow의 일정을 비활성화한다.
공통 Flow에 일정이 선언되지 않았다면 자동으로 새 일정을 만들지 않는다.
규격서 Job에는 법령 키나 모델 실행 자격증명을 넘기지 않는다. 역할별 Job Secret은 분리한다.
메타데이터 동기화 일정은 DB 읽기 계정과 ingestion bot token을 준비한 뒤 활성화한다.

## 명령과 실행 순서

```bash
# YAML만 확인 — 클러스터에 접속하지 않음
bash deploy/kubernetes/deploy.sh harbor.example.com/teoria COMMIT_SHA teoria.example.com \
  --overlay k3s --render

# 기반 서비스·인증정보·게시 artifact 준비 후 최초 설치
bash deploy/kubernetes/deploy.sh harbor.example.com/teoria COMMIT_SHA teoria.example.com \
  --overlay k3s --component all --model-registry-host harbor.example.com

# 이후 플랫폼만 갱신 — component 기본값은 platform
bash deploy/kubernetes/deploy.sh harbor.example.com/teoria COMMIT_SHA teoria.example.com \
  --overlay k3s --model-registry-host harbor.example.com
```

일반 Kubernetes는 `--overlay generic --storage-class <CSI> --shared-storage-class <RWX> --ingress-class <CLASS>`를 지정한다.
`COMMIT_SHA`에는 40자리 이미지 태그를 사용한다. 이미지 Registry prefix는 `host/project` 형식이다.
기존 `--modules`·`--features`는 제거했으며 오류와 함께 새 사용법을 안내한다.

| component | 수행 작업 |
|---|---|
| `database` | Platform·Data PostgreSQL → 플랫폼 DB·계정 준비 → Data 계정·migration·Metadata 읽기 권한 |
| `storage` | MinIO → 모델 bucket 초기화 |
| `workflow` | Prefect Redis → Server·Services |
| `mlflow` | MLflow 서버·자신의 schema 관리 |
| `openmetadata` | 검색 준비 → schema migration → Metadata Server |
| `platform` | Application DB migration → 정책 생성·artifact 검증 → API·UI·Runtime·Worker → 연결 확인 → Flow 등록·Worker 활성화 |
| `all` | 인증·게시 artifact가 준비된 환경에서 위 단위를 표 순서로 조립 |

플랫폼 갱신은 DB 서버·MinIO·Prefect·MLflow·OpenMetadata 설치 정의를 다시 적용하지 않는다.
Data DB schema 변경은 `database` 단위로 명시적으로 적용한다. Application DB migration은 플랫폼 갱신에 포함한다.
플랫폼의 Runtime 캐시·정책·artifact PVC는 플랫폼 실행 구성에 포함한다.
Harbor·이미지 빌드·외부 이미지 반입은 `all`에도 포함하지 않는다.

검증·등록이 끝나기 전에는 Prefect Worker를 0개로 유지한다.
실패하면 후속 단계를 중단하며 PVC·DB·게시 이력을 삭제하지 않는다. 실행 중인 업무는 배포 전에 운영자가 확인한다.
`--render`는 기본 도메인 Worker 0개를 표시한다. 실제 활성 수는 운영 ConfigMap 검증 후 배포가 반영한다.

## 실제 환경 검증

렌더링·모의 배포·API schema 검사는 실제 설치 성공과 구분한다.
이번 통합은 정지된 개발 k3d를 다시 시작하거나 재배포하지 않는다.
기존 데이터 경로·리소스 이름은 유지하지만, 통합 신규 설치·외부 서비스 연결·운영 이관은 실환경 검증이 필요하다.

[Registry·폐쇄망 반입](image_registry.md) · [k3d](k3d.md) · [k3s](k3s.md) · [검증 기록](harbor_validation.md)

설계 기준은 [Kustomize](https://kubernetes.io/docs/tasks/manage-kubernetes-objects/kustomization/)와
[Palantir Architecture Center](https://www.palantir.com/docs/foundry/architecture-center/overview/)의 기능·서비스 책임 구분이다.
Teoria는 현재 도구·DB·메타데이터 권위를 유지하며 미구현 AI/AIP를 실행 구성에 추가하지 않는다.

외부 서비스의 커스텀 이미지 빌드 입력은 `deploy/image_builds/`에 둔다.
Teoria API·Worker는 `backend/Dockerfile`, UI는 `frontend/Dockerfile`에서 빌드한다.
MLflow 서버는 `deploy/image_builds/mlflow/Dockerfile`에서 빌드하며,
Prefect·MinIO 서버는 Kubernetes 정의에서 공식 이미지를 직접 사용한다.
빈 환경의 설치와 도메인 활성화는 [최초 설치 절차](bootstrap.md)를 따른다.

설정 등록 후 플랫폼·MLflow 배포는 입력 revision을 반영해 환경변수를 사용하는 Pod를 교체한다.
[변경별 반영 범위](../../deploy/kubernetes/envs/README.md#3-서비스에-반영)를 따른다.
