# 개발 Harbor·MLOps 실제 검증

2026-11-12 UTC, 원격 Docker를 사용하는 Devcontainer에서 새 k3d `teoria` 클러스터를 생성해 검증했다.
기존 호스트의 다른 서비스·DB는 변경하지 않았다. 검증 checkout에는 미커밋 변경이 포함돼 있으며 운영 릴리스가 아니다.
아래 상태는 검증 시점의 개발 환경 기록이다.

## 설치와 연결

| 항목 | 실제 결과 |
|---|---|
| Kubernetes | 단일 노드 k3d / K3s v1.35.5+k3s1, Ready |
| Harbor | Helm chart 1.19.4 / Harbor 2.15.4, 전체 Pod Ready |
| Harbor 저장소 | registry 100Gi·DB 5Gi·Redis 1Gi·job log 1Gi, PVC Bound |
| Harbor 프로젝트 | private `teoria`·`models` |
| 계정 | 플랫폼/모델 publisher, 플랫폼/모델 pull, 모델 조회 Robot 5개 분리 |
| Teoria MLOps | Admin API·UI·Prefect·Worker·PostgreSQL·Redis·MLflow·MinIO 기동 |
| 이미지 연결 | 조회용 Robot의 프로젝트 목록·태그·digest 조회, pull용 Robot으로 실제 Pod 실행 |
| 인증·TLS | Teoria 미인증 요청 401, Harbor·플랫폼 CA 검증 유지 |

Docker 호스트 기준 Harbor는 `https://harbor.teoria.localhost`, 플랫폼은
`https://teoria.localhost:18443`이다. 기존 호스트의 8080 포트 점유 때문에 플랫폼 HTTP는 18080,
HTTPS는 18443으로 선택했다. Harbor 443과 Kubernetes API 6550은 loopback에 바인딩한다.
외부 네트워크에 개발 Admin을 공개하지 않는다. 로컬 인증서는 브라우저 신뢰 저장소에 별도로 등록한다.
접속 주소는 `.local/access.json`, 현재 Devcontainer용 환경변수는 `.local/session.env`에 보관한다.
이 환경에서는 `source deploy/kubernetes/k3d/.local/session.env` 후 관리 명령을 실행한다.

Devcontainer는 `k3d-teoria` Docker 네트워크에 연결하고 전용 kubeconfig의 API를
`https://k3d-teoria-server-0:6443`으로 설정했다. 노드·Pod·Docker 호스트 모두 Harbor public URL에
접근하고 CA를 검증한다. 이미지 저장소 요청을 Teoria 프록시로 우회하지 않는다.

인증정보는 Git에서 제외한 `deploy/kubernetes/k3d/.local/credentials.json`과 Kubernetes Secret에만 둔다.
Harbor 관리자는 `admin` / `harbor_admin` 값, Teoria bearer token은 `admin_token`,
Prefect·MLflow UI 운영 계정은 `teoria` / `prefect_password` 값이다. 이 파일 내용을 문서·로그에 복사하지 않는다.
로컬 Robot은 생성일 기준 90일 유효하며 재발급 시 Secret·반입 PC의 인증도 함께 갱신한다.

## 이미지 반입과 실제 실행

`backend/tests/fixtures/model_execution/`의 독립 검증 이미지를 빌드했다.
MLflow 의존성만 있는 기본 이미지로 합성 선형 회귀를 학습하며 Teoria·Prefect 패키지가 없음을 확인했다.
이 fixture는 운영 배포·Registry 계약에 자동 등록하지 않으며 검증 요청에서만 명시적으로 선택한다.

이미지를 `docker save`로 약 792MiB 파일로 내보내고 파일 SHA256 확인 → `docker load` →
모델 publisher로 Harbor push를 수행했다. Teoria는 게시된 manifest를 검증해 다음 참조를 반환했다.

```text
harbor.teoria.localhost/models/linear-validation@sha256:26864ef85e4697ff92b989d6aebb5524d04cfea70ed9e48d16ffae954076e507
```

| 검증 단계 | 결과 |
|---|---|
| 모델 `linear_validation_dd5bf822` 학습 2회 | Prefect COMPLETED, MLflow v1·v2 생성 |
| 데이터·결과 무결성 | 입력 SHA256 확인, 모델 checksum·MLflow run 연결 검증 |
| 산출물 | MinIO 결과 JSON·학습 로그 보존 확인 |
| v1 서빙 | 입력 x=[3,4] → [7,9] |
| v2 전환 | 같은 입력 → [12,14] |
| 실패 후보 | 종료 코드 1인 후보를 제출, 해당 Flow는 의도한 FAILED |
| 실패 후 복구 | 기존 v2의 [12,14] 응답 유지 |
| 이전 설정 재배포 | v1로 복원, [7,9] 응답 확인 |

검증용 `validation-dd5bf822` 서빙은 v1로 실행 중이다. endpoint는 내부 전용이며 추론은 인증된
Teoria Admin API를 거친다. 모델 Pod에는 플랫폼 Admin/Prefect credential과 ServiceAccount token을 주지 않는다.
학습 Job은 완료 후 정리됐고 MLflow 모델·Prefect 이력·MinIO 산출물은 유지했다.

## 발견해 수정한 설정

- 오래된 Docker 기본 frontend가 backend Dockerfile의 heredoc을 해석하지 못해 frontend 1.7.0을 명시했다.
- 실제 이미지 push가 Traefik 기본 read timeout으로 HTTP 499가 되어 HTTPS read/write timeout을 3600초로 조정했다.
- MLflow가 readiness의 Pod IP Host와 모델 namespace의 Service DNS를 거부해 고정 probe Host와 허용 내부 DNS를 설정했다.
- Worker의 학습 결과 읽기·로그 쓰기 계정 연결을 추가했다. 모델용 계정과 분리해 최소 bucket 권한을 적용했다.
- MinIO·mc는 Docker 호스트에 확보된 고정 버전 이미지를 노드에 적재했다. 노드의 외부 Quay 접근에 의존하지 않았다.

## 재현과 남은 범위

[Harbor 설치·반입](image_registry.md)과 [모델 실행](model_execution.md)에 따라 환경을 준비한 뒤
검증 이미지와 합성 데이터만 사용하는 opt-in 검사를 실행한다. credential 환경변수는 보안 파일에서 주입하고
셸 이력·명령 인수에 직접 넣지 않는다.

```bash
# TEORIA_TEST_MLOPS_URL, TEORIA_TEST_MLOPS_TOKEN, TEORIA_TEST_MLOPS_CA_FILE,
# TEORIA_TEST_S3_ENDPOINT, TEORIA_TEST_S3_ACCESS_KEY, TEORIA_TEST_S3_SECRET_KEY 설정.
TEORIA_TEST_MLOPS_K3D=1 uv run --project backend --locked --all-extras --group orchestration \
  pytest backend/tests/integration/test_mlops_harbor_k3d.py -q -s
```

기본 검사는 마지막에 서빙을 중지한다. 명시적인 `TEORIA_TEST_KEEP_SERVING=1`로 검증용 서빙을 남길 수 있다.
`TEORIA_TEST_MLOPS_REPORT`를 비공개 파일 경로로 지정하면 credential 없는 실행 결과 JSON을 보관한다.

실제 검사는 1개 통과(114초)했다. 전체 백엔드 검사는 1,398개 통과·102개 선택적 검사 skip,
Compose 설정·문서 검사는 32개 통과했다. 수십 GB 전송·완전 폐쇄망 설치·GPU·장애 후 전체 클러스터 복구·
운영 K3s/일반 Kubernetes는 검증하지 않았다. Semantic·MLOps 결합 설치 제한도 유지한다.

## 원격 IP 진입 전환

후속 원격 접속 구성은 기존 클러스터를 재생성하지 않고 적용했다.

| 대상 | 현재 외부 주소 |
|---|---|
| Teoria | `https://211.218.17.11:18443` |
| Harbor | `https://211.218.17.11:18444` |

`deploy/kubernetes/k3d/remote_access.sh`에서 주소와 포트를 관리한다.
실제 파라미터는 `.local/remote_access/config.json`, proxy 설정은 같은 폴더의 `nginx.conf`에 보관한다.
`teoria-k3d-remote-access` 컨테이너가 지정 IP의 두 HTTPS 포트만 게시한다.
서버 UFW에는 해당 목적지 IP의 TCP 18443:18444 허용 규칙을 추가했다. 기존 다른 서비스의 443은 유지했다.

Harbor 공개 URL·Teoria 조회 URL·Registry 허용 목록·pull Secret·노드 TLS 설정을 함께 갱신했다.
새 이미지 참조는 `211.218.17.11:18444/models/...@sha256:...`이며 기존 내부 이미지 참조도 허용한다.
프록시는 외부 연결과 내부 upstream 연결 모두에서 인증서를 검증한다.
Harbor는 실제 IP Host를 받아 브라우저 CSRF·세션 검사를 수행하고 Teoria bearer 인증도 유지한다.

Windows에서 `.local/remote_access/tls/ca.crt`를 다운로드해 현재 사용자의 신뢰할 수 있는 루트 인증 기관에 등록한다.
PowerShell에서 한 번 등록할 수도 있다. 이 명령은 Windows 사용자 PC에서 실행한다.

```powershell
Import-Certificate -FilePath .\ca.crt -CertStoreLocation Cert:\CurrentUser\Root
```

이후 IP 주소로 접속하며 hosts 변경이나 SSH 터널은 필요 없다.
계정·토큰은 기존 `.local/credentials.json`의 값을 유지한다.

공인 IP 경로의 두 웹 화면 200 응답, Harbor 브라우저 로그인·cookie 세션, Teoria 미인증 401,
Harbor 프로젝트 조회·토큰 교환·digest 확인, Docker의 새 Registry 주소 로그인을 실제 검증했다.
전체 백엔드 검사 1,408개 통과와 새 IP 진입 단위 검사 10개 통과를 확인했다.
외부 IP 브라우저·인증 opt-in 검사는 1개 통과했다.
실제 Windows PC에서의 마지막 네트워크 구간은 사용자 접속으로 확인해야 한다.

초기 설정 갱신 중 Worker 재시작과 겹친 검증 실행은 취소 상태로 정리하고 완료된 Job을 제거했다.
Worker 재시작 시 실행을 자동 인계하는 기능은 추가하지 않았으며 적용 전에 진행 중인 실행이 없어야 한다.

최종 IP 진입 경로의 실제 학습·서빙 검사는 1개 통과(112초)했다.
검증 모델은 `linear_validation_e610e708`, 서빙은 `validation-e610e708`이며 v1로 복원한 상태다.
새 주소로 학습 2회·서빙 전환·실패 후보 복구·롤백과 MinIO 결과·로그 보존을 다시 확인했다.
credential 없는 상세 결과는 `.local/public_validation_report.json`에 보관했다.

## MLOps 배포 수명주기 분리 검증

후속 변경에서 `database`·`storage`·`workflow`·`mlflow`·`platform` 배포 단위를 분리했다.
기본값은 `platform`이며 전체 최초 설치는 `--component all`을 명시한다.
리소스 이름·namespace·PVC·계정·게시 이력을 유지했고 기존 클러스터를 재생성하지 않았다.

현재 k3d에서 `local.sh deploy --modules mlops --component platform`을 실제 실행했다.
PostgreSQL·Prefect Redis·Prefect Server·Prefect Services·MinIO·MLflow 여섯 기반 리소스의
UID·Pod template SHA256이 배포 전후 동일함을 확인했다. 관리자 DB 초기화·저장소 초기화는 실행하지 않았다.
Teoria API·Worker는 운영 ConfigMap의 주소로 연결하고 Application DB migration·Teoria Flow 등록을 수행했다.

전체 백엔드 검사 1,413개 통과·103개 선택적 검사 skip, 배포 단위 검사 22개 통과를 확인했다.
분리 후 실제 학습 2회·서빙 전환·실패 후보 복구·롤백·검증 서빙 중지 검사는 1개 통과(110초)했다.
이 검사의 상세 결과는 `.local/component_validation_report.json`, 기반 리소스 비교는
`.local/lifecycle_baseline.json`에 보관한다. 기존 검증용 서빙과 외부 IP 접속은 유지했다.

`all` 조립은 독립 배포 단위의 리소스 합집합·중복 없음과 generic/K3s/k3d 렌더링으로 검증했다.
수명주기 분리 이후 빈 클러스터 최초 설치와 조직의 외부 DB·S3·Prefect·MLflow 연결은 별도로 검증해야 한다.
Semantic 배포 경로의 기반 서비스 분리는 이번 MLOps 변경 범위에 포함하지 않았다.

## 배포 디렉터리 정리 검증

독립 서비스의 정의·초기화 Job을 `base/services/<service>/`, Teoria MLOps 정의·Flow 등록 Job을
`base/mlops/`에 모았다. 모델 실행 namespace/RBAC는 `base/mlops/model_execution/`이 소유한다.
Prefect·Platform PostgreSQL은 기존 Semantic 조립에서도 같은 서비스 정의를 재사용한다.
OpenMetadata Server·전용 검색·schema migration도 `base/services/openmetadata/`로 모았다.
Semantic의 검색 준비 → migration → 서버 시작 순서는 유지하며, 독립 component 선택은 아직 MLOps에 한정한다.
K3s Traefik 전역 설정은 Harbor release에서 분리해 `overlays/k3s/traefik_config.yaml`에 두었다.

변경 전후 generic·k3s·k3d의 Semantic 및 MLOps component별 21개 렌더링을 정규화해 비교했고,
생성되는 Kubernetes 객체가 모두 동일했다. 이번 파일 정리를 위해 실행 중인 서비스를 다시 배포하지 않았다.
실제 `status`·공인 IP HTTPS·Harbor 브라우저 로그인·Teoria Registry 조회·Docker 로그인을 확인했다.
기존 여섯 기반 서비스의 UID·Pod template도 유지됐다.

백엔드 1,416개 통과·103개 선택적 검사 skip, 배포·문서 검사 34개 통과,
Compose 설정·문서 검사 32개 통과를 확인했다. 일상 명령과 Compose 대응표는
[배포 시작 안내](../../deploy/README.md)를 따른다.


## 플랫폼 기능 선택 검증

`--features metadata,ontology,mlops`를 추가하고 공통 API·UI·선택 Worker·Runtime·모델 실행 권한·등록 Job의
정의를 `base/teoria/`에 모았다. `base/mlops/`는 기존 설치의 호환 조립 목록으로 유지한다.
Metadata·Ontology·MLOps의 일곱 기능 조합을 generic·k3s·k3d에서 렌더링하고 선택하지 않은
서비스·도메인 Worker·등록 Job이 포함되지 않는 것을 확인했다. 기존 21개 배포 구성의 객체도 유지한다.

API 기능 상태와 라우터·Workflow 목록, UI 메뉴·검토함의 비활성 기능 조회 차단을 검증했다.
격리 PostgreSQL 17 컨테이너에서 일곱 조합의 DB·소유 계정·반복 초기화를 확인했다.
배포 명령 모의 실행으로 migration·artifact 검증·OpenMetadata migration 순서,
기반 서비스 갱신 제외와 API 연결 검증 뒤 Worker 활성화를 확인했다.

백엔드 전체 검사 1,454개 통과·106개 skip 이후 최종 변경 관련 검사 93개 통과,
프런트엔드 176개 통과와 production build를 확인했다. Compose 설정과 문서 링크도 검사했다.
이번 기능 선택을 위해 현재 개발 클러스터를 재배포하지 않았다.
신규 기능 조합의 빈 클러스터 설치·외부 서비스 연결·운영 이관 성공을 주장하지 않는다.
사용법과 준비 조건은 [기능 선택 안내](kubernetes.md)를 따른다.

## base 소유권·프로필 분리 검증

`base/`에는 `teoria/`·`services/`·`domains/`만 남겼다.
기존 `application`·`infrastructure`·`execution`·`jobs`·`mlops` 폴더는 제거하고,
실제 리소스는 소유 위치로 옮겼으며 조립 목록은 `profiles/`에 둔다.
공통 API·UI 정의를 재사용하고 기존 Semantic API의 이미지·환경변수·artifact mount 차이만 프로필 패치로 유지한다.
수집 Worker는 goods·legal_information 도메인, 공통 실행 계정·권한·quota는 Teoria가 소유한다.
Data DB migration은 기존 통합 이관 진입점을 유지한다.

변경 전후 기존 CLI 21개·신규 기능 조합 21개의 렌더링을 비교해 총 42개 구성의 Kubernetes 객체가 동일했다.
배포·Registry·상태 관련 테스트 60개와 리소스 중복 정의·프로필 경계 검사 1개를 확인했다.
CI YAML과 shell 블록을 검사하고 기존 경로 대신 새 프로필·소유 위치의 모든 Job을 검사하도록 수정했다.
문서 링크·Bash 문법·diff 공백 검사도 수행했다.
현재 실행 중인 개발 클러스터는 재배포하지 않았고, 파일 이동을 운영 배포 성공으로 기록하지 않는다.

## 통합 Teoria·Kubernetes 전용 배포 검증

Metadata·Ontology·MLOps는 통합 구성 하나로 조립한다.
기능 조합 프로필·`features.sh`·`--modules`·`--features` 배포 선택을 제거했고,
기본 배포는 Teoria만, `--component all`은 기반 서비스까지 갱신한다.
도메인 API·Worker·선언된 일정과 원천별 Metadata 동기화 일정은 운영 ConfigMap으로 별도 활성화한다.
기존 ConfigMap·namespace·DB·PVC 식별자는 보존하며 초기화·migration·등록 순서를 공통으로 관리한다.

사용자가 제외한 `deploy/compose/`에 맞춰 전용 Python 배포·유지보수 코드·CI와 호환 검사를 제거했다.
OPA·OpenMetadata ingestion 빌드 입력은 `deploy/image_builds/`로 옮겼다.
Prefect 배포 정책은 Kubernetes만 지원하며, Metadata·모델 controller의 process pool은 Pod 안에서 계속 사용한다.
Devcontainer의 실행 구성은 서비스 배포와 별개다.

검증 결과:

- 백엔드 전체: 1,391개 통과·107개 선택적 검사 skip·3개 경고.
- 통합 배포·Registry·상태·API 검사 34개 통과 이후 도메인 활성화·이미지 빌드 목록 관련 최종 검사 5개 통과.
- 격리된 실제 Kubernetes API 서버에서 generic·k3s·k3d 전체 YAML의 server dry-run 통과.
- 격리 PostgreSQL 17에서 네 플랫폼 DB·소유 계정 생성과 반복 초기화 통과.
- Pipeline 계약 정적 검증, CI YAML·Bash 문법·문서 링크·diff 공백 검사 통과.

전체 검사 종료 시 Prefect 임시 서버의 닫힌 로그 stream 경고가 있었으며 pytest 종료 코드는 0이다.
이번 통합은 실제 Teoria 워크로드의 빈 클러스터 최초 설치·외부 서비스 연결·운영 이관 성공을 의미하지 않는다.
현재 개발 k3d 노드·로드밸런서·원격 프록시는 정지 상태로 유지했고 기존 데이터를 재배포·삭제하지 않았다.

## 2026-11-12 저장소·배포 구조 정리 후 검증

- 빌드 입력은 `deploy/image_builds/`, UI 프록시는 `base/teoria/web_proxy/`로 이동했다.
  CI·로컬 빌드·Dockerfile·검사 경로를 함께 갱신했다.
- 작업 배정 이미지와 규격서·법령 실행 이미지를 분리하고 metadata/model Worker를 non-root로 실행한다.
  별도 최소 의존성 환경에서 Pipeline CLI·Prefect Kubernetes 등록·모델 Flow·native HTTP executor import를 확인했다.
- Docker context matcher로 Kubernetes `.local`·비밀 env·kubeconfig·TLS 키·이미지 캐시 제외와
  애플리케이션·독립 파서 소스 보존을 확인했다. 빌드 입력 제외는
  [공식 `.dockerignore` 설명](https://docs.docker.com/build/concepts/context/#dockerignore-files)을 따른다.
- 규격서 서비스 토큰을 실제 조립 API에 전달해 전용 actor 인증, 허용 조회,
  Ontology 게시·메타데이터 접근·프로파일 상태 전이 차단을 확인했다.
  Prefect SDK의 Job 렌더링으로 역할별 Secret·Codex 마운트·이미지·non-root 설정 보존을 확인했다.
- 백엔드 전체 1,398개 통과·104개 선택적 검사 skip. 이후 추가한 저장소 preflight·공개 URL·context 검사와
  관련 배포/연동 검사 36개, 아키텍처/메타데이터/Codex 검사 38개도 통과했다. 수치는 중복 검사를 합산하지 않았다.
- 프런트엔드 177개·TypeScript/Vite 빌드, 문서 검사 9개·로컬 링크 263개가 통과했다.
- 별도 일회용 Kubernetes API 서버에서 generic·k3s·k3d 전체 manifest의 server dry-run을 확인했다.
  테스트 서버는 제거했다. 개발 k3d 노드·로드밸런서·원격 프록시는 정지 상태를 유지했다.
- 이 환경은 Docker Buildx 플러그인이 없어 변경 이미지의 실제 빌드는 실행하지 못했다.
  전체 신규 설치·실제 모델 추론·규격서 업로드/처리는 아직 검증 전이다.
  [최초 설치](bootstrap.md)에 따라 이미지·계정·S3·승인 artifact를 준비한 뒤 별도 실환경 검증이 필요하다.

## 2026-11-13 k3d 원격 접속의 설정·복구 정리

`remote_access.env.example`·`remote_access.conf.template`을 배포 폴더에 추가했다.
기준 입력은 `.local/remote_access.env`, 완료 기록은 기존 `remote_access/config.json`이며
기존 기록만 있는 환경도 읽는다. 일반 플랫폼·Harbor 갱신이 같은 주소를 사용하고,
미적용 입력·미완료 복구가 있으면 실제 배포를 중단한다.

`--check`는 Python 표준 라이브러리만 사용하는 오프라인 계획이며 상태를 쓰지 않는다.
`--apply`는 사전 검사·비공개 이전 값 기록·단계별 적용·HTTPS 확인 후 완료를 수행한다.
실패 시 변경한 값과 보관한 프록시를 복구하고, 복구 충돌·강제 종료는 `--recover`로 처리한다.
일반 플랫폼·Harbor 갱신과 주소 변경을 같은 잠금으로 직렬화했다.

검증 결과:

- 전체 백엔드 1,426개 통과·105개 선택적 검사 skip. 마지막 오프라인 wrapper 검사 추가 후 관련 검사 36개도 통과했다.
  중복 실행 수치는 합산하지 않았다.
- 단계별 실패·중단된 Helm 복구·커밋 중 오류·소유 값 충돌·다른 Registry/DB credential 보존을 검사했다.
- 별도 Docker 네트워크의 실제 Nginx에서 TLS 신뢰 검증·인증 전달·Host 보존·32MiB 스트리밍 업로드를 검증했다.
  프록시는 non-root·read-only·capability 제거 설정으로 실행했으며 테스트 컨테이너·네트워크·볼륨은 제거했다.
- 공통 UI Nginx도 격리 컨테이너로 경로 변환·API 인증·MLflow 접근 제어를 확인했다.
- 문서 테스트 9개와 로컬 링크 269개, Bash 문법·diff 공백 검사가 통과했다.

실제 개발 k3d와 원격 프록시는 정지 상태를 유지했다. 기존 접속 설정·Harbor·Secret에는 적용하지 않았다.
실제 Harbor image push/pull·수십 GB 전송·실환경 변경/복구는 이번 격리 검사로 검증했다고 기록하지 않는다.
[적용·연결 확인·복구 절차](k3d.md#원격-접속-변경과-복구)에 따라 별도 실행해야 한다.

이 기록의 `session.env`·`credentials.json`과 일회성 검증 스크립트는 구형 설치 산출물이다.
현재 입력과 보관 위치는 [k3d 파일 정리](k3d.md#local의-역할과-기존-파일-정리)를 따른다.
이관은 로컬 파일 정리이며 과거 검증 결과를 다시 실행한 것으로 간주하지 않는다.
