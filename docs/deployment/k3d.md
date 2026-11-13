# 로컬 k3d 실행

로컬 Kubernetes 통합 환경은 k3d, EC2 운영은 기존 K3s를 사용한다.
공통 리소스·초기화 Job·Prefect 정책은
`deploy/kubernetes/`에서 공유하며 로컬 차이만 `overlays/k3d/`에 둔다.

Metadata·Ontology·MLOps는 [통합 Teoria 배포](kubernetes.md)를 따른다. 도메인 실행은 운영 설정으로 분리한다.

## 준비와 클러스터 생성

Docker Engine와 로컬 빌드용 Buildx, k3d v5.9 이상, kubectl, Helm, Bash, Python 3, OpenSSL, `flock`이 필요하다.
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
`127.0.0.1:8443`, HTTP는 `127.0.0.1:8080`, Harbor는 `127.0.0.1:443`에 연결한다. 이미 사용 중인 포트가 있으면 생성 전에 해결한다.
플랫폼 포트는 `TEORIA_K3D_HTTP_PORT`·`TEORIA_K3D_HTTPS_PORT`로 바꿀 수 있다.
Devcontainer가 Docker 네트워크에 연결돼 있으면 `TEORIA_K3D_API_SERVER=https://k3d-teoria-server-0:6443`으로
전용 kubeconfig의 API 주소를 지정할 수 있다. TLS 검증은 유지한다.

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

`up`은 플랫폼·Harbor 로컬 인증서와 노드 DNS·CA를 준비한다.
Harbor 설치·프로젝트·조회/pull 계정은 [Registry 안내](image_registry.md)에 따라 별도로 준비한다.
Admin·Runtime의 bearer 인증과 기존 승인·게시 경계는 그대로 사용한다.
플랫폼 Secret은 [envs/dev](../../deploy/kubernetes/envs/README.md)의 역할별 파일에서 준비한다.

```bash
export KUBECONFIG="${TEORIA_K3D_KUBECONFIG:-deploy/kubernetes/k3d/.local/kubeconfig}"
bash deploy/kubernetes/envs/settings.sh init --env dev
# connections.env의 주소·실행 설정과 secrets.env의 인증정보를 채운 후:
bash deploy/kubernetes/envs/settings.sh apply --env dev --context k3d-teoria --role connections
bash deploy/kubernetes/envs/settings.sh apply --env dev --context k3d-teoria --role platform
```

DSN은 Kubernetes Service 이름을 사용한다. Compose 호스트·포트를 복사하지 않는다.
법령 API key는 법령 수집을 활성화할 때만 요구한다. 실제 값을 로그·Git에 기록하지 않는다.
최초 OpenMetadata 계정·bot과 이미 게시된 Runtime artifact의 이관은
[K3s 최초 데이터 절차](k3s.md#인증정보와-최초-데이터)를 동일하게 따른다.
빈 저장소에서 artifact 검사로 멈추는 것은 정상이며, authoring YAML을 자동 게시해 우회하지 않는다.

## 이미지와 배포

일상 명령의 흐름은 `up` → `render ` → `deploy ` → `status`다.
[배포 시작 안내](../../deploy/README.md)의 일상 명령을 참고한다.

플랫폼·모델 이미지는 독립 설치한 Harbor를 사용한다. 먼저
[Harbor 설치·CA·인증·이미지 반입](image_registry.md)을 완료한다.
`build`는 Docker Buildx/BuildKit이 필요하다. 선택 사항이며 폐쇄망에서는 외부에서 만든 이미지를 직접 Harbor에 push한다.
통합 플랫폼 이미지는 `local.sh build `로 준비한다. 최초 설치는
`local.sh deploy --component all`, 이후 Teoria만 갱신할 때는
`local.sh deploy --component platform`을 사용한다.
`database`·`storage`·`workflow`·`mlflow`도 독립적으로 선택할 수 있다.
[서비스별 책임과 연결 설정](kubernetes.md#명령과-실행-순서)을 따른다.
모델 실행 Secret·계정 준비는 [모델 실행](model_execution.md)을 따른다.

```bash
bash deploy/kubernetes/k3d/local.sh build
bash deploy/kubernetes/k3d/local.sh render > /tmp/teoria_k3d.yaml
bash deploy/kubernetes/k3d/local.sh deploy
```

`build`는 통합 플랫폼과 역할별 실행 이미지 12개를 빌드해 `harbor.teoria.localhost/teoria`에 push한다.
태그는 현재 Git commit SHA이며 배포도 같은 SHA를 사용한다. 수정 중인 checkout을 빌드하면
그 작업 내용이 포함되므로 운영 릴리스 이미지와 혼용하지 않는다.
명시적인 기존 태그를 사용할 때는 두 명령에 같은 `TEORIA_K3D_REVISION`을 설정한다.

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
`namespace/PVC이름/` 경로를 사용한다. 노드 storage와 Harbor PVC 본문은 호스트 bind에 보존한다.
클러스터를 명시적으로 삭제하고 같은 호스트 경로로 다시 생성해도 새 PVC는 같은 데이터 경로를 사용한다.
클러스터 삭제 전에는 DB를 정상 종료하고 별도 백업을 확보한다. 강제 삭제 뒤의 DB 복구는 별도 검증 대상이다.

재생성하면 Kubernetes Secret·게시 참조 설정 등 API 리소스는 다시 준비해야 한다.
`up` → Harbor 복구 → 동일한 플랫폼 Secret 등록 → 같은 이미지 태그로 배포 순서를 따른다.
Harbor도 같은 chart·private values·Secret으로 재설치하고 기존 PVC 데이터를 확인한다.
이전 개발 Registry에서 전환할 때는 [전환 절차](image_registry.md#기존-구성에서-전환)를 먼저 따른다.
TLS 키도 기존 `.local/` 파일을 유지해야 브라우저 신뢰를 다시 설정할 필요가 없다.

같은 클러스터에서 PVC만 삭제하면 PV가 Released 상태로 남는다. 자동 재연결하지 않으므로
관련 워크로드를 중지하고 데이터를 확인한 뒤 PV 회수 절차를 수행한다.
기존 Compose DB·볼륨은 자동 이관하지 않는다. 물리 디렉터리를 공유하지 말고 별도 백업·복원한다.

이 스토리지는 단일 노드 로컬 개발용이며 용량 제한·복제·백업을 제공하지 않는다.
노드 수를 늘리는 경우 generic overlay와 실제 RWX 저장소를 선택한다.

## 원격 IP 접속

도메인이 없는 원격 개발에서는 독립 진입 프록시를 추가해 다음처럼 구분한다.

| 대상 | 외부 HTTPS |
|---|---|
| Teoria | `https://서버IP:18443` |
| Harbor | `https://서버IP:18444` |

설정 기준은 `deploy/kubernetes/k3d/.local/remote_access.env`다.
기존 클러스터·Harbor·Teoria가 실행 중인 개발 환경에 IP 접속을 추가할 때 사용한다.
빈 환경은 [최초 설치](bootstrap.md)를 먼저 완료한다.

```bash
# 최초 준비: 예시의 IP를 Docker 호스트의 실제 IPv4 주소로 바꾼다.
cp deploy/kubernetes/k3d/remote_access.env.example deploy/kubernetes/k3d/.local/remote_access.env
# 파일 내용:
# TEORIA_K3D_ADDRESS=SERVER_IP
# TEORIA_K3D_PLATFORM_PORT=18443
# TEORIA_K3D_HARBOR_PORT=18444

# 변경할 주소·포트·영향 확인. 클러스터 접속이나 파일/컨테이너 변경 없이 실행한다.
bash deploy/kubernetes/k3d/remote_access.sh --check
# 실행 중인 개발 환경에 명시적으로 적용한다.
bash deploy/kubernetes/k3d/remote_access.sh --apply
# 적용 후 TLS·인증·운영 화면·Registry 연결을 읽기 전용으로 확인한다.
bash deploy/kubernetes/k3d/remote_access.sh --verify
```

`--check`는 Bash·Python 표준 라이브러리만 사용하며 uv 의존성 동기화도 실행하지 않는다.
`--address`·`--platform-port`·`--harbor-port`는 파일 값의 명시적 override다.
`--config /secure/remote_access.env`로 별도 입력을 검토할 수도 있다.
적용 성공 시 실제 값을 기본 env 파일에 기록하고 `remote_access/config.json`에 완료 상태를 남긴다.
예전 `config.json`만 있는 환경은 해당 값을 읽으며, 다음 성공한 적용에서 env 파일로 이관한다.
기존 옵션만 전달하는 명령은 이제 검토 결과만 출력한다. 실제 변경에는 `--apply`가 필요하다.
쉘 환경변수로 숨겨진 기본값을 덮어쓰지 않으며 env 파일은 코드로 실행하지 않는다.

`local.sh build/deploy/render`, 공통 `deploy.sh --overlay k3d`, 일반 Harbor 갱신은 같은 적용 완료 주소를 사용한다.
입력과 완료 기록이 다르거나 복구가 남아 있으면 일반 배포를 중단한다.
`deploy.sh --render`에 Registry 주소를 명시하면 다른 주소의 YAML을 미리 볼 수 있지만 실제 배포에는 이 예외가 없다.
운영 k3s·generic overlay는 이 k3d 전용 설정을 읽지 않는다.

원격 Nginx 설정은 `remote_access.conf.template`, 입력 예시는 `remote_access.env.example`,
실행 코드는 `backend/src/teoria/entrypoints/k3d_remote_access.py`가 소유한다.
별도 Dockerfile 없이 준비된 `nginx:1.27-alpine` 이미지를 사용한다.
Docker·OpenSSL·Helm·kubectl·uv, 기존 개발 CA·키·고정 Harbor chart와 플랫폼/모델 Secret이 필요하다.
Nginx·보조 `busybox:1.36` 이미지는 Docker 호스트에 미리 준비한다. 사전 검사에서 이미지를 내려받지 않는다.

## 원격 접속 변경과 복구

적용은 일반 플랫폼 배포와 같은 잠금을 사용하며 다음 순서로 진행한다.

1. 전용 context·실행 중인 노드/로드밸런서·프록시 소유권·호스트 포트 충돌·인증서·필수 Secret을 검사한다.
2. 새 인증서·Nginx·Harbor 값을 별도 디렉터리에 준비하고 인증서 검증·chart 렌더링·`nginx -t`를 수행한다.
3. 변경 대상의 이전 값과 진행 기록을 비공개 transaction 파일에 저장한다.
4. Harbor 주소/IP Ingress·Registry CA·선택한 Secret 키·Admin 연결을 갱신한다.
5. 기존 프록시를 정지해 보관하고 새 프록시를 시작한다. 기존 컨테이너를 먼저 삭제하지 않는다.
6. 외부 HTTPS와 인증을 확인한 뒤 완료 기록을 갱신하고 보관한 이전 컨테이너를 제거한다.

단일 프록시 교체와 관련 Pod 갱신 중에는 짧은 접속 중단이 발생할 수 있다.
진행 중인 학습·배포를 먼저 확인한다. PVC·DB·게시 artifact와 기존 플랫폼 이미지 참조는 변경하지 않는다.
오류가 나면 이번에 변경한 값과 기존 컨테이너를 복구한다. 관계없는 Secret 키·Registry 설정은 보존한다.
다른 작업이 같은 값을 변경했거나 일부 복구가 실패하면 덮어쓰지 않고 복구 기록을 남긴다.
강제 종료 등으로 중단된 작업도 클러스터가 실행 중인 상태에서 다음 명령으로 복구한다.

```bash
bash deploy/kubernetes/k3d/remote_access.sh --recover
```

`.local/remote_access/pending.json`과 해당 release의 `transaction.json`이 복구 기준이다.
진행 중 기록에는 이전 Secret 값이 포함되므로 Git·이미지에 넣거나 외부에 공유하지 않는다.
파일은 제한된 권한으로 기록하며 성공적으로 완료/복구하면 transaction의 Secret 본문을 제거한다.
충돌이 남으면 `.local/remote_access/last_error.log`와 실제 리소스를 확인한 후 복구한다.
작업 기록을 삭제해서 미완료 상태를 우회하지 않는다.

`--verify`는 인증서 검증, Admin 미인증 차단·인증 성공, 플랫폼의 Registry 목록 조회,
Prefect·MLflow 접근, Harbor health와 Registry 인증 challenge의 공개 주소를 검사한다.
이미지 push나 모델 실행은 하지 않는다. 실제 Harbor의 업로드·다운로드와 운영 용량은 별도 검증한다.

## 원격 클라이언트 접속

프록시는 지정한 IP에만 바인딩하고 내부 Traefik 연결의 인증서도 검증한다.
Docker 호스트 방화벽·클라우드 보안 그룹에서 해당 IP의 TCP 18443·18444를 허용한다.
Windows에서는 `.local/remote_access/tls/ca.crt`를 현재 사용자의 **신뢰할 수 있는 루트 인증 기관**에
등록한 뒤 위 IP 주소로 접속한다. hosts 수정·SSH 터널은 필요 없다.
Docker client의 CA 신뢰는 해당 Docker 실행 환경에도 설정해야 한다.
적용 코드는 Docker 호스트의 `/etc/docker/certs.d/서버IP:18444/ca.crt`를 준비한다.

`local.sh stop/up`은 관리하는 외부 프록시도 중지·시작하고 적용 완료된 Registry 설정을 복원한다.
미완료 접속 변경이 있으면 먼저 `--recover`로 처리해야 한다.
클러스터를 재생성한 경우 보존한 인증·데이터를 복원하고 IP 접속 설정을 다시 적용한다.
운영 k3s·일반 Kubernetes에서는 서비스별 DNS 이름과 Ingress 443을 사용한다.
폐쇄망에서는 내부 DNS와 조직 CA를 사용할 수 있다.

[k3d 공식 Ingress 노출 방식](https://k3d.io/stable/usage/exposing_services/)을 기본으로 삼으며,
추가 외부 프록시는 IP 접속을 위한 개발 전용 구성이다.
시간 제한·버퍼링은 [Nginx proxy 설정](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)을 따른다.
공통 UI 프록시도 Admin·Runtime·Prefect 이벤트 연결에 맞춰 대기 시간을 별도로 지정한다.

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
2026-11-11 검증: 배포·문서 단위 검사 25개, 기존 개발 Registry 기반 실제 k3d 통합 검사 1개 통과.
같은 환경에서 Compose 설정 검사와 문서 링크 검사도 통과했다. 테스트 클러스터·Registry는 정리했다.
이 기록은 Harbor 설치 검증을 뜻하지 않는다. 개발 Harbor·MLOps의 후속 실제 검증은 [Harbor 검증 기록](harbor_validation.md)을 따른다.
전체 서비스 배포에는 위 Secret·게시 artifact·외부 연동 준비가 필요하다.
규격서 처리의 객체 저장소·소유 API·모델 인증은 도메인 실행 전에 별도로 준비한다.
k3d 추가를 규격서 처리 전체 흐름이나 운영 배포 검증 완료로 기록하지 않는다.

공식 근거: [k3d 설정](https://k3d.io/stable/usage/configfile/),
[Registry mirror](https://k3d.io/stable/usage/registries/),
[스토리지와 네트워크](https://k3d.io/stable/usage/k3s/),
[Local Path Provisioner](https://github.com/rancher/local-path-provisioner#storage-classes).
[Palantir Architecture Center](https://www.palantir.com/docs/foundry/architecture-center/overview/)의
플랫폼 기능과 배포 기반 구분을 참고한다. Teoria는 로컬 클러스터 설정만 추가하며
Prefect·DB·객체 저장소·Ontology의 소유권을 변경하지 않는다.

## `.local`의 역할과 기존 파일 정리

`.local`은 Kubernetes나 k3d가 정한 표준 폴더가 아니다. Teoria의 `local.sh up`과
`remote_access.sh`가 개발 호스트에서 생성·보관할 파일의 위치로 정했다. Git·이미지 빌드에서 제외한다.
스토리지 본문은 이 폴더가 아니라 Docker 호스트의 `TEORIA_K3D_DATA_DIR/storage`에 있다.

| 위치 | 내용 |
|---|---|
| `envs/dev/*.env`, `harbor_values.yaml` | 운영자가 관리하는 서비스·인증·Harbor 입력 |
| `envs/dev/k3d.env` | 선택 입력: 호스트 경로·포트·API 주소·이미지 revision; `local.sh`가 자동으로 읽음 |
| `k3d/.local/kubeconfig`, `*.crt`, `*.key`, `node_hosts` | 재사용할 접속·인증서·노드 설정 파일 |
| `k3d/.local/remote_access.env` | 원격 IP 접속 입력 |
| `k3d/.local/remote_access/`, `access.json`, `docker/` | 적용·복구 상태, 프록시 설정·인증서, 로컬 Docker 로그인 상태 |
| `k3d/.local/cache/charts/`, `cache/images/` | 반입한 chart와 이미지 archive cache |
| `.artifacts/k3d_legacy/<UTC 시각>/` | 이전 설치 스크립트·로그·보고서·원본 인증정보의 비공개 백업 |

기존 개발 설치의 `credentials.json`·`session.env`와 일회성 스크립트를 정리할 때:

```bash
uv run --project backend --locked --extra api python -m teoria.entrypoints.k3d_local_state migrate --root "$PWD"
# 위 결과를 확인한 후 로컬 파일만 이관:
uv run --project backend --locked --extra api python -m teoria.entrypoints.k3d_local_state migrate --root "$PWD" --apply
```

기존에 채운 env 값은 유지하고 알려진 구형 키만 옮긴다. 원본과 덮어쓰기 전 입력은 700/600 권한으로 백업한다.
없는 새 인증정보는 `CHANGE_ME`로 남기므로 사용 전에 채워야 한다. 이전 스크립트는 실행하지 않는다.
클러스터·컨테이너·PVC·실제 저장소 데이터에는 접근하지 않으며 Secret 등록·배포도 별도 절차다.
인증서와 프록시 mount 경로는 유지한다. 기존 `session.env`의 포트·경로는 `k3d.env`로 보존한다.
