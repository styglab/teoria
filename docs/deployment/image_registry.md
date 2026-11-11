# 모델 실행 이미지 Registry

Distribution Registry를 Teoria의 선택형 MLOps 구성에 포함한다. 이미지 본문은 Registry 영구 볼륨,
학습 데이터·모델 파일·평가 보고서는 MinIO, 모델 버전·실험 정보는 MLflow가 관리한다.
플랫폼 이미지는 기존 로컬 빌드 또는 GHCR 같은 외부 배포처에서 준비한다.

Admin의 **컨테이너 이미지**는 repository·tag·digest를 조회한다. 웹 tar 반입·이미지 빌드는 아직 제공하지 않는다.
CLI·CI는 표준 `docker login`·`docker push`를 사용한다. 실행 요청은 고정 digest를 사용한다.

## 접속 경로와 인증

Registry는 내부 HTTP `image-registry:5000`에서 동작한다. 외부 접속과 TLS는 기존 플랫폼 프록시가 맡는다.

| 환경 | 클라이언트 주소 | TLS 처리 |
|---|---|---|
| 개발 Compose | `localhost:8081` | 로컬 개발 HTTP; 기존 Nginx의 `/v2/`로 전달 |
| 운영 Kubernetes | `registry.example.com` | 기존 Ingress controller와 공통 `teoria-tls` 사용 |

개발 HTTP는 신뢰하는 개발 환경에서 사용한다. 원격·운영 접속에는 플랫폼 edge의 HTTPS를 사용한다.
Kubernetes Registry 호스트는 플랫폼과 구분할 수 있지만 추가 프록시 컨테이너나 CA 서버는 필요 없다.
공통 TLS 인증서의 SAN 또는 wildcard는 웹 호스트와 Registry 호스트를 모두 포함해야 한다.
기관 CA를 사용하는 폐쇄망에서는 push 실행 환경과 이미지를 받는 노드가 같은 CA를 신뢰하도록 설치한다.

Registry 로그인은 Docker 프로토콜의 Basic 인증을 유지하며 Admin bearer token·브라우저 세션을 전달하지 않는다.
현재 bcrypt 계정은 Registry 전체의 읽기·쓰기를 허용한다. 프로젝트별 권한이 필요하면 별도 token 인증이나
기존 기업 Registry를 연결한다. UI에서 이미지를 조회하는 권한과 Docker push/pull 계정은 구분한다.

## Compose 실행

`compose_mlops.yaml`의 `image-registry`는 호스트 포트를 직접 열지 않는다.
기존 Nginx가 `/v2/`를 Registry로 전달하고 업로드 크기 제한을 해제한다.
요청 buffering을 끄고 전송 timeout을 늘려 대용량·분할 업로드를 지원한다.
Registry는 relative Location을 반환하므로 업로드 재개 요청도 같은 외부 주소를 사용한다.

checkout 밖에 bcrypt 인증 파일과 HTTP secret을 준비한다. 다음은 운영자 도구 사용 예다.

```bash
mkdir -p /secure/teoria-registry
chmod 700 /secure/teoria-registry
read -r -s -p 'Registry password: ' registry_password
printf '%s\n' "$registry_password" | docker run --rm -i --entrypoint htpasswd httpd:2.4-alpine -Bni registry_operator > /secure/teoria-registry/htpasswd
unset registry_password
openssl rand -hex 32 > /secure/teoria-registry/http_secret
chmod 600 /secure/teoria-registry/htpasswd /secure/teoria-registry/http_secret
```

`httpd`는 인증 파일을 생성하고 종료하는 도구이며 상시 서비스가 아니다.
`.env`에 다음 연결을 설정한다. 인증 파일은 Docker daemon 호스트의 절대 경로를 사용한다.

```dotenv
TEORIA_IMAGE_REGISTRY_HTTP_SECRET=<http_secret 파일의 값>
TEORIA_IMAGE_REGISTRY_AUTH_FILE=/secure/teoria-registry/htpasswd
TEORIA_IMAGE_REGISTRY_URL=http://image-registry:5000
TEORIA_IMAGE_REGISTRY_PUBLIC_HOST=localhost:8081
TEORIA_IMAGE_REGISTRY_USERNAME=registry_operator
TEORIA_IMAGE_REGISTRY_PASSWORD=<Registry password>
TEORIA_MODEL_ALLOWED_REGISTRIES=localhost:8081
```

HTTP 포트를 바꾸면 public host와 허용 목록도 같은 포트로 바꾼다. 내부 URL은 바꾸지 않는다.
DevContainer처럼 daemon이 checkout을 다른 경로로 보는 경우 Registry 설정 파일도
`TEORIA_IMAGE_REGISTRY_CONFIG_FILE`로 daemon 호스트의 절대 경로를 지정한다(기본 `./registry/config.yaml`).
Registry 전용 TLS 파일·CA 설정은 필요 없다.

```bash
bash deploy/compose/deploy.sh build --modules mlops
bash deploy/compose/deploy.sh deploy --modules mlops
# 외부 배포처에서 플랫폼 이미지를 받는 환경:
bash deploy/compose/deploy.sh deploy --modules mlops --pull
```

`stop/down`은 Registry를 종료하지만 볼륨을 삭제하지 않는다. 기본 볼륨 이름은
`<Compose 프로젝트>_registry-data`다. 프로젝트 이름을 바꾸며 기존 볼륨을 사용할 때는
[Compose 저장소 재사용 설정](compose.md)을 따른다. 인증 파일·HTTP secret·데이터 볼륨을 함께 백업한다.
이미지 삭제 API는 기본 비활성화하며 플랫폼 이미지 정리는 Registry 저장 내용을 삭제하지 않는다.

기존 별도 HTTPS 5000 구성에서 전환할 때도 같은 인증 파일·HTTP secret·Registry 볼륨을 유지한다.
외부 주소를 새 프록시 주소로 바꾸고 Docker login 정보와 Worker 허용 목록을 갱신한다.
기존 이미지는 재빌드 없이 새 주소로 tag한 뒤 push할 수 있다. 기존 daemon CA 파일은 더 이상 이 로컬 HTTP 연결에 사용하지 않는다.

## 이미지 등록과 실행

현재 고객 이탈 샘플은 다음과 같이 등록한다. `docker load`로 tar를 불러온 경우에도 push 방법은 같다.

```bash
docker build -t localhost:8081/models/customer-churn:0.1.0 archive/customer_churn
docker login localhost:8081
docker push localhost:8081/models/customer-churn:0.1.0
docker image inspect localhost:8081/models/customer-churn:0.1.0 --format '{{json .RepoDigests}}'
```

운영에서는 `localhost:8081`을 설치된 Registry 호스트로 바꾼다. 학습·서빙 요청은
`<host>/models/customer-churn@sha256:...`를 사용한다. [공통 모델 실행 계약](model_execution.md)을 따른다.
플랫폼 이미지의 `TEORIA_IMAGE_PREFIX`·`TEORIA_IMAGE_TAG`는 기존 릴리스 배포처 설정이며 내부 모델 Registry로 바꿀 필요가 없다.

Dispatcher의 pull 인증은 `TEORIA_DOCKER_CONFIG_DIRECTORY`로 전달한다.
이 경로는 daemon 호스트의 디렉터리다. Worker에 없는 credential helper 대신 auth가 들어 있는 Docker config를 준비한다.

```bash
docker --config /secure/teoria-docker-auth login localhost:8081
```

학습·서빙 컨테이너에는 Docker socket·Admin token·DB credential을 전달하지 않는다.

## Kubernetes와 K3s

기존 Ingress controller를 재사용하고 `teoria` namespace에 Registry Deployment·Service와 50Gi PVC를 추가한다.
공통 `teoria-tls` 인증서가 플랫폼 호스트와 Registry 호스트를 모두 포함하도록 먼저 준비한다.
Registry 전용 인증은 `model-registry-auth`, 플랫폼 이미지 pull은 별도의 `teoria-registry` Secret을 사용한다.

```bash
kubectl create namespace teoria --dry-run=client -o yaml | kubectl apply -f -
kubectl -n teoria create secret generic model-registry-auth --from-file=htpasswd=/secure/teoria-registry/htpasswd --from-file=http_secret=/secure/teoria-registry/http_secret
bash deploy/kubernetes/deploy.sh ghcr.io/org/teoria <commit_sha> teoria.example.com --modules mlops --with-model-registry registry.example.com --overlay k3s
```

`model-registry-tls`는 사용하지 않는다. Registry Ingress는 공통 `teoria-tls`를 참조한다.
일반 Kubernetes는 [공통 배포 안내](kubernetes.md)의 generic overlay를 사용한다.
선택한 Ingress controller의 업로드 크기·요청 buffering·timeout도 대용량 이미지 전송에 맞춘다.
Docker·containerd 노드의 CA 신뢰와 이미지 pull Secret은 설치 운영자가 준비한다.
MLOps Admin은 내부 HTTP로 조회하며 public host는 배포 스크립트가 Registry 호스트로 설정한다.

GitHub 배포는 `TEORIA_MODEL_REGISTRY_HOST`로 같은 옵션을 전달한다. Registry 옵션만 지정하면
기존 Semantic 배포에 이미지 저장소를 추가할 수 있다. 옵션 생략은 기존 PVC·workload 삭제를 뜻하지 않는다.
K3s `local-path`는 노드 간 자동 복제 저장소가 아니므로 다중 노드 가용성이 필요하면 재연결 가능한 저장소를 선택한다.

## 외부 Registry 연결

기존 Registry를 조회할 경우 내부 URL 대신 해당 origin을 지정할 수 있다.
HTTPS와 사설 CA가 필요한 외부 연결은 `TEORIA_IMAGE_REGISTRY_CA_PEM`에 PEM 본문을 지정한다.
서버는 설정한 한 origin만 호출하며 pagination Link의 다른 host를 따라가지 않는다.
조회는 Distribution `_catalog`·tag·manifest API와 공개/Basic 인증을 지원한다.
GHCR 등 catalog 또는 인증 방식이 다른 제품은 별도 조회 어댑터가 필요할 수 있다.

## 검증

```bash
python3 -m unittest discover -s deploy/compose/tests -v
uv run --project backend --locked --all-extras --group orchestration --group docker-orchestration pytest backend/tests/platform/mlops backend/tests/entrypoints/test_registry_deployment.py backend/tests/entrypoints/test_compose_deployment.py -q
TEORIA_TEST_REGISTRY_DOCKER=1 TEORIA_REGISTRY_TEST_CLIENT_IMAGE=teoria-platform-admin:0.1.0 uv run --project backend --locked --all-extras --group orchestration --group docker-orchestration pytest backend/tests/integration/test_image_registry_docker.py -q
```

Docker 검증은 전용 네트워크·볼륨·합성 계정으로 진행한다. 실제 Nginx 설정을 사용해 HTTP와 TLS edge를 모두 거쳐
미인증 접근 거절·1MiB 초과 분할 업로드·다운로드·pagination·tag·manifest digest·Registry 재시작 후 보존을 확인한다.
검증용 프록시 인증서는 운영 설정에 사용하지 않는다. 운영 DNS·인증서·Kubernetes 실배포 성공은 별도 검증 대상이다.

설계는 [Distribution 프록시](https://distribution.github.io/distribution/recipes/nginx/)와
[Registry API](https://distribution.github.io/distribution/spec/api/)를 따른다.
[Palantir 모델 통합](https://www.palantir.com/docs/foundry/model-integration/overview/)의 외부 모델 연결·버전 추적 원칙을 참고하되,
Teoria는 Prefect·MLflow의 기존 권위와 MLOps 소유 경계를 유지한다.
