# EC2 단일 서버 K3s 배포

GitHub `main` push의 **CI 성공 후** 이미지를 GHCR에 저장하고 EC2에 SSH로 접속하여
K3s를 갱신한다. 현재 구현은 Linux **x86_64 EC2 1대**를 대상으로 한다. EC2 주소·도메인과
GitHub 설정은 운영자가 준비한다. 저장소 구성 검증과 실제 EC2 배포 성공은 구분한다.
현재 환경에서 실제 EC2 연결과 배포는 아직 수행하지 않았다.

## 실행 구성과 기준 파일

```text
GitHub main → CI → GHCR의 commit SHA 이미지 → EC2 SSH → deploy.sh
                                                        ↓
                                               K3s 단일 server
                                               ├─ Teoria API·UI·OPA
                                               ├─ PostgreSQL·Redis
                                               ├─ OpenMetadata·검색
                                               └─ Prefect·수집 Worker
```

| 목적 | 기준 파일 |
|---|---|
| EC2 K3s 설치 설정 | `deploy/k3s/server_config.yaml` |
| DB·캐시·검색·영속 볼륨 | `deploy/k3s/infrastructure/` |
| OpenMetadata Server | `deploy/k3s/openmetadata/` |
| API·UI·진단 Worker | `deploy/k3s/application/platform.yaml` |
| OPA와 정책 관리 | `deploy/k3s/application/policy.yaml` |
| Prefect와 수집 Worker | `deploy/k3s/application/prefect.yaml` |
| HTTPS와 요청 경로 | `deploy/k3s/application/ingress.yaml` |
| 순서가 있는 초기화·migration·등록 | `deploy/k3s/jobs/` |
| 배포 순서·대기·실패 처리 | `deploy/k3s/deploy.sh` |
| 환경별 인증정보의 키 목록 | `deploy/k3s/secrets.env.example` |
| 이미지 빌드·EC2 배포 | `.github/workflows/deploy_k3s.yaml` |

Kustomize는 `kubectl`에 포함된 기능만 사용한다. Helmfile이나 별도 GitOps 서버는 필요하지 않다.
MLflow·Argo CD·Harbor·GPU Operator·MinIO·S3는 이 초기 구성에 추가하지 않는다.
모델 진단은 외부 모델 gateway를 호출하며 기본적으로 비활성화한다.

## EC2 최초 준비

1. x86_64 Linux와 cgroup v2, K3s 요구 커널·네트워크를 준비한다. DB·검색·Prefect를
   함께 실행하므로 K3s 자체의 최소 사양을 전체 서비스 사양으로 사용하지 않는다.
   YAML의 CPU·메모리 요청과 실제 데이터 크기를 기준으로 EC2·EBS 용량을 정한다.
   기본 server 설정은 시스템·Kubernetes 용도로 합계 CPU 1개와 메모리 1Gi를 예약한다.
   워크로드에도 CPU·메모리 상한을 두며, 이 값은 실제 부하에 맞춰 조정한다.
2. 데이터 디렉터리를 영속 EBS에 두고, 운영 데이터 보존·snapshot 정책을 정한다.
   같은 EBS에 DB와 검색을 함께 두면 I/O를 공유한다. S3는 PostgreSQL의 데이터 디스크가 아니다.
3. `server_config.yaml`을 `/etc/rancher/k3s/config.yaml`에 설치한 뒤 버전을 고정해 K3s를 설치한다.

```bash
sudo install -d -m 700 /etc/rancher/k3s
sudo install -m 600 deploy/k3s/server_config.yaml /etc/rancher/k3s/config.yaml
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION='v1.37.1+k3s1' sh -s - server
sudo k3s kubectl get nodes
```

SSH 배포 계정에는 이 클러스터를 관리할 kubeconfig와 `kubectl`, Python 3, Bash,
`flock`, `tar`가 필요하다. 예를 들어 EC2의 전용 배포 계정에서 다음을 준비한다.
이 계정은 해당 클러스터를 관리하므로 접속키의 접근 권한을 운영 범위로 제한한다.

```bash
mkdir -p "$HOME/.kube"
sudo install -m 600 -o "$(id -u)" -g "$(id -g)" \
  /etc/rancher/k3s/k3s.yaml "$HOME/.kube/config"
# EC2 호스트에서만 사용하므로 kubeconfig의 127.0.0.1 주소를 유지한다.
export KUBECONFIG="$HOME/.kube/config"
kubectl get nodes
```

Security Group은 사용자 HTTPS, 관리 SSH와 노드 간 필요한 트래픽을 구분한다.
GitHub 호스티드 runner가 SSH에 접근할 경로를 준비한다. 그 경로가 없다면 배포 작업은
연결 단계에서 실패한다. Kubernetes API 6443은 GitHub runner에 공개할 필요가 없다.

## 인증정보와 최초 데이터

비밀값을 Git에 넣지 않는다. 예제 파일을 checkout 밖으로 복사해 `CHANGE_ME`와 URL을 채운다.
역할별 암호와 DSN의 암호는 같아야 하며, DSN 암호는 URL encoding한다.

```bash
kubectl create namespace teoria
cp deploy/k3s/secrets.env.example /secure/teoria-secrets.env
chmod 600 /secure/teoria-secrets.env
# 파일을 채운 다음 실행한다.
kubectl -n teoria create secret generic teoria-secrets \
  --from-env-file=/secure/teoria-secrets.env
kubectl -n teoria create secret docker-registry teoria-registry \
  --docker-server=ghcr.io --docker-username="$GHCR_USER" \
  --docker-password="$GHCR_READ_TOKEN"
kubectl -n teoria create secret tls teoria-tls \
  --cert=/secure/fullchain.pem --key=/secure/privkey.pem
```

`GHCR_READ_TOKEN`은 해당 저장소의 private package를 읽을 수 있는 credential이다.
이미지 빌드에 쓰는 GitHub Actions의 `GITHUB_TOKEN`을 EC2의 영구 pull credential로 쓰지 않는다.
운영 도메인의 DNS를 EC2로 연결하고 그 도메인에 맞는 TLS 인증서를 준비한다.
선택적 Provider key는 사용하는 연동에만 채운다.

빈 클러스터에서는 기존 DB와 **이미 게시된 Runtime bundle**을 한 번 이관해야 한다.
`deploy.sh`는 DB 초기화·migration과 OpenMetadata 기동 이후 artifact 확인에서 멈추므로
이 시점에 DB 복원과 최초 OpenMetadata 계정·ingestion bot 설정을 진행할 수 있다.
OpenMetadata 관리는 EC2에서 `kubectl port-forward service/openmetadata-server 8585:8585`
후 SSH tunnel을 통해 접속한다. bot JWT를 얻으면 Secret의
`OPENMETADATA_INGESTION_BOT_TOKEN`, `TEORIA_OPENMETADATA_AUTH_TOKEN`을 갱신한다.
JWT·연동 token이 바뀌면 해당 Pod를 재시작해 새 값을 읽게 한다. DB 암호 변경은
실제 PostgreSQL role 암호와 Secret을 함께 갱신하는 별도 운영 절차로 수행한다.

DB 복원은 운영과 분리한 대상으로 검증한 뒤 수행한다. 배포 스크립트는 데이터를
자동 복원하거나 기존 DB를 삭제하지 않는다. Runtime은 authoring YAML에서 자동 게시하지 않는다.
`active.json`과 그 파일이 지정한 version 디렉터리를 함께 가져온다. 복사 예시는 다음과 같다.

```bash
kubectl -n teoria run artifact-import --image=busybox:1.37 --restart=Never \
  --overrides='{"spec":{"containers":[{"name":"artifact-import","image":"busybox:1.37","command":["sleep","3600"],"volumeMounts":[{"name":"artifacts","mountPath":"/artifacts"}]}],"volumes":[{"name":"artifacts","persistentVolumeClaim":{"claimName":"runtime-artifacts"}}]}}'
kubectl -n teoria wait --for=condition=Ready pod/artifact-import --timeout=120s
# APPROVED_STORE와 VERSION은 이관할 게시 artifact로 지정한다.
tar -C "$APPROVED_STORE" -cf - active.json "$VERSION" | \
  kubectl -n teoria exec -i artifact-import -- tar -C /artifacts -xf -
kubectl -n teoria exec artifact-import -- chown -R 10001:10001 /artifacts
kubectl -n teoria delete pod artifact-import
```

그 후 동일 커밋의 workflow를 다시 실행한다. Runtime bundle checksum, 인증 API와
OpenMetadata 연결 검증까지 성공해야 배포 성공으로 기록한다. Registry·Ontology 변경은
별도 검토·게시하고 새 bundle을 명시적으로 이관해야 하며, 코드 push가 이를 대신하지 않는다.

## GitHub 설정과 자동 배포

GitHub Environment `production`을 만들고 다음을 설정한다. 자동 배포를 원하면
이 Environment에 수동 reviewer 승인을 필수로 설정하지 않는다.

| 종류 | 이름 | 값 |
|---|---|---|
| Variable | `EC2_HOST` | EC2 접속 주소 |
| Variable | `EC2_USER` | 전용 SSH 배포 사용자 |
| Variable | `EC2_SSH_PORT` | 기본 22 |
| Variable | `TEORIA_PUBLIC_HOST` | TLS 인증서와 일치하는 도메인 |
| Secret | `EC2_SSH_PRIVATE_KEY` | 배포 계정 접속용 키 |
| Secret | `EC2_SSH_KNOWN_HOSTS` | 사전에 확인한 EC2 SSH 호스트 키 |

저장소의 Actions 권한에서 GHCR package 쓰기를 허용한다. 현재 브랜치는 `main`이며,
변경하려면 workflow의 branch 조건과 최신 commit 확인을 함께 바꾼다.

- CI에서 K3s API 서버의 server dry-run으로 매니페스트를 검증한다.
- `CI`가 성공한 `main` push만 이미지 빌드·배포한다. PR·fork 실행 결과는 배포하지 않는다.
- 이미지 9종은 commit SHA tag로 저장한다. `latest`로 배포하지 않는다.
- EC2에는 Git에 커밋된 `deploy/k3s/`만 전달한다. 비밀값은 GitHub에서 전송하지 않고
  사전 생성된 클러스터 Secret을 사용하며 수집 namespace에 필요한 키만 동기화한다.
- GitHub concurrency와 EC2의 파일 lock으로 배포를 직렬화한다. 이미 더 최신 main이 있으면 과거 실행을 건너뛴다.
- Secret 사전 확인 → DB·검색 준비 → 계정 초기화 → SQL migration → OPA bundle → 게시 artifact 확인 → API·Worker 갱신 → Prefect 등록 → API 동작 확인 순서다.
- 실패 시 PVC와 Job 상태를 남기고 배포 실패로 종료한다. DB migration을 자동으로 되돌리거나 PVC를 삭제하지 않는다.

관리 작업은 저장된 커밋 디렉터리에서 같은 스크립트로 실행한다.

```bash
bash deploy/k3s/deploy.sh ghcr.io/owner/repository COMMIT_SHA teoria.example.com
```

API와 Worker는 단일 replica·Recreate 방식이므로 갱신 중 잠깐 중단될 수 있다.
진단 Worker를 사용하려면 Secret의 모델 설정을 채우고
`application/platform.yaml`의 `metadata-assessment-worker` replica를 1로 바꾼다.
OpenMetadata ingestion schedule과 retry는 Prefect가 소유하고 실제 실행은 한 번짜리
Kubernetes Job이다. Docker socket·Docker daemon·Airflow를 요구하지 않는다.

## 정해진 자원 안에서 파이프라인 병렬 실행

수집 Flow·Task와 `backend/prefect.yaml`은 Compose와 K3s가 함께 사용한다.
Compose는 기존 `teoria-ingestion` Process Worker 내부에서 실행한다. K3s는 등록 시
work pool만 `teoria-ingestion-k3s`로 바꾸고, Kubernetes Worker가 실행마다 별도 Job을 만든다.
Flow마다 Docker·Kubernetes 분기 코드를 넣지 않는다.

기본 정책은 다음과 같다. EC2의 사양과 서비스에 남길 자원을 고려해 배포 전에 조정한다.

| 설정 | 기본값 | 변경 위치 |
|---|---|---|
| 수집 전체 requests 예산 | CPU 2·메모리 4Gi | `deploy/k3s/execution/resource_quota.yaml` |
| 수집 전체 limits 예산 | CPU 4·메모리 8Gi | 같은 ResourceQuota |
| 작업당 requests | CPU 1·메모리 2Gi | 등록 Job의 `TEORIA_JOB_CPU_REQUEST`, `TEORIA_JOB_MEMORY_REQUEST` |
| 작업당 limits | CPU 2·메모리 4Gi | 등록 Job의 `TEORIA_JOB_CPU_LIMIT`, `TEORIA_JOB_MEMORY_LIMIT` |
| 수집 동시 실행 상한 | 2 | 등록 Job의 `TEORIA_PIPELINE_CONCURRENCY` |
| Backfill·보정 동시 실행 상한 | 1 | 등록 Job의 `TEORIA_PIPELINE_BACKFILL_CONCURRENCY` |

공통 등록 명령은 `teoria-pipelines register --backend kubernetes --kind all`이다.
작업당 기본값은 `backend/src/teoria/integrations/prefect/deployment.py`, 운영 override는
`deploy/k3s/jobs/prefect-register.yaml`의 환경변수로 관리한다. Prefect work pool의
base job template에 등록되며, Deployment의 `work_pool.job_variables`로 작업별 CPU·메모리를
다르게 지정할 수도 있다. 등록 Job이 원본 YAML을 임시 사본으로 변환하므로
Compose의 Deployment·스케줄·입력 파라미터는 바뀌지 않는다.

최신 수집은 `latest` Queue, Backfill·보정은 `backfill` Queue를 사용한다.
기본 동시 실행 상한 내에서 최대 2개 Job을 생성하되 Backfill·보정은 1개까지만 실행한다.
나머지는 Prefect에서 대기한다. 최신 수집을 먼저 선택하며 이미 실행 중인 작업을 선점하지 않는다.
같은 Deployment 중복 실행은 기존 `CANCEL_NEW` 정책이 먼저 적용된다.
Kubernetes는 requests와 실제 노드의 예약 가능한 자원을 기준으로 Pod를 배치하고,
CPU limit 초과 사용을 제한하며 메모리 limit 초과 시 프로세스가 종료될 수 있다.
Quota는 `teoria-pipelines` namespace에만 적용되므로 API·DB·Prefect Server 예산과 구분된다.
동시 실행 상한과 작업별 자원 합계가 Quota 안에 들어가도록 함께 조정한다.
Quota 초과는 admission 거부, 노드 용량 부족은 Pending을 유발할 수 있다. Pod 시작을
600초 기다린 뒤에도 실행되지 않으면 실패로 처리될 수 있으므로 무한 대기를 보장하지 않는다.

Job 종료 후 사용 자원은 반환되고 완료 Job은 1시간 뒤 정리된다. 실행 Dispatcher는 DB·Connector
자격증명을 받지 않으며 Job에만 필요한 Secret을 전달한다. 배포 스크립트는 `teoria`의 Secret에서
수집용 키와 registry 인증만 `teoria-pipelines`로 동기화하므로 Secret 회전 후 재배포한다.
Kubernetes Dispatcher 재시작은 별도 실행 중인 Job을 일괄 취소하지 않는다.
Compose 시작 시에는 Prefect가 종료를 확인한 실행의 미완료 DB 기록만 정리한다.
실행 중이거나 Prefect와 연결을 확인할 수 없는 기록은 자동 취소하지 않는다.

이는 실행 요청에 따라 제한된 범위에서 Job 수를 늘리고 줄이는 구조다. 단일 Flow의 연산을
자동 분산하거나 Worker replica·EC2 서버를 자동 증설하는 설정은 포함하지 않는다.
OpenMetadata ingestion은 별도 Metadata Worker가 관리하며 위 수집 namespace 예산에 포함하지 않는다.
실제 EC2의 병렬 실행·자원 포화 검증은 서버 준비 후 별도로 수행해야 한다.

기준: [Prefect Kubernetes Worker의 Job template](https://reference.prefect.io/prefect_kubernetes/worker/).

## 노드 증설과 영속 데이터

처음에는 nodeSelector나 taint를 강제하지 않아 server 노드에서 모든 CPU Pod가 실행된다.
나중에 CPU·GPU agent를 추가한 뒤 실제 필요한 workload에 affinity·GPU resource·toleration을 적용한다.
Prefect Server의 위치와 작업 실행 Worker의 위치는 독립적이다.

`local-path` PVC는 생성된 노드의 디스크에 묶인다. agent를 추가해도 DB·artifact가
자동으로 다른 노드로 이동하지 않는다. Stateful workload 이동과 디스크·DB 백업은
별도 계획이 필요하다. EC2 한 대 장애는 전체 서비스·Control Plane 장애다.
Control Plane HA는 CPU·GPU agent 추가와 별개의 datastore·server 구성 변경이다.

공식 기준: [K3s 설치](https://docs.k3s.io/quick-start),
[영속 스토리지](https://docs.k3s.io/add-ons/storage),
[GHCR 인증](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

기존 [scaffold 안내 주소](experimental_k3s.md)는 문서 링크 호환을 위해 새 안내를 가리킨다.
