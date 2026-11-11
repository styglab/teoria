# 공통 모델 실행과 배포

Teoria는 외부에서 만든 일반 OCI 이미지를 실행한다. 학습·서빙 이미지에 Teoria나 Prefect를 설치할 필요는 없다.
Compose 개발 환경과 Kubernetes 운영 환경은 같은 실행 입력을 사용한다. 플랫폼 소스 변경 없이
서로 다른 모델 이미지·명령·자원을 지정하며, 관리 작업은 Admin bearer 인증과 `metadata_admin` 역할을 검증한다.

## 실행 명령

이미지마다 학습·서빙에 사용할 `command`를 실행 요청에 명시한다. 별도 `model` CLI 설치나
Python 패키지 배포는 요구하지 않는다. 고객 이탈 샘플은 `python -m customer_churn train`과
`python -m customer_churn serve`를 사용한다. 데이터·모델 버전은 환경변수 계약으로 전달한다.
서빙은 `0.0.0.0:8080`에서 `/health`와 `POST /predict`를 제공하며 예측 JSON의 필드는 모델이 정의한다.

## 책임과 기본 구성

Compose `--modules mlops`는 Web·Admin API·Platform PostgreSQL·MinIO·Prefect Server·Prefect Services·Redis·
MLflow·공통 실행 Worker의 9개 상시 서비스를 시작한다. Registry는 기존 외부 서비스를 사용한다.
모델별 학습 컨테이너와 서빙은 별도로 생성한다.
기존 Data PostgreSQL과 OPA·Policy Control Plane은 기본으로 시작하지 않는다. 데이터와 기존 볼륨은 삭제하지 않는다.

공통 Worker의 Prefect process pool은 `teoria-model-operations`다. 학습은 Docker 컨테이너 또는 Kubernetes Job,
서빙은 모델별 Docker 컨테이너 또는 Deployment·Service로 실행한다. 실행 이미지는 허용 Registry의 고정 digest만 받는다.
이미지·파라미터와 실행 상태는 Prefect, 모델 버전은 MLflow, 활성·이전 서빙 참조와 요청 주체는 Application DB가 소유한다.

`teoria-mlflow`는 MLflow 서버·S3·PostgreSQL 연결용 이미지다. backend의 `mlflow-server`
의존성 그룹만 설치하며 Teoria 애플리케이션·Prefect·수집 계약은 포함하지 않는다.
`teoria-model-dispatcher`는 Prefect와 컨테이너 실행을 담당하는 별도 공통 Worker 이미지다.

## 개발 Compose 시작

[Compose 준비](compose.md)와 [이미지 Registry 인증·TLS](image_registry.md)를 먼저 설정한다.
플랫폼 이미지는 기존 외부 배포처 또는 로컬 빌드로 준비한다. `.env`에 허용 Registry와 런타임 전용 환경을 지정한다.

```dotenv
TEORIA_MODEL_ALLOWED_REGISTRIES=registry.example.com:5000
TEORIA_DOCKER_CONFIG_DIRECTORY=/secure/teoria-docker-auth
TEORIA_MODEL_WORKLOAD_ENVIRONMENT={"AWS_ACCESS_KEY_ID":"<workload_account>","AWS_SECRET_ACCESS_KEY":"<workload_secret>","AWS_ENDPOINT_URL_S3":"http://minio:9000","MLFLOW_S3_ENDPOINT_URL":"http://minio:9000"}
```

위 JSON은 비밀 설정이며 Git·Flow 입력·명령 출력에 기록하지 않는다. 예시의 저장소 계정은 학습·산출물 bucket만 접근하게 준비한다.
각 이미지가 신뢰할 수 있는 개발자·CI에서 게시되었는지 확인한다. Registry 허용 목록은 이미지 제작자에 대한 신뢰를 대신하지 않는다.
Worker는 Docker socket을 사용하지만 학습·서빙 컨테이너에는 socket·호스트 볼륨·Admin·Prefect·Application DB credential을 주지 않는다.

```bash
bash deploy/compose/deploy.sh config --modules mlops
bash deploy/compose/deploy.sh build --modules mlops
bash deploy/compose/deploy.sh deploy --modules mlops
bash deploy/compose/deploy.sh status
```

기존 모듈·addon 선택에서 전환할 때는 기존 구성으로 `down` 후 새 구성으로 `deploy`한다.
`--all`은 제품 모듈을 선택한다. 고객 이탈 예제는 Compose 배포에 포함하지 않는다.
이 addon은 Data DB·예제 Docker Dispatcher·배포 Worker·추론 API와 기존 Flow ID를 추가한다.
예제 학습·서빙 이미지는 addon을 선택한 구성으로 미리 빌드한다. 기본 MLOps 실행에는 필요 없다.

## 학습 이미지 계약

이미지는 UID/GID 10001로 실행 가능해야 하며 명시한 명령을 실행하고 성공 시 0, 실패 시 0이 아닌 코드로 종료한다.
입력 데이터 checksum 검증, 학습·평가, MLflow 기록과 모델 버전 등록, 산출물 업로드는 모델 이미지의 책임이다.
표준 출력은 Docker·Kubernetes의 컨테이너 로그이며 학습 컨테이너 정리 후 보존되지 않는다.
보존할 학습 로그·평가 보고서는 이미지가 MLflow 또는 출력 S3 경로에 기록해야 한다.

이미지가 받는 환경변수:

| 환경변수 | 값 |
|---|---|
| `TEORIA_MODEL_NAME` | 모델 이름 |
| `TEORIA_TRAINING_RUN_ID` | Prefect 실행 ID; MLflow tag로 연결 권장 |
| `TEORIA_INPUT_URI`, `TEORIA_INPUT_SHA256` | `s3://bucket/key` 입력과 SHA256 |
| `TEORIA_OUTPUT_URI` | 실행별 `s3://bucket/prefix` 산출물 위치 |
| `TEORIA_TRAINING_PARAMETERS` | 모델별 파라미터 JSON |
| `MLFLOW_TRACKING_URI` | 실험·모델 기록 API |

Admin의 **워크플로우 → 모델 이미지 학습 → 수동 실행**에서 다음 JSON을 입력한다.
이미지 digest·데이터 checksum·경로는 실제 값으로 바꾼다. 데이터 경로와 출력 경로는 실행별 불변 경로로 운영한다.

```json
{
  "model_name": "my_model",
  "image": "registry.example.com:5000/models/my-training@sha256:<64자리_digest>",
  "command": ["python", "/app/train.py"],
  "input_uri": "s3://training-data/datasets/v1/data.csv",
  "input_sha256": "<64자리_SHA256>",
  "output_uri": "s3://training-results/my-model/run-001",
  "parameters": {"trees": 100},
  "resources": {"cpu": 2, "memory_mib": 2048, "gpu": 0},
  "timeout_seconds": 3600
}
```

동일 요청을 API로 제출할 때는 다음 형식을 사용한다. 인증 주체를 서버가 `requested_by`로 넣으며 body의 주체 값은 받지 않는다.
같은 요청을 재시도할 때는 같은 idempotency UUID를 사용한다. 인증정보는 `execution`에 넣지 않는다.

```text
POST /admin-api/v1/admin/workflows/pipelines/model-train/runs
Authorization: Bearer <Admin token>
Content-Type: application/json

{"idempotency_key":"<UUID>","execution":{...위 학습 입력...}}
```

## 서빙 이미지 계약

이미지는 포트 8080에서 HTTP를 제공하고 준비 경로가 성공했을 때 고정 모델 버전의 추론을 처리할 수 있어야 한다.
`TEORIA_MODEL_URI=models:/<name>/<version>`, `TEORIA_MODEL_SHA256`, `TEORIA_MODEL_NAME`, `TEORIA_MODEL_VERSION`,
`MLFLOW_TRACKING_URI`, `PORT=8080`을 받는다. 이미지는 모델을 로드하면서 checksum을 검증해야 한다.
모델 checksum은 모델 디렉터리 아래 파일을 상대 경로 순서로 정렬한 뒤 각 파일의
`상대 경로 UTF-8 + NUL 바이트 + 파일 본문`을 순서대로 SHA256에 누적한 값이다.
이는 기존 MLflow 연결의 `model_checksum`과 같은 알고리즘이며 실행 이미지 digest와 구분한다.
추론 API는 `POST /predict`이며 입력·응답 JSON의 스키마는 모델 개발자가 정의한다.

**워크플로우 → 모델 이미지 서빙 배포 → 수동 실행**:

```json
{
  "deployment_id": "my-model-production",
  "model_name": "my_model",
  "model_version": 1,
  "model_sha256": "<64자리_SHA256>",
  "image": "registry.example.com:5000/models/my-serving@sha256:<64자리_digest>",
  "command": ["python", "/app/serve.py"],
  "resources": {"cpu": 1, "memory_mib": 1024, "gpu": 0},
  "readiness_path": "/health",
  "readiness_timeout_seconds": 120,
  "replicas": 1
}
```

API는 `model-deploy` Workflow에 같은 `execution`을 제출한다. 모델별 동시 배포·중지는 DB advisory lock으로 직렬화한다.
Compose는 후보 컨테이너의 준비 상태를 확인한 뒤 기존 컨테이너를 교체한다. 전환 중 짧은 중단이 생길 수 있으며
무중단 배포를 보장하지 않는다. 실패하면 기존 컨테이너를 유지·복원한다. 개발 Compose의 서빙 복제본은 1개만 지원한다.
Kubernetes는 RollingUpdate·readiness와 지정 복제본을 사용하고 준비 실패 시 이전 Deployment 설정을 복원한다.

Admin **모델 서빙**에서 배포 상태·추론 요청·이전 설정 재배포·중지를 사용할 수 있다.
서빙 endpoint는 내부 전용이며 외부 추론은 인증된 Admin 경유 API를 사용한다.

```text
GET  /admin-api/v1/admin/model-operations/deployments
POST /admin-api/v1/admin/model-operations/deployments/<deployment_id>/predict
```

중지는 `model-stop` Workflow에 `{"deployment_id":"my-model-production"}`를 전달한다.
이전 설정 재배포도 새 Prefect 실행으로 기록하며 모델을 다시 학습하지 않는다.
동적 서빙은 Compose 본체가 소유하는 고정 서비스가 아니므로, 플랫폼 `stop/down` 후에도 실행 중일 수 있다.
서빙을 함께 종료하려면 플랫폼 종료 전에 명시적으로 중지한다. 이미지·모델·DB의 영구 데이터는 지우지 않는다.

## Kubernetes 설치와 자원

일반 Kubernetes는 [공통 Kubernetes 배포](kubernetes.md)의 `--overlay generic`을 사용한다.
K3s overlay와 모델 실행 계약은 유지하며 공통 실행 정책은 `deploy/kubernetes/prefect/`가 소유한다.

공통 배포 명령에서 다음처럼 K3s를 선택한다. 현재 Kubernetes CLI는 기존 Semantic 배포 또는 MLOps 단독 배포를 지원하며
두 모듈의 결합 설치는 지원하지 않는다. 기존 Semantic 설치 위에 MLOps를 덮어쓰지 않도록 검사한다.

```bash
bash deploy/kubernetes/deploy.sh ghcr.io/org/teoria <commit_sha> teoria.example.com --overlay k3s \
  --modules mlops --model-registry-host registry.example.com
```

기존 `teoria-secrets`에는 Platform DB 관리자·Application·Prefect 계정과 URL, Admin token, Prefect 인증,
MinIO 관리자 계정과 기존 외부 Registry 연결·조회 계정을 준비한다. 플랫폼 웹 Ingress는 `teoria-tls`를 사용한다.
추가로 다음 Secret을 준비한다. `deploy/kubernetes/control.env.example`과 `workload.env.example`을
checkout 밖의 보안 경로에 복사해 실제 값을 채우고 `kubectl create secret generic ... --from-env-file=...`로 생성한다.
credential은 보안 파일에서 생성하며 예시 값을 운영에 쓰지 않는다.

| namespace | Secret | 내용 |
|---|---|---|
| `teoria` | `teoria-registry` | 플랫폼 이미지 pull 인증 |
| `teoria` | `model-control` | `TEORIA_MLFLOW_DB_PASSWORD`, `MLFLOW_BACKEND_STORE_URI`, `TEORIA_MODEL_ALLOWED_REGISTRIES` |
| `teoria-models` | `model-images` | 모델 이미지 pull 인증 (`kubernetes.io/dockerconfigjson`) |
| `teoria-models` | `model-workload` | 학습·서빙 이미지용 S3 계정·endpoint 등 환경변수 |

`MLFLOW_BACKEND_STORE_URI`는 MLflow 전용 PostgreSQL 계정의 `postgresql+psycopg2://...@platform-postgres:5432/mlflow`다.
`TEORIA_MODEL_ALLOWED_REGISTRIES`에는 실제 모델 Registry host만 쉼표로 구분한다.
`model-workload`의 MinIO endpoint는 다른 namespace에서 접근 가능한 `http://minio.teoria.svc:9000`을 사용한다.
모든 Kubernetes overlay의 `/mlflow/` UI는 기존 UI nginx가 Prefect 운영 계정으로 인증한다.
Registry 계정·bcrypt 파일·전용 인증 CRD는 사용하지 않는다. `/prefect/`도 Prefect 인증을 사용한다.
`teoria-models` namespace를 만들고 Secret을 준비한 뒤 배포 명령을 실행한다. 실행 Role은 이 namespace의
Job·Deployment·Service만 관리하며 workload Pod에는 ServiceAccount token을 mount하지 않는다.

GitHub 자동 배포는 repository variable `TEORIA_DEPLOY_MODULES=mlops`와 `TEORIA_MODEL_REGISTRY_HOST`를 설정한다.
단일 기본 PVC는 노드 간 복제·고가용성을 보장하지 않는다. 여러 서버에서 노드 장애까지 견디려면
Platform PostgreSQL·MinIO의 외부 서비스 또는 적절한 영구 저장소와 백업·복원 구성을 별도로 준비한다.

Compose는 한 Docker 호스트의 CPU·메모리·GPU 제한과 동시 실행 수를 적용한다. Kubernetes에서는 같은 자원을
requests·limits와 GPU 리소스로 변환하여 노드에 배치한다. 기본 실행은 1 CPU·1024MiB, GPU 0이다.
GPU는 Docker의 NVIDIA runtime 또는 Kubernetes device plugin이 설치된 실제 환경에서 별도 검증해야 한다.

## 검증과 운영 범위

```bash
uv run --project backend --locked --all-extras --group orchestration pytest backend/tests
python3 -m unittest discover -s deploy/compose/tests -q
TEORIA_TEST_MODEL_EXECUTION_DOCKER=1 uv run --project backend --locked --all-extras --group orchestration --group docker-orchestration pytest backend/tests/integration/test_model_execution_docker.py backend/tests/integration/test_mlops_database_docker.py -q
```

Docker 검사는 격리 Registry·네트워크·외부 실행 이미지로 학습·서빙·버전 전환·실패 후보 복구·중지를 확인한다.
DB 검사는 격리 PostgreSQL에서 전체 migration·배포 이력·모델별 lock을 확인한다.
Kubernetes API의 요청·rollback 검사는 가짜 transport로 수행하며 실제 클러스터 배포 성공과 구분한다.

장애 후 자동 정리·재조정, 분산 학습, 오토스케일링, 카나리 트래픽 분배, 모델 drift 감지는 현재 범위에 포함하지 않는다.
Worker 강제 종료 시 Docker 학습·후보 컨테이너가 남을 수 있으므로 `io.teoria.project`·`io.teoria.run` label로 점검한다.
Kubernetes Job에는 실행 기한과 TTL을 설정한다. 리소스 강제 삭제 전에 진행 중인 실행과 DB 참조를 확인한다.

설계는 [Prefect Docker Worker](https://reference.prefect.io/prefect_docker/worker/),
[Prefect Kubernetes Worker](https://reference.prefect.io/prefect_kubernetes/worker/),
[Palantir 모델 통합](https://www.palantir.com/docs/foundry/model-integration/overview/)의 실행 환경 분리·고정 버전·추적 원칙을 참고한다.
Teoria의 공통 Flow가 일반 이미지를 실행하는 방식이며, Palantir 기능 동등성이나 Prefect Worker 자체의 구현을 뜻하지 않는다.
