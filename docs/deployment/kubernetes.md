# 일반 Kubernetes·K3s·k3d 배포

Kubernetes 공통 리소스는 `deploy/kubernetes/base/`, 환경 차이는 `overlays/`가 소유한다.
학습 Job·모델별 서빙 Deployment·Service·RBAC는 두 환경에서 같은 계약을 사용한다.
실제 노드 배치·스토리지·Ingress 동작은 해당 클러스터에서 검증해야 하며 템플릿·API 스키마 검사를 운영 성공으로 간주하지 않는다.

## 구조와 선택

```text
deploy/kubernetes/
  deploy.sh                  공통 배포 순서·렌더링·대기·검증
  base/                      공통 API·DB·Prefect·모델 실행·초기화 Job
  prefect/                   공통 Kubernetes pool·queue·Job 실행 정책
  components/web_proxy/      기존 UI nginx의 API 경로 전달·MLflow 인증
  secrets.env.example        플랫폼 Secret 키 예시
  overlays/
    generic/                 표준 Ingress·클러스터 스토리지 설정
    k3s/                     Traefik·local-path·EC2/K3s 노드 설치 설정
    k3d/                     로컬 Traefik·인증서·보존 스토리지 선택
  k3d/                       로컬 클러스터·Registry·수명주기 명령
```

`--modules mlops`는 모델 운영 단독, `--modules semantic`은 기존 Metadata·Ontology·업무 기능 구성을 선택한다.
로컬 환경의 생성·빌드·Secret·데이터 보존 절차는 [k3d 안내](k3d.md)를 따른다.
두 모듈을 한 번에 합치는 K3s/Kubernetes 설치는 현재 지원하지 않는다. Compose의 모듈 조합과 구분한다.
기존 Semantic 설치 위에 MLOps 단독 구성을 덮어쓰지 않도록 배포 스크립트가 검사한다.

| 항목 | generic | k3s |
|---|---|---|
| API·UI·학습·서빙 리소스 | 공통 base | 같은 base |
| 외부 진입 | 표준 Ingress, 경로 보존 | Semantic은 Traefik prefix, MLOps는 UI 프록시 |
| UI·API 연결 | 기존 UI nginx가 프록시도 수행 | Semantic은 Traefik, MLOps는 UI nginx |
| MLflow 외부 인증 | Prefect 운영 계정으로 nginx 인증 | Prefect 운영 계정으로 nginx 인증 |
| 기본 PVC StorageClass | 클러스터 기본값 또는 지정값 | `local-path` 또는 지정값 |
| CI 접근 | 배포 에이전트의 kubectl context | 기존 EC2 SSH workflow 유지 |

일반 구성에 프록시 전용 상시 컨테이너를 추가하지 않는다. 기존 `admin-ui` 컨테이너에 ConfigMap을 mount하여
`/admin-api/`, `/runtime-api/`, `/prefect/`, `/mlflow/`를 내부 Service로 전달한다.
이미지 Registry는 별도 기존 서비스를 사용하며 플랫폼 Ingress에 `/v2/`를 추가하지 않는다.

## 배포 전에

배포 명령은 클러스터 노드가 아닌 Linux 배포 에이전트·개발 PC·CI에서 실행할 수 있다.
Bash·Python 3·`flock`·Kustomize Component를 지원하는 kubectl과 리소스 생성·검증 권한이 필요하다.
`KUBECONFIG`와 선택된 context를 사용하며 EC2·SSH·클라우드 API를 요구하지 않는다.

1. `kubectl config current-context`와 `kubectl get nodes`로 대상 클러스터를 확인한다.
2. Ingress controller와 IngressClass를 준비한다. generic은 controller 전용 rewrite annotation이나 CRD를 요구하지 않는다.
3. 플랫폼 TLS 종료는 Ingress controller에서 수행한다. 플랫폼 DNS와 인증서를 준비하고 외부 Registry의 연결·인증은 별도로 설정한다.
4. 기본 StorageClass 또는 `--storage-class`로 지정할 CSI 저장소를 준비한다.
5. 노드 아키텍처에 맞는 플랫폼·모델 이미지를 기존 외부 Registry에서 준비하고 플랫폼·실행 namespace에 pull 인증을 설정한다.
6. Secret·DB 계정·게시 artifact 등 모듈별 준비를 완료한다.

namespace는 기존 식별자를 유지한다. 플랫폼은 `teoria`, 수집 Job은 `teoria-pipelines`, 모델 실행은 `teoria-models`다.
이미 존재하는 DB·PVC·게시 artifact를 삭제하거나 namespace를 자동 이관하지 않는다.

인증정보의 키 목록은 `deploy/kubernetes/secrets.env.example`이 소유한다. 예시를 checkout 밖 보안 파일로 복사한다.
모델 전용 Secret 템플릿은 `deploy/kubernetes/control.env.example`, `workload.env.example`이다.
모델 계정·입출력·이미지 준비는 [모델 실행 안내](model_execution.md)와 [Registry 안내](image_registry.md)를 따른다.

## MLOps 일반 클러스터 실행

먼저 파일만 렌더링해 검토한다. `--render`는 클러스터 접속·Secret 조회·배포를 수행하지 않는다.
실제 Secret 값을 출력하지 않으며 참조만 포함한다. 커밋 SHA·DNS·이미지 prefix는 실제 값으로 바꾼다.

```bash
bash deploy/kubernetes/deploy.sh ghcr.io/org/teoria <commit_sha> teoria.example.com \
  --overlay generic --modules mlops \
  --model-registry-host registry.example.com \
  --storage-class cluster-csi --ingress-class public --render > /tmp/teoria_mlops.yaml
```

준비된 context와 Secret으로 같은 명령의 `--render`를 제거하면 배포한다.
초기화 Job과 migration을 순서대로 실행하고 공통 학습·서빙 Flow를 등록한 뒤 연결을 확인한다.

```bash
bash deploy/kubernetes/deploy.sh ghcr.io/org/teoria <commit_sha> teoria.example.com \
  --overlay generic --modules mlops \
  --model-registry-host registry.example.com \
  --storage-class cluster-csi --ingress-class public
```

`--storage-class`, `--ingress-class`를 생략하면 generic은 클러스터 기본 설정을 사용한다.
DNS domain이 `cluster.local`이 아니면 `--cluster-domain corp.internal`을 추가한다.
UI 프록시는 Pod의 `/etc/resolv.conf`에서 DNS resolver를 읽고 지정된 cluster domain으로 Service를 조회한다.
Prefect와 모델 실행 클라이언트는 배포판 전용 hostname 대신 Kubernetes Service DNS를 사용한다.

Ingress에는 원래 요청 경로를 보존하도록 설정한다. 이미 설치한 controller의 전역 rewrite·인증 설정은
이 구성과 충돌하지 않는지 확인한다. 모든 일반 Ingress 구현·스토리지 제품의 동작을 검증한 것은 아니다.

## Semantic 공유 저장소

Runtime API와 Admin API가 함께 읽는 `runtime-artifacts`, 정책 Job과 서비스가 공유하는
`opa-signing-keys`·`opa-bundles`는 서로 다른 노드에서도 접근 가능해야 한다.
따라서 generic Semantic 배포는 RWX를 지원하는 `--shared-storage-class`를 명시해야 한다.
이 세 PVC만 `ReadWriteMany`로 렌더링하고 DB·캐시 등 전용 볼륨은 `ReadWriteOnce`를 유지한다.

```bash
bash deploy/kubernetes/deploy.sh ghcr.io/org/teoria <commit_sha> teoria.example.com \
  --modules semantic --overlay generic \
  --storage-class cluster-block-csi --shared-storage-class cluster-filesystem-csi \
  --ingress-class public --render > /tmp/teoria_semantic.yaml
```

StorageClass 이름만 지정한다고 RWX·복제·고가용성이 제공되는 것은 아니다. 저장소 관리자가 실제 기능과 접근 권한을 확인해야 한다.
이미 Bound 상태인 PVC의 class·access mode 변경을 데이터 이관 방법으로 사용하지 않는다. 새 PVC·백업·복원과
별도 전환 계획을 준비한다. 배포 스크립트는 기존 PVC를 삭제하거나 데이터를 복제하지 않는다.
K3s 기본은 기존 RWO `local-path`를 보존하므로 단일 노드 배치 전제를 그대로 갖는다.
여러 노드의 K3s에서도 공유 저장소가 필요하면 `--shared-storage-class`로 RWX class를 명시한다.

## K3s 선택과 자동 배포

K3s도 공통 진입점에 `--overlay k3s`를 지정한다.

```bash
bash deploy/kubernetes/deploy.sh ghcr.io/org/teoria <commit_sha> teoria.example.com --overlay k3s
bash deploy/kubernetes/deploy.sh ghcr.io/org/teoria <commit_sha> teoria.example.com \
  --overlay k3s --modules mlops --model-registry-host registry.example.com
```

EC2/K3s 설치 설정은 `deploy/kubernetes/overlays/k3s/server_config.yaml`에 둔다.
기존 별도 배포 폴더와 호환 진입점은 제거했다. 운영자의 기존 스크립트도 위 공통 명령으로 갱신한다.
Job YAML은 `deploy/kubernetes/base/jobs/`, 플랫폼 Secret 예시는 `deploy/kubernetes/secrets.env.example`이 기준이다.
리소스 이름·namespace·PVC 이름·Secret 키·공개 경로는 유지한다.

`.github/workflows/deploy_k3s.yaml`은 EC2 접속 전용이며 릴리스에 `deploy/kubernetes/`만 전달한다.
원격에서도 공통 배포 명령에 `--overlay k3s`를 전달한다. 일반 클러스터는 조직의 CI·배포 에이전트에서
kubeconfig를 안전하게 준비하고 같은 진입점에 `--overlay generic`을 지정한다.

## 검증 범위와 근거

```bash
uv run --project backend --locked --all-extras --group orchestration pytest backend/tests/entrypoints/test_kubernetes_deployment.py
TEORIA_TEST_KUBERNETES_API_DOCKER=1 uv run --project backend --locked --all-extras --group orchestration --group docker-orchestration pytest backend/tests/integration/test_kubernetes_manifests_docker.py -q
TEORIA_TEST_KUBERNETES_PROXY_DOCKER=1 uv run --project backend --locked --all-extras --group orchestration --group docker-orchestration pytest backend/tests/integration/test_kubernetes_proxy_docker.py -q
```

오프라인 검사는 generic·K3s 렌더링, class·DNS 치환, K3s 라우팅과 공유 볼륨의 보존을 검증한다.
API 검사는 Traefik CRD를 추가하지 않은 격리 K3s API 서버에 generic 리소스를 server dry-run하며
실제 Pod 스케줄링·Ingress controller·CSI 동작·운영 배포를 검증하지 않는다.
실컨테이너 프록시 검사는 API 경로·토큰 전달·Prefect 경로·MLflow 미인증 거절을 확인한다.
프록시 테스트의 HTTP client 이미지는 `TEORIA_KUBERNETES_PROXY_CLIENT_IMAGE`로 지정한다.
`backend/Dockerfile`의 `admin` target으로 빌드한 이미지를 사용하고 `nginx:1.27-alpine`도 미리 준비한다.
CI는 generic server dry-run과 실제 프록시 인증·라우팅 검사를 함께 실행한다.

배포 구조는 [Kubernetes Kustomize](https://kubernetes.io/docs/tasks/manage-kubernetes-objects/kustomization/)의 base·overlay와
[StorageClass](https://kubernetes.io/docs/concepts/storage/storage-classes/)의 환경별 저장소 선택을 따른다.
[Palantir Architecture Center](https://www.palantir.com/docs/foundry/architecture-center/overview/)의 플랫폼 기능과 배포 기반 분리를 참고하되,
Teoria는 기존 Prefect·DB·객체 저장소의 권위를 유지하고 별도 배포 엔진이나 의미 Registry를 추가하지 않는다.
