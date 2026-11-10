# 컨테이너 이미지 Registry

플랫폼·학습·서빙 이미지는 같은 Distribution Registry의 서로 다른 repository에 보관할 수 있다.
이미지 저장소는 MLflow Model Registry와 구분한다. MinIO는 기존 데이터·모델 산출물을 보관하고,
이 구성의 이미지 파일은 Registry의 영구 볼륨에 보관한다.

Registry는 선택형 독립 기반 서비스다. 이미 운영 중인 Registry가 있으면 설치를 생략하고 연결한다.
Teoria `deploy.sh stop/down`은 Registry를 중지하지 않는다. 아직 설정되지 않은 환경에서는
Admin의 **공통 운영 → 컨테이너 이미지** 화면에 연결 안내를 표시한다.

## 설치 전에

Docker 서버·Kubernetes 노드·빌드 실행 환경에서 접근 가능한 Registry DNS와 TLS 인증서를 준비한다.
자체 CA를 사용하면 Docker daemon·K3s containerd·Admin API의 HTTP client에도 CA를 신뢰시키며,
TLS 검증을 끄는 옵션으로 대체하지 않는다. Registry 자체 이미지는 공개 배포처에서 먼저 받아
플랫폼 이미지를 다운로드해야 Registry가 시작되는 순환 의존성을 만들지 않는다.

현재 기본은 Distribution 3.1.2, 단일 인스턴스, 파일시스템 저장이다.
K3s의 `local-path` PVC는 현재 단일 EC2용이며 노드 장애 시 다른 노드로 자동 복제되는 저장소가 아니다.
노드 확장·가용성 요구가 생기면 재연결 가능한 저장소 또는 별도 Registry 서비스를 검토한다.

인증 파일과 인증서·키는 checkout 밖에 둔다. 예를 들어 운영자의 보안 경로를 준비한 뒤:

```bash
mkdir -p /secure/teoria-registry
chmod 700 /secure/teoria-registry
read -r -s -p 'Registry password: ' registry_password
printf '%s\n' "$registry_password" | docker run --rm -i --entrypoint htpasswd httpd:2.4-alpine -Bni registry_operator > /secure/teoria-registry/htpasswd
unset registry_password
openssl rand -hex 32 > /secure/teoria-registry/http_secret
chmod 600 /secure/teoria-registry/htpasswd /secure/teoria-registry/http_secret
```

`httpd`는 bcrypt 인증 파일 생성 후 종료되는 도구이며 상시 서비스로 추가하지 않는다.
인증서와 키는 같은 보안 경로의 `tls.crt`, `tls.key`로 준비한다.
이 구성의 Basic 인증 계정은 Registry 전체의 읽기·쓰기를 허용한다. 별도 계정을 만들어도
권한 범위가 분리되지는 않는다. 프로젝트별 push/pull 권한이 필요하면 token 인증이나
그 기능을 제공하는 기존 Registry를 연결한다. Admin UI/API는 조회만 제공한다.

## Compose Registry 설치

`deploy/compose/registry/compose.yaml`은 별도 Compose 프로젝트다. 플랫폼 `.env`와 별개로
`deploy/compose/registry/.env.example`을 보안 경로에 복사해 인증 파일·TLS 파일의 절대 경로를 채운다.
`TEORIA_IMAGE_REGISTRY_HTTP_SECRET`에는 앞서 생성한 파일의 값을 보관한다.

```bash
docker compose --env-file /secure/teoria-registry/registry.env -f deploy/compose/registry/compose.yaml config --quiet
docker compose --env-file /secure/teoria-registry/registry.env -f deploy/compose/registry/compose.yaml up -d --wait
```

기본 포트는 HTTPS 5000이다. Registry는 직접 TLS를 제공하므로 추가 프록시 컨테이너가 필요 없다.
`registry-data` 볼륨은 재배포 후에도 유지한다. 인증 파일·HTTP secret·볼륨을 함께 백업한다.
이미지 삭제 API는 기본 비활성화하며 플랫폼 이미지 정리 명령은 Registry 저장 내용을 삭제하지 않는다.

## K3s Registry 설치

기존 Traefik ingress를 재사용하므로 추가 상시 workload는 Registry 하나다.
먼저 보안 파일을 사용해 전용 namespace와 Secret을 준비한다.

```bash
kubectl create namespace teoria-registry
kubectl -n teoria-registry create secret generic registry-auth --from-file=htpasswd=/secure/teoria-registry/htpasswd --from-file=http_secret=/secure/teoria-registry/http_secret
kubectl -n teoria-registry create secret tls registry-tls --cert=/secure/teoria-registry/tls.crt --key=/secure/teoria-registry/tls.key
bash deploy/k3s/registry/deploy.sh registry.example.com
```

Registry는 platform의 `teoria` namespace와 독립적이며 전용 50Gi PVC를 사용한다.
이 배포를 반복해도 Secret·PVC를 삭제하지 않는다. 실제 인증·push/pull은 별도로 확인한다.

## 플랫폼 이미지 빌드·배포

예시 repository 구분:

```text
registry.example.com/teoria/teoria-platform-admin:<commit>
registry.example.com/teoria/teoria-nginx:<commit>
registry.example.com/models/customer-churn-training:<version>
registry.example.com/models/customer-churn-serving:<version>
```

빌드 실행 환경에서 `docker login registry.example.com`으로 인증한 뒤,
Compose `.env`에 다음 값을 설정한다. prefix의 마지막 `/`를 포함한다.

```dotenv
TEORIA_IMAGE_PREFIX=registry.example.com/teoria/
TEORIA_IMAGE_TAG=<commit_sha>
```

서비스별 `TEORIA_*_IMAGE`가 채워져 있으면 그 명시적 이미지가 우선한다.
외부 제품의 PostgreSQL·Redis·Prefect 이미지는 기존 제공처를 유지한다.

```bash
bash deploy/compose/deploy.sh build --modules mlops
bash deploy/compose/deploy.sh push --modules mlops
# 배포 서버에서 같은 .env와 Registry 인증을 준비한 후:
bash deploy/compose/deploy.sh deploy --modules mlops --pull
```

`pull`은 선택 이미지 다운로드만, `push`는 선택 구성의 Teoria 빌드 결과만 업로드한다.
`deploy --pull`은 기존 서비스 유지보수에 들어가기 전에 다운로드 실패를 확인한다.
local 개발은 prefix·tag를 비워 기존 build → deploy 방식을 유지한다.

K3s CI는 기본 GHCR을 유지한다. 다른 Registry를 사용하려면 GitHub repository의 variable·secret 설정을 추가한다.

| 설정 | 값 |
|---|---|
| variable `TEORIA_IMAGE_REGISTRY_PREFIX` | `registry.example.com/teoria` — 끝 `/` 제외 |
| secret `TEORIA_IMAGE_REGISTRY_USERNAME` | CI 업로드 계정 |
| secret `TEORIA_IMAGE_REGISTRY_PASSWORD` | CI 업로드 credential |
| variable `TEORIA_IMAGE_BUILD_RUNNER` | 필요 시 사설망 접근 가능한 self-hosted runner label |

CI는 K3s 기존 이미지 이름과 Compose 호환 이름을 같은 이미지의 tag로 게시한다.
commit SHA tag는 같은 commit에 대해 다른 내용을 덮어쓰지 않는 릴리스 규칙으로 운영한다.
K3s의 `teoria-registry` pull Secret도 선택한 Registry 계정으로 준비한다.
Registry URL과 그 인증정보를 설정했다고 임의의 외부 학습 이미지를 실행하는 기능까지 생기는 것은 아니다.
현재 K3s 기본 배포에는 MLOps가 포함되지 않으며, 그 학습 Job·서빙 경로는 후속 구현 범위다.

## Admin 이미지 조회 연결

Compose `.env` 또는 K3s의 `teoria-secrets`에 다음을 설정한다.

```dotenv
TEORIA_IMAGE_REGISTRY_URL=https://registry.example.com
TEORIA_IMAGE_REGISTRY_PUBLIC_HOST=registry.example.com
TEORIA_IMAGE_REGISTRY_USERNAME=registry_operator
TEORIA_IMAGE_REGISTRY_PASSWORD=<registry_password>
```

Compose Registry 기본 포트를 사용하면 URL과 public host에 `:5000`을 포함한다.
API는 서버에 설정한 한 origin만 호출하며 Admin bearer token을 Registry에 전달하지 않는다.
인증된 사용자는 repository·tag를 조회하고 manifest 본문의 SHA256을 검증한 고정 참조를 확인한다.
서버 응답의 pagination Link를 다른 host로 따라가지 않으며 페이지 크기는 제한한다.
현재 조회 연동은 Distribution의 `_catalog`·tag·manifest API와 공개/Basic 인증을 지원한다.
GHCR 등 catalog API 또는 Bearer token 교환 방식이 다른 제품은 실행 이미지 pull과 별도로 조회 어댑터가 필요하다.

학습 Dispatcher의 Registry 인증은 `TEORIA_DOCKER_CONFIG_DIRECTORY`로 전달한다.
이 경로는 Docker daemon이 실행되는 호스트의 디렉터리이며 checkout 밖의 위치를 권장한다.
credential helper가 없는 파일 형식으로 login 정보를 준비한 뒤 읽기 전용으로 mount한다.
Dispatcher 이미지에 없는 OS credential helper나 Desktop keychain 설정은 사용할 수 없다.

```bash
docker --config /secure/teoria-docker-auth login registry.example.com
```

```dotenv
TEORIA_DOCKER_CONFIG_DIRECTORY=/secure/teoria-docker-auth
TEORIA_MODEL_TRAINING_IMAGE=registry.example.com/models/customer-churn-training@sha256:<digest>
TEORIA_MODEL_SERVING_IMAGE=registry.example.com/models/customer-churn-serving@sha256:<digest>
```

현재 고객 이탈 학습 pool은 **Prefect Flow가 포함된 실행 이미지**를 사용한다.
Teoria·Prefect 없이 작성된 임의 학습 이미지의 실행 계약은 아직 구현하지 않았다.
`IfNotPresent` 정책으로 없는 이미지를 다운로드하며 실제 학습 컨테이너에는 Docker 인증 파일을 mount하지 않는다.
서빙 이미지는 Compose가 호스트 인증정보로 다운로드한다.

## 검증 범위

```bash
python3 -m unittest discover -s deploy/compose/tests -v
uv run --project backend --locked --all-extras --group orchestration --group docker-orchestration pytest backend/tests/platform/mlops backend/tests/entrypoints/test_registry_deployment.py backend/tests/entrypoints/test_compose_deployment.py -q
TEORIA_TEST_REGISTRY_DOCKER=1 uv run --project backend --locked --all-extras --group orchestration --group docker-orchestration pytest backend/tests/integration/test_image_registry_docker.py -q
```

실제 Docker 검사는 `registry:3.1.2`와 httpx가 설치된 로컬 Teoria Admin 이미지를 사용한다.
이미지 이름은 `TEORIA_REGISTRY_TEST_CLIENT_IMAGE`로 바꿀 수 있다.
검증은 전용 네트워크·볼륨·자체 서명 인증서·합성 인증정보로 진행하고 종료 시 정리한다.
TLS·미인증 접근 거절·두 repository의 이미지 업로드·pagination·tag·manifest digest 검증·재시작 후 보존을 확인한다.
이 검사가 통과해도 운영 DNS·공인 인증서·실제 K3s 배포 성공을 뜻하지 않는다.

설계는 [Distribution 배포](https://distribution.github.io/distribution/about/deploying/)와
[Registry API](https://distribution.github.io/distribution/spec/api/)를 따른다.
[Palantir 모델 통합](https://www.palantir.com/docs/foundry/model-integration/overview/)의 외부 모델 연결·버전 추적 원칙을 참고하되,
Teoria는 Prefect·MLflow의 기존 권위와 MLOps 소유 경계를 유지한다.
