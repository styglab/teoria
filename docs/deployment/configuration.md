# 환경 설정과 인증정보

배포 입력은 `deploy/kubernetes/`의 값 없는 예시와 소유 리소스를 기준으로 관리한다.
현재 실행 환경은 개발 k3d와 운영 k3s·일반 Kubernetes다. `deploy/compose/` 배포 경로는 제거했다.
[통합 배포](kubernetes.md)와 [개발 k3d](k3d.md)의 준비 순서를 따른다.

## 설정을 읽는 위치

| 대상 | 기준 위치 |
|---|---|
| Python 설정·기본값 | `backend/src/teoria/settings.py` |
| 일반 연결 주소·도메인 실행 여부 | `deploy/kubernetes/envs/dev/connections.env.example` → ConfigMap |
| 플랫폼·서비스 비밀값 | `deploy/kubernetes/envs/dev/secrets.env.example` → `teoria-secrets` |
| 모델 controller 비밀값 | `deploy/kubernetes/envs/dev/control.env.example` → `model-control` |
| 모델 Job·서빙 비밀값 | `deploy/kubernetes/envs/dev/workload.env.example` → `model-workload` |
| 규격서 처리 비밀값 | `deploy/kubernetes/envs/dev/specification.env.example` → `specification-processing` |
| Harbor 관리자·암호화 키 | `deploy/kubernetes/envs/dev/harbor_secrets.env.example` → `harbor-secrets` |
| Harbor Helm 입력 | `deploy/kubernetes/envs/dev/harbor_values.yaml.example`; 실제 YAML은 Git 제외 |
| k3d 호스트 입력 | `deploy/kubernetes/envs/dev/k3d.env.example`; `local.sh`가 실제 `k3d.env`를 자동으로 읽음 |
| 컨테이너 실행·Secret 주입 | `deploy/kubernetes/base/`의 소유 리소스 |
| 환경별 저장소·Ingress | `deploy/kubernetes/overlays/` |
| Prefect pool·queue·Job 정책 | `deploy/kubernetes/prefect/` |

API는 `bootstrap_settings()`를 통해 환경변수와 명시적 `TEORIA_ENV_FILE`을 읽는다.
운영 컨테이너는 호스트의 `.env`를 자동으로 읽지 않는다.
실제 비밀번호·토큰은 Git에서 제외한 `envs/dev`·`envs/prod` 또는 보안 운영 경로의 파일에서 준비한다.
위 표는 개발 예시 경로이며 운영은 같은 이름의 `envs/prod` 예시를 사용한다.

## 통합 플랫폼과 도메인 설정

Kubernetes 정의는 Metadata·Ontology·MLOps를 함께 활성화한다.
기능 조합용 `TEORIA_FEATURES`와 배포의 `--modules`·`--features`는 사용하지 않는다.
규격서 처리·법령 수집과 원천별 일정은 다음 ConfigMap 값으로 운영한다.

| 키 | 기본값 | 효과 |
|---|---|---|
| `TEORIA_SPECIFICATION_PROCESSING_ENABLED` | `false` | FormatID·물품 작성 API·규격서 Worker·선언된 일정 |
| `TEORIA_LEGAL_INFORMATION_ENABLED` | `false` | 법령 API·전용 Worker·선언된 일정 |
| `TEORIA_METADATA_SYNC_SCHEDULE_ENABLED` | `false` | Teoria Data DB 메타데이터 정기 동기화 |

값은 `true` 또는 `false`다. 입력·저장소·소유 API 인증·법령 키 등 해당 기능의 실행 조건을 준비한 뒤 활성화한다.
Teoria API·Runtime·정책 서비스·Worker·migration/등록 Job의 실행 환경은 같은 ConfigMap의 `TEORIA_ENVIRONMENT`로 정한다.
개발 예시는 `development`, 운영 예시는 `production`이며 클러스터 종류와 별개다.
기존 ConfigMap에도 이 키를 추가해야 새 Teoria Pod와 Job을 실행할 수 있다.

환경별 파일을 수정하고 `settings.sh apply --role connections`로 등록한 뒤 플랫폼을 배포하면 API와 Worker·Flow 등록에 함께 반영한다.
배포는 예시 파일을 자동 등록하지 않는다. 기존 ConfigMap의 필수 값을 검증하고 설정 revision을 통해 Pod 교체에 반영한다.

## DB·객체 저장소·Registry

`TEORIA_APP_DATABASE_URL`은 Teoria Application DB 전용 계정이다.
Data DB 수집·이관은 `TEORIA_PIPELINE_DATA_DATABASE_URL`, Runtime 조회는 `TEORIA_RUNTIME_DATA_DATABASE_URL`로 분리한다.
Platform PostgreSQL 관리 계정은 DB·계정 준비 Job에만 사용한다.
Prefect·MLflow·OpenMetadata는 각자의 DB와 계정을 사용하며 Teoria API가 내부 테이블을 직접 관리하지 않는다.
URL 안의 비밀번호는 URL-encode하고 DB 계정 암호와 일치시킨다.

모델 객체 저장소 계정은 controller와 workload로 분리한다. Job에는 허용한 저장소 credential만 전달한다.
OpenMetadata ingestion bot은 `OPENMETADATA_INGESTION_BOT_TOKEN`, 플랫폼 조회 연결은
`TEORIA_OPENMETADATA_AUTH_TOKEN`을 사용한다.

이미지 Registry는 [Harbor](image_registry.md)로 별도 운영한다. 플랫폼은 Registry 서버를 설치하지 않는다.
조회 계정과 이미지 pull·개발자 push 계정의 역할을 구분한다.

## API·Runtime·정책 인증

운영 Admin API는 `TEORIA_ADMIN_AUTH_MODE=bearer`와 `TEORIA_ADMIN_API_TOKEN`을 사용한다.
Runtime token은 `TEORIA_RUNTIME_API_TOKEN`, Context의 Runtime 호출 인증은 별도로 주입한다.
인증된 principal이 작성·검토·승인의 주체이며 요청 body의 actor·reviewer 문자열을 권위로 삼지 않는다.
개발용 disabled 인증을 외부로 노출하지 않는다.

Ontology Runtime은 checksum 검증된 게시 artifact만 적재한다.
`TEORIA_RUNTIME_ARTIFACT_STORE`는 versioned artifact 저장소이며 authoring YAML을 운영 fallback으로 읽지 않는다.
운영 의미 실행은 OPA를 사용한다. 정책 control-plane token·서명키·bundle은 API bearer token과 별도로 관리한다.
배포가 의미 정의를 자동 승인·게시하지 않는다.

## 자산 진단 Worker

진단 실행은 `TEORIA_ASSESSMENT_ENABLED`와 모델 인증을 별도로 준비한다.
Codex subprocess를 사용하는 소유 기능이며 AI/AIP 실행 플랫폼 구현을 뜻하지 않는다.
선택할 모델과 timeout은 `TEORIA_ASSESSMENT_CODEX_MODEL`·`TEORIA_ASSESSMENT_CODEX_TIMEOUT_SECONDS`로 관리한다.
모델 인증 자료는 전용 저장소로 주입하고 이미지·Git·로그에 넣지 않는다.

## 실행 자원 제한

API·DB·Worker의 CPU·메모리 requests·limits는 `deploy/kubernetes/base/`가 기준이다.
Pipeline Job 기본값·상한은 `deploy/kubernetes/prefect/execution.yaml`, 모델 실행 자원은
[모델 실행 계약](model_execution.md)을 따른다.
requests·limits와 quota는 해당 클러스터의 실제 자원·GPU·스토리지에서 별도로 검증한다.

## 개인·서비스 계정의 OIDC 토큰 검증

Admin API는 `TEORIA_ADMIN_AUTH_MODE=bearer`를 유지하면서 다음 설정으로
OIDC 제공자가 서명한 API access token을 검증할 수 있다.

| 환경변수 | 설정 |
|---|---|
| `TEORIA_ADMIN_OIDC_ISSUER` | 토큰의 정확한 HTTPS issuer |
| `TEORIA_ADMIN_OIDC_AUDIENCE` | Teoria Admin API에 할당한 audience |
| `TEORIA_ADMIN_OIDC_JWKS_URL` | 운영자가 고정한 HTTPS 공개 서명키 주소 |
| `TEORIA_ADMIN_OIDC_ROLES_CLAIM` | 역할 목록 경로. 기본 `roles`, 예: `realm_access.roles` |
| `TEORIA_ADMIN_OIDC_ROLE_MAPPING` | 외부 역할에서 Teoria 역할 목록으로의 JSON 매핑 |

매핑 예시는 `{"teoria_reviewers":["binding_reviewer"],"teoria_owners":["ontology_owner"]}`다.
기존 기본 관리자 역할을 토큰 사용자에게 부여하지 않는다. 매핑된 역할이 없으면 접근을 거절한다.
서명 알고리즘은 RS256으로 제한하고 issuer·audience·sub·exp·iat와 서명을 확인한다.
actor는 변경 가능한 표시명 대신 issuer와 sub로 구성하며 자동 작업도 고유 sub를 사용한다.

issuer를 설정하면 공용 Admin token으로 되돌아가는 인증 경로는 없다. Worker와 배포 검증
요청도 API audience를 가진 유효한 서비스 access token을 공급해야 한다. Kubernetes의 기존
`TEORIA_ADMIN_API_TOKEN` 필수 입력은 호환을 위해 유지하지만 OIDC 모드의 인증 근거가 되지 않는다.
ID token의 브라우저 client audience를 API audience로 지정하지 않는다.

OIDC 설정은 해당 환경변수를 Admin Deployment에
명시적으로 설정해야 한다. 제공자별 로그인 redirect·PKCE·서비스 토큰 자동 갱신은 아직 연결하지
않았으며 현재 관리자 연결창은 access token 입력을 사용한다. 실제 SSO 구성은 issuer·client와
역할 설정, 만료·키 교체·개인별 승인 기록을 해당 환경에서 확인한 뒤 완료로 기록한다.
OIDC 연결만으로 문서·속성 단위 접근 정책이나 작성자/승인자 분리가 완성되는 것은 아니다.

## 환경별 파일 위치와 반영

실제 비밀값은 `deploy/kubernetes/envs/dev/`·`prod/`의 역할별 `*.env` 또는 운영자 보안 경로에 둔다.
예시만 Git에 포함하며 실제 파일은 Git·이미지 빌드에서 제외한다.
[환경별 설정·인증정보 준비와 반영](../../deploy/kubernetes/envs/README.md)에 따라 초기화하고 context를 명시해 등록한다.
배포 YAML이 참조하는 기존 Secret 이름과 namespace는 변경하지 않는다.
