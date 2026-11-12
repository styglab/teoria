# Teoria 배포 안내

Kubernetes에서는 Metadata·Ontology·MLOps를 하나의 Teoria 구성으로 실행한다.
API·UI·Runtime·역할별 Worker 이미지는 분리하며, 서비스 갱신 범위만 선택한다.
명령은 저장소 루트에서 실행한다.

## 현재 개발 환경의 일상 명령

```bash
source deploy/kubernetes/k3d/.local/session.env

bash deploy/kubernetes/k3d/local.sh render > /tmp/teoria_platform.yaml
bash deploy/kubernetes/k3d/local.sh deploy
bash deploy/kubernetes/k3d/local.sh status
```

`render`는 클러스터에 접속하지 않는다. `deploy` 기본값은 Teoria만 갱신한다.
이미지를 직접 빌드할 때는 `local.sh build`를 사용한다. 외부에서 검증한 이미지를 반입하면 빌드는 생략한다.
현재 로컬 설정은 `.local/session.env`가 제공한다. 새 환경은 [k3d 설치](../docs/deployment/k3d.md)를 따른다.

## 최초 설치와 일상 갱신

| 선택 | 갱신 범위 |
|---|---|
| 기본값 또는 `--component platform` | Teoria API·UI·Runtime·정책·Worker, Application DB migration·Flow 등록 |
| `--component database` | PostgreSQL·플랫폼 DB/계정·Data DB schema·읽기 권한 |
| `--component storage` | MinIO·모델 bucket |
| `--component workflow` | Prefect Server·Services·전용 Redis |
| `--component mlflow` | MLflow |
| `--component openmetadata` | OpenMetadata 전용 검색·schema migration·서버 |
| `--component all` | 위 기반 서비스와 Teoria를 순서대로 준비 |

```bash
# 인증정보·이미지·게시 artifact를 준비한 최초 설치
bash deploy/kubernetes/k3d/local.sh deploy --component all

# 이후 Teoria 코드만 갱신
bash deploy/kubernetes/k3d/local.sh deploy

# 기반 서비스 하나만 갱신
bash deploy/kubernetes/k3d/local.sh deploy --component mlflow
```

Harbor는 [독립 설치](../docs/deployment/image_registry.md)하며 `all`에 포함하지 않는다.
기존 외부 DB·S3·Prefect·MLflow·OpenMetadata를 연결하면 해당 설치 단계를 생략한다.
기존 `--modules`·`--features` 선택은 제거했다. 두 실행 구성을 나누지 않는다.

## 파일을 읽는 순서

```text
kubernetes/
  deploy.sh                 단일 입력·렌더링·배포 순서·검증
  base/
    teoria/                 API·UI·Runtime·정책·Worker·권한·Job
    services/               기반 서비스·소유 초기화 Job
    domains/                물품·법령 Worker·도메인 Flow 등록 Job
  overlays/                 generic·k3s·k3d 환경 차이
  base/teoria/web_proxy/     UI의 API·운영 화면 프록시
  prefect/                  pool·queue·실행 Job 정책
  harbor/                   독립 Harbor Helm release
  k3d/                      개발 클러스터·원격 접속 관리
  connections.env.example   연결 주소·도메인 실행 설정 예시
```

`base/teoria/kustomization.yaml`이 공통 플랫폼을 조립하고, `overlays/`는 저장소·Ingress 차이를 적용한다.
기능 조합용 `profiles/`와 별도 배포 스크립트는 제거했다.
초기화·migration·등록 Job의 실행 순서는 `deploy.sh`가 관리한다.

## 데이터와 운영 설정

연결 주소와 도메인 실행 설정은 [connections.env.example](kubernetes/connections.env.example)을 따른다.
ConfigMap 이름 `teoria-mlops-connections`는 기존 연결 설정을 보존하기 위해 유지한다.
비밀번호·토큰은 역할별 Secret, 데이터는 PVC·객체 저장소에 둔다.
기존 ConfigMap을 기본값으로 덮어쓰거나 PVC·DB 이력을 자동 삭제하지 않는다.

규격서 처리·법령 수집과 특정 DB의 메타데이터 정기 동기화는 기본 비활성화다.
원천·인증·산출물 저장소를 준비하고 운영 설정을 변경한 뒤 `deploy`를 실행해 활성화한다.
AI/AIP 실행 기능은 미구현이다.

## 클러스터 정지와 시작

```bash
bash deploy/kubernetes/k3d/local.sh stop
bash deploy/kubernetes/k3d/local.sh up
```

`stop`은 개발 클러스터·원격 프록시를 정지하고 컨테이너와 데이터를 유지한다.
`up`은 기존 설치를 다시 시작한다. 새 코드 적용은 이미지 준비와 별도 `deploy`가 필요하다.

[상세 준비·배포 순서](../docs/deployment/kubernetes.md) · [k3d](../docs/deployment/k3d.md) ·
[k3s 운영](../docs/deployment/k3s.md) · [Harbor](../docs/deployment/image_registry.md)

공통 정의와 환경 차이는 [Kustomize base·overlay](https://kubernetes.io/docs/tasks/manage-kubernetes-objects/kustomization/)로 관리한다.
[Palantir Architecture Center](https://www.palantir.com/docs/foundry/architecture-center/overview/)의 기능·서비스 책임 구분을 참고하며
Teoria의 현재 구현과 운영 도구를 유지한다.

이미지 빌드 입력은 `deploy/image_builds/`에 두며, Python·UI 이미지는 소유 프로젝트의 Dockerfile을 사용한다.
빈 환경의 설치와 도메인 활성화는 [최초 설치 절차](../docs/deployment/bootstrap.md)를 따른다.
