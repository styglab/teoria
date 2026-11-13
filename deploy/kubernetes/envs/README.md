# 환경별 설정과 인증정보

`dev`·`prod`는 배포 환경이고, `k3d`·`k3s`·`generic`은 클러스터 종류다.
일반 설정과 역할별 비밀값을 같은 환경 폴더에서 준비한다. 기존 ConfigMap·Secret 이름과 namespace는 유지한다.

```text
envs/
  dev/
    connections.env.example
    secrets.env.example
    control.env.example
    workload.env.example
    specification.env.example
    harbor_secrets.env.example
    harbor_values.yaml.example
    k3d.env.example          # dev 전용 선택 입력
  prod/
    ...같은 역할의 예시
  settings.sh
```

예시만 Git에 포함하며 실제 `*.env`는 Git·이미지 빌드 대상에서 제외한다.
운영 실제 파일은 운영자·배포 계정이 사용하는 환경에만 두고 개발 인증정보를 재사용하지 않는다.
Git은 디렉터리의 700 권한을 보존하지 않으므로 아래 초기화로 권한을 설정한다.

## 1. 초기화와 수정

저장소 루트에서 실행한다. `init`은 기존 파일의 값을 덮어쓰지 않으며 클러스터에 접속하지 않는다.
디렉터리는 700, 실제 env 파일은 600으로 설정한다. 비밀값의 `CHANGE_ME`와 환경별 연동 값을 채운다.
`connections.env`는 서비스 주소·기능 활성화 여부를 담으며 비밀번호·토큰을 넣지 않는다.

```bash
bash deploy/kubernetes/envs/settings.sh init --env dev
# 운영자 환경에서만:
bash deploy/kubernetes/envs/settings.sh init --env prod
# checkout 밖에서 관리할 때:
bash deploy/kubernetes/envs/settings.sh init --env prod --dir /secure/teoria/prod
```

| 파일 | 역할 | namespace | 저장 리소스 |
|---|---|---|---|
| `connections.env` | 서비스 주소·기능 활성화·공개 URL | `teoria` | ConfigMap `teoria-mlops-connections` |
| `secrets.env` | 플랫폼·기반 서비스 인증 | `teoria` | Secret `teoria-secrets` |
| `control.env` | 모델 제어·MLflow 인증 | `teoria` | Secret `model-control` |
| `workload.env` | 모델 Job·서빙 인증 | `teoria-models` | Secret `model-workload` |
| `specification.env` | 규격서 처리 API·S3 | `teoria` | Secret `specification-processing` |
| `harbor_secrets.env` | Harbor 관리자·암호화 키 | `harbor` | Secret `harbor-secrets` |

예시는 선택 기능을 포함하므로 실제로 사용하는 역할만 등록한다.
Registry 주소·허용 목록은 해당 클러스터의 실제 접속 주소에 맞춘다.
TLS·Registry pull 로그인·Codex `auth.json`은 [최초 설치](../../../docs/deployment/bootstrap.md)에 따라 별도로 준비한다.
k3d IP 접속 입력은 `k3d/.local/remote_access.env`에 유지한다.

## 2. 대상 클러스터에 등록

대상 context·namespace를 먼저 확인하고 필요한 namespace를 준비한다.
명령마다 context를 명시하며 현재 kubectl context를 전환하지 않는다.
아래 context 이름은 실제 클러스터에 등록한 이름으로 바꾼다.

```bash
# k3d는 기본 kubeconfig를 자동 변경하지 않으므로 전용 파일을 지정한다.
export KUBECONFIG="${TEORIA_K3D_KUBECONFIG:-deploy/kubernetes/k3d/.local/kubeconfig}"
kubectl config get-contexts
bash deploy/kubernetes/envs/settings.sh apply --env dev --context k3d-teoria --role connections
bash deploy/kubernetes/envs/settings.sh apply --env dev --context k3d-teoria --role platform
bash deploy/kubernetes/envs/settings.sh apply --env dev --context k3d-teoria --role control
bash deploy/kubernetes/envs/settings.sh apply --env dev --context k3d-teoria --role workload
# 규격서 처리를 사용하는 경우:
bash deploy/kubernetes/envs/settings.sh apply --env dev --context k3d-teoria --role specification

# 운영자 환경의 별도 경로를 사용하는 예:
KUBECONFIG=/secure/kube/prod.yaml bash deploy/kubernetes/envs/settings.sh apply --env prod --context production-cluster --role connections --dir /secure/teoria/prod
```

등록은 server-side apply를 사용하며 필드 소유권 충돌을 강제로 덮어쓰지 않는다.
기존 Secret의 필드 관리자는 유지해 도구 이름 변경만으로 소유권이 바뀌지 않게 한다.
기존 리소스의 관리 방식과 충돌하면 변경 주체를 확인한 후 정리한다.
등록 명령은 서비스 재시작이나 배포를 자동 실행하지 않고, 성공하면 다음 반영 범위를 안내한다.

## 3. 서비스에 반영

파일 수정 → `settings.sh apply` → 소유 컴포넌트 배포 순서로 진행한다.
플랫폼·MLflow 배포는 ConfigMap을 미리 등록했는지와 필수 값을 검사한다.
예시 파일로 ConfigMap을 자동 생성하지 않으며, 배포가 등록된 값을 덮어쓰지 않는다.
기존 클러스터의 ConfigMap에는 `TEORIA_ENVIRONMENT` 키를 추가한다.
Teoria API·Runtime·정책 서비스·Worker·migration/등록 Job이 이 값을 읽고 Prefect 작업 Job에도 전달한다.
`dev` 예시는 `development`, `prod` 예시는 `production`이며 overlay 선택과 독립적이다.

| 바꾼 입력 | 후속 반영 |
|---|---|
| `connections.env` | `--component platform`; `TEORIA_MODEL_STORAGE_ENDPOINT` 변경 시 `--component mlflow`도 실행 |
| `secrets.env` | 플랫폼 값은 `--component platform`; 기반 서비스 값은 해당 서비스의 회전·재시작 절차로 반영 |
| `control.env` | `--component platform`; MLflow DB 인증 변경 시 `--component mlflow`도 실행 |
| `specification.env` | `--component platform`; 이미 실행 중인 규격서 Job은 기존 환경을 유지 |
| `workload.env` | 이후 생성하는 모델 Job에 적용; 기존 서빙은 MLOps의 명시적 재배포로 반영 |
| `harbor_secrets.env`·`harbor_values.yaml` | Harbor Helm release에 별도 반영; 기존 DB·키 회전 절차 확인 |

예를 들어 k3d의 일반 설정을 바꾼 후:

```bash
bash deploy/kubernetes/envs/settings.sh apply --env dev --context k3d-teoria --role connections
bash deploy/kubernetes/k3d/local.sh deploy --component platform
# 객체 저장소 endpoint도 변경했다면:
bash deploy/kubernetes/k3d/local.sh deploy --component mlflow
```

플랫폼 배포는 일반 설정 값과 관련 Secret의 UID·resourceVersion으로 revision을 계산한다.
변경 시 Admin·Runtime·정책 API·OPA의 Pod template에 revision을 반영해 새 환경변수로 교체한다.
Worker는 기존 배포 절차의 중지·검증·등록 후 재활성화 단계에서 새 값을 읽는다.
MLflow 배포는 객체 저장소 endpoint와 관련 Secret revision 변경 시 Pod를 교체한다. 도메인 활성화 값은 MLflow revision에 포함하지 않는다.
같은 입력이면 revision은 유지한다. `--render`는 클러스터 입력을 읽지 않으므로 실제 revision을 표시하지 않는다.

Prefect·MinIO·OpenMetadata·DB 같은 기반 서비스는 소유 인증 변경 절차를 따른다.
필요한 실제 계정 변경을 먼저 처리하고, env 값을 사용하는 기존 Pod에는 해당 Deployment/StatefulSet의
명시적인 `kubectl --context CONTEXT -n teoria rollout restart ...`가 필요할 수 있다.
PostgreSQL role 암호는 Secret 등록이나 Pod 재시작만으로 변경되지 않는다.
등록된 설정이 올바르게 반영되는지 확인한 뒤 해당 기능을 실행한다.

실제 env 파일은 접근을 제한한 저장소에 안전하게 백업하고 로그·이슈·빌드 산출물로 공유하지 않는다.
파일 암호화·중앙 Secret 관리 도구는 현재 필수 구성에 포함하지 않는다.
일반 설정은 [Kubernetes ConfigMap](https://kubernetes.io/docs/concepts/configuration/configmap/),
인증정보는 기존 Secret·역할별 접근 권한을 유지한다.

## Harbor와 k3d 입력

`harbor_values.yaml.example`을 같은 폴더의 `harbor_values.yaml`로 복사하고 600 권한을 설정한다.
Helm의 공개 URL·스토리지·DB 초기 암호는 이 YAML에서, 관리자 암호·암호화 키는 `harbor_secrets.env`에서 관리한다.
`settings.sh apply --env dev --context k3d-teoria --role harbor`로 Secret을 등록한 뒤
`bash deploy/kubernetes/harbor/deploy.sh --env dev --overlay k3d`로 별도 설치한다.
TLS Secret·이미지 반입은 [Harbor 설치](../../../docs/deployment/image_registry.md)를 따른다.
chart 버전·checksum은 `harbor/chart.json`에서 관리하고 k3d chart cache는 `.local/cache/charts/`를 사용한다.

개발 호스트 설정이 필요하면 `k3d.env.example`을 `k3d.env`로 복사한다. `local.sh`가 자동으로 읽으며
파일을 shell에서 `source`하지 않는다. Docker 호스트 데이터 경로·API 주소·포트·이미지 revision만 담는다.
셸의 `TEORIA_K3D_*` 값이 우선하며 다른 경로는 `TEORIA_K3D_ENV_FILE`로 지정한다.
파일 없이 실행하면 기존 기본값을 사용한다. `init`은 호스트별 설정과 Harbor YAML을 자동 생성하지 않는다.

`TEORIA_IMAGE_REGISTRY_CA_PEM`에는 PEM 줄바꿈을 한 줄의 `\n`으로 표현할 수 있다.
`kubectl --from-env-file`은 이를 literal 값으로 등록하고 애플리케이션 설정이 PEM으로 복원한다.
