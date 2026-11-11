# 로컬 k3d 실행

로컬 Kubernetes 통합 환경은 k3d, EC2 운영은 기존 K3s를 사용한다.
Compose는 기존 실행 경로로 유지한다. 공통 리소스·초기화 Job·Prefect 정책은
`deploy/kubernetes/`에서 공유하며 로컬 차이만 `overlays/k3d/`에 둔다.

## 준비와 클러스터 생성

Docker Engine, k3d v5.9 이상, kubectl, Bash, Python 3, OpenSSL, `flock`이 필요하다.
DB·검색·OpenMetadata·Prefect 전체를 실행하므로 k3d 자체의 최소 사양을 전체 서비스
요구량으로 간주하지 않는다. 기존 base의 CPU·메모리 요청을 수용할 Docker 자원을 준비한다.

저장소 루트에서 실행한다.

```bash
bash deploy/kubernetes/k3d/local.sh up
export KUBECONFIG="$PWD/deploy/kubernetes/k3d/.local/kubeconfig"
kubectl get nodes
```

전용 kubeconfig를 사용하므로 기존 운영 context를 변경하지 않는다. 클러스터 이름은
`teoria`, server 1대, agent 0대다. API는 `127.0.0.1:6550`, HTTPS는
`127.0.0.1:8443`, HTTP는 `127.0.0.1:8080`, 개발 이미지 Registry는
`127.0.0.1:5111`에 연결한다. 이미 사용 중인 포트가 있으면 생성 전에 해결한다.

기본 영속 경로는 **Docker 호스트의** `$HOME/.local/share/teoria/k3d`다.
`TEORIA_K3D_DATA_DIR`로 절대 경로를 지정할 수 있다. Devcontainer·원격 Docker에서는
현재 컨테이너 경로와 Docker 호스트 경로가 다를 수 있다. 클러스터 생성·이미지 push·브라우저
접속 명령은 Docker 호스트에서 실행하는 것을 기본으로 한다. Devcontainer에서 실행하려면
호스트 bind 경로와 loopback/API 접근을 별도로 연결해야 한다.

`cluster.yaml`은 K3s 이미지를 고정한다. 버전 변경은 클러스터·저장소 재검증과 함께 한다.
로컬 전용 kubelet 설정은 구형 cgroup v1 Docker 호스트에서도 기동을 허용한다.
운영 K3s의 cgroup v2 요구는 유지하며 로컬 호스트도 v2 전환을 권장한다.
로컬 TLS 키와 kubeconfig는 Git에서 제외한 `deploy/kubernetes/k3d/.local/`에 둔다.

## 인증정보와 최초 데이터

`up`은 로컬 인증서와 개발 Registry용 빈 pull 설정을 준비한다.
Admin·Runtime의 bearer 인증과 기존 승인·게시 경계는 그대로 사용한다.
플랫폼 Secret은 예시를 checkout 밖으로 복사해 채운다.

```bash
mkdir -p "$HOME/.config/teoria"
cp deploy/kubernetes/secrets.env.example "$HOME/.config/teoria/k3d_secrets.env"
chmod 600 "$HOME/.config/teoria/k3d_secrets.env"
# CHANGE_ME, 역할별 DSN, 법령 API key와 사용하는 연동 token을 실제 값으로 채운 후:
kubectl -n teoria create secret generic teoria-secrets \
  --from-env-file="$HOME/.config/teoria/k3d_secrets.env" \
  --dry-run=client -o yaml | kubectl apply -f -
```

DSN은 Kubernetes Service 이름을 사용한다. Compose 호스트·포트를 복사하지 않는다.
현재 Semantic 배포의 사전 검사는 법령 API key도 요구한다. 실제 값을 로그·Git에 기록하지 않는다.
최초 OpenMetadata 계정·bot과 이미 게시된 Runtime artifact의 이관은
[K3s 최초 데이터 절차](k3s.md#인증정보와-최초-데이터)를 동일하게 따른다.
빈 저장소에서 artifact 검사로 멈추는 것은 정상이며, authoring YAML을 자동 게시해 우회하지 않는다.

## 이미지와 배포

```bash
bash deploy/kubernetes/k3d/local.sh build
bash deploy/kubernetes/k3d/local.sh deploy --render > /tmp/teoria_k3d.yaml
bash deploy/kubernetes/k3d/local.sh deploy
```

`build`는 기존 Semantic 모듈이 쓰는 이미지 8개를 빌드해 `localhost:5111/teoria`에 push한다.
태그는 현재 Git commit SHA이며 배포도 같은 SHA를 사용한다. 수정 중인 checkout을 빌드하면
그 작업 내용이 포함되므로 운영 릴리스 이미지와 혼용하지 않는다.
명시적인 기존 태그를 사용할 때는 두 명령에 같은 `TEORIA_K3D_REVISION`을 설정한다.

노드는 `localhost:5111`을 Registry 컨테이너로 mirror한다. 따라서 배포 Pod뿐 아니라
나중에 생성되는 Prefect Job도 같은 주소의 이미지를 받을 수 있다.
이 공용 Registry에 플랫폼·모델 이미지를 함께 저장한다. MLOps는
`local.sh build --modules mlops`, `local.sh deploy --modules mlops`를 사용한다.
모델 실행 Secret·계정 준비는 [모델 실행](model_execution.md), 공용 Registry 연결은
[Registry 안내](image_registry.md)를 따른다. 별도 Registry 컨테이너는 추가하지 않는다.

브라우저에서 `https://teoria.localhost:8443/`에 접속한다. OS가 `.localhost`를 해석하지 않으면
호스트 파일에 `127.0.0.1 teoria.localhost`를 등록한다.
브라우저의 로컬 신뢰 저장소에는 `.local/tls.crt`를 등록한다. curl 검증 예시는 다음과 같다.

```bash
curl --cacert deploy/kubernetes/k3d/.local/tls.crt https://teoria.localhost:8443/health
```

Pod 안에서는 CoreDNS가 `teoria.localhost`를 Traefik Service로 연결한다.
배포 마지막의 API·TLS 검사는 이 경로와 로컬 인증서를 사용한다. 호스트의 8443 포트 접근은
위 curl과 브라우저에서 별도로 확인한다. TLS 검증을 비활성화하지 않는다.

## 데이터 보존과 재생성

```bash
bash deploy/kubernetes/k3d/local.sh stop
bash deploy/kubernetes/k3d/local.sh up
```

일상 작업은 stop/up을 사용한다. `teoria-local` StorageClass는 `Retain`과
`namespace/PVC이름/` 경로를 사용한다. 노드 storage와 Registry 본문은 호스트 bind에 보존한다.
클러스터를 명시적으로 삭제하고 같은 호스트 경로로 다시 생성해도 새 PVC는 같은 데이터 경로를 사용한다.
클러스터 삭제 전에는 DB를 정상 종료하고 별도 백업을 확보한다. 강제 삭제 뒤의 DB 복구는 별도 검증 대상이다.

재생성하면 Kubernetes Secret·게시 참조 설정 등 API 리소스는 다시 준비해야 한다.
`up` → 동일한 플랫폼 Secret 등록 → 같은 이미지 태그로 배포 순서를 따른다.
기존 Registry 컨테이너가 남아 있으면 `k3d registry delete k3d-teoria-images` 후 `up`한다.
이 명령은 Registry 컨테이너를 삭제하며 호스트 bind의 이미지 본문은 유지한다.
TLS 키도 기존 `.local/` 파일을 유지해야 브라우저 신뢰를 다시 설정할 필요가 없다.

같은 클러스터에서 PVC만 삭제하면 PV가 Released 상태로 남는다. 자동 재연결하지 않으므로
관련 워크로드를 중지하고 데이터를 확인한 뒤 PV 회수 절차를 수행한다.
기존 Compose DB·볼륨은 자동 이관하지 않는다. 물리 디렉터리를 공유하지 말고 별도 백업·복원한다.

이 스토리지는 단일 노드 로컬 개발용이며 용량 제한·복제·백업을 제공하지 않는다.
노드 수를 늘리는 경우 generic overlay와 실제 RWX 저장소를 선택한다.

## 검증 범위

```bash
uv run --project backend --locked --all-extras --group orchestration \
  pytest backend/tests/entrypoints/test_kubernetes_deployment.py -q
TEORIA_TEST_K3D=1 uv run --project backend --locked --all-extras --group orchestration \
  pytest backend/tests/integration/test_k3d_local_cluster.py -q
```

두 번째 검사는 별도 이름의 실제 클러스터·Registry를 생성해 이미지 pull, PVC 쓰기,
로컬 DNS·인증서를 검증하는 HTTPS 서비스 응답, 클러스터와 Registry 재생성 후 데이터 재접속을
확인하고 테스트 리소스를 정리한다. 테스트용 `busybox:1.36`과 `python:3.12-slim`은 없으면 pull한다.
2026-11-11 검증: 배포·문서 단위 검사 25개, 실제 k3d 통합 검사 1개 통과.
같은 환경에서 Compose 설정 검사와 문서 링크 검사도 통과했다. 테스트 클러스터·Registry는 정리했다.
전체 서비스 배포에는 위 Secret·게시 artifact·외부 연동 준비가 필요하다.
현재 Kubernetes Semantic 구성에는 Compose의 규격서 객체 저장소·처리 배포 전체가 연결돼 있지 않다.
k3d 추가를 규격서 처리 전체 흐름이나 운영 배포 검증 완료로 기록하지 않는다.

공식 근거: [k3d 설정](https://k3d.io/stable/usage/configfile/),
[Registry mirror](https://k3d.io/stable/usage/registries/),
[스토리지와 네트워크](https://k3d.io/stable/usage/k3s/),
[Local Path Provisioner](https://github.com/rancher/local-path-provisioner#storage-classes).
[Palantir Architecture Center](https://www.palantir.com/docs/foundry/architecture-center/overview/)의
플랫폼 기능과 배포 기반 구분을 참고한다. Teoria는 로컬 클러스터 설정만 추가하며
Prefect·DB·객체 저장소·Ontology의 소유권을 변경하지 않는다.
