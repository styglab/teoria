# 모델 실행 이미지 Registry 연결

Teoria는 Registry 서버를 배포하지 않는다. 플랫폼의 **컨테이너 이미지** 화면은 기존
Registry의 repository·tag·digest를 조회하고 학습·서빙 요청에 사용할 고정 digest 참조를 제공한다.
이미지 본문은 외부 Registry, 학습 데이터·모델 파일은 객체 저장소, 실험·모델 버전은 MLflow가 소유한다.
플랫폼 이미지와 모델 이미지는 같은 Registry 안에서 `teoria/`·`models/` 같은 경로로 구분할 수 있다.

## 로컬 k3d

[k3d 실행](k3d.md)의 `local.sh up`이 클러스터 공용 Registry를 준비한다.
MLOps 안에 추가 Registry Deployment·Service·PVC·Ingress를 만들지 않는다.

| 사용처 | 주소 |
|---|---|
| Docker 호스트에서 push | `localhost:5111` |
| Admin API의 이미지 조회 | `http://k3d-teoria-images:5000` |
| 모델 이미지 참조·노드 pull | `localhost:5111/models/<name>@sha256:...` |

노드의 containerd mirror가 `localhost:5111`을 공용 Registry로 연결한다.
Registry는 loopback에 노출되는 인증 없는 개발용 구성이다. 원격·운영에서는 인증·TLS를 갖춘 Registry를 사용한다.
MLOps 배포는 조회 URL과 공개 이미지 참조 host를 위 값으로 자동 설정한다.
`model-control`의 `TEORIA_MODEL_ALLOWED_REGISTRIES`는 `localhost:5111`로 지정한다.

```bash
bash deploy/kubernetes/k3d/local.sh up
bash deploy/kubernetes/k3d/local.sh build --modules mlops
# 모델 실행용 Secret·계정 준비 후:
bash deploy/kubernetes/k3d/local.sh deploy --modules mlops
```

모델 이미지는 별도 빌드한 뒤 공용 Registry에 push한다. 학습·서빙은 태그 대신 digest를 사용한다.
기존 플랫폼 `.local/docker_config.json`의 빈 pull 설정은 인증 없는 로컬 Registry에만 사용할 수 있다.
`teoria-models` namespace의 `model-images`도 해당 Registry에 맞는 pull 설정으로 준비한다.

## Compose·운영 Kubernetes

Registry 주소·인증정보는 배포 플랫폼이 제공한다. Compose의 `.env` 또는 Kubernetes
`teoria-secrets`에 다음 키를 설정한다. 조회용 URL은 Admin 컨테이너에서 접근 가능해야 한다.
공개 host는 실제 push와 노드 pull에 사용하는 host·port이며 프로토콜을 포함하지 않는다.

```dotenv
TEORIA_IMAGE_REGISTRY_URL=https://registry.example.com
TEORIA_IMAGE_REGISTRY_PUBLIC_HOST=registry.example.com
TEORIA_IMAGE_REGISTRY_USERNAME=<조회 계정>
TEORIA_IMAGE_REGISTRY_PASSWORD=<조회 계정 암호>
TEORIA_MODEL_ALLOWED_REGISTRIES=registry.example.com
```

Kubernetes 허용 목록은 `model-control`에 둔다. 모델 pull 인증은 `teoria-models/model-images`,
플랫폼 이미지 pull은 `teoria/teoria-registry`로 분리한다. 조회 계정과 push·pull 계정은 역할에 맞게 제한한다.
외부 HTTPS의 사설 CA는 `TEORIA_IMAGE_REGISTRY_CA_PEM`에 PEM 본문을 설정한다.

Kubernetes CLI로 조회 주소를 지정할 수도 있다. 이 옵션은 기존 Registry 연결만 설정한다.

```bash
bash deploy/kubernetes/deploy.sh ghcr.io/org/teoria <commit_sha> teoria.example.com \
  --overlay k3s --modules mlops \
  --model-registry-host registry.example.com \
  --model-registry-url https://registry.example.com
```

URL을 생략하면 `https://<host>`를 사용한다. CLI 옵션이 없으면 Secret의 연결 설정을 사용한다.
Compose에서는 `build --modules mlops`, `deploy --modules mlops`를 그대로 사용한다.
플랫폼 웹 프록시의 `/v2/` 경로는 제공하지 않는다. Docker client는 Registry 주소로 직접 접속한다.
Docker 실행 Worker의 pull 계정은 `TEORIA_DOCKER_CONFIG_DIRECTORY`로 전달한다.

이미지 조회는 Distribution `_catalog`·tag·manifest API와 공개/Basic 인증을 지원한다.
GHCR 등 catalog·인증 계약이 다른 서비스에는 별도 조회 어댑터가 필요할 수 있다.
서버는 설정된 한 origin만 호출하고 pagination Link의 다른 host를 따라가지 않는다.

## 기존 내장 Registry에서 전환

기존 이미지·인증정보·볼륨은 먼저 백업하고 새 Registry로 이미지를 이관한다.
조회 URL·공개 host·실행 허용 목록·pull 계정을 함께 갱신하고 학습·서빙까지 확인한다.
기존 Registry 컨테이너·Deployment·Service·Ingress는 운영자가 전환 후 정리한다.
새 배포 정의는 기존 리소스를 자동 삭제하지 않으며 `registry-data` PVC·Docker 볼륨도 삭제하지 않는다.
기존 MLflow용 `model-ui-auth`는 사용하지 않는다. 모든 Kubernetes overlay의 `/mlflow/`는
기존 UI 프록시에서 Prefect 운영 계정으로 인증한다.

## 검증

```bash
uv run --project backend --locked --all-extras --group orchestration pytest \
  backend/tests/entrypoints/test_registry_deployment.py \
  backend/tests/entrypoints/test_kubernetes_deployment.py \
  backend/tests/entrypoints/test_compose_deployment.py deploy/compose/tests/test_compose_configuration.py -q
TEORIA_TEST_REGISTRY_DOCKER=1 uv run --project backend --locked --all-extras --group orchestration \
  --group docker-orchestration pytest backend/tests/integration/test_image_registry_docker.py -q
```

실컨테이너 검사는 테스트 fixture의 외부 Registry·TLS 프록시를 사용해 인증·업로드·조회·보존을 확인한다.
플랫폼에 Registry 서버를 설치하지 않는다. 운영 Registry와 실제 학습·서빙의 연결 검증은 별도다.
