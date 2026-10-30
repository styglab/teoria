# Compose 배포와 운영

Teoria는 공통 기반에 MLOps, Metadata·Ontology, FormatID를 조합한다.
명령은 저장소 루트에서 실행하며 `deploy/compose/deploy.sh`가 구성 선택·실행 순서·종료를 관리한다.
셸 진입점은 Python 표준 라이브러리만 사용하는
[Compose 배포 진입점](../../backend/src/teoria/entrypoints/compose_deployment.py)을 호출한다.
K3s는 [별도 절차](k3s.md)를 사용한다. 아래 Compose 구성 검증을 실제 서비스나 EC2 배포 성공으로 기록하지 않는다.

## 구성 선택

| 선택 | 추가되는 상시 서비스 | 목적 |
|---|---|---|
| `core` | 공통 서비스 10개 | Web·Admin API·정책, Data/Application PostgreSQL, MinIO, Prefect·Redis |
| `mlops` | 4개 | MLflow, 학습/평가·배포 Worker, 데모 추론 API |
| `semantic` | 6개, 진단 활성 시 +1개 | Runtime·캐시, OpenMetadata·검색·ingestion Worker, 법령 Worker·선택형 진단 Worker |
| `formatid` | 1개 | FormatID 규격서 전용 Worker·파서·Codex 실행 |
| `--all` | 공통 포함 21개, 진단 활성 시 22개 | 위 세 기능을 모두 실행 |

`compose.yaml`은 공통 기반, `compose_mlops.yaml`, `compose_semantic.yaml`,
`compose_formatid.yaml`은 기능별 서비스와 Admin API 설정을 추가한다.
공통 서비스는 같은 Compose 프로젝트에서 한 번만 생성한다.
MLOps에는 모델 서빙이 포함되며 OpenMetadata·Semantic Runtime을 요구하지 않는다.
기본·MLOps Admin 이미지는 Codex CLI를 포함하지 않고, Semantic·FormatID는 작성용 이미지로 확장한다.
공통 Data DB migration도 파서·Codex가 없는 operations 이미지를 재사용한다.
FormatID는 Admin API의 Ontology·사전·프로파일 작성 기능을 사용하지만
OpenMetadata·Semantic Runtime 컨테이너를 강제로 실행하지 않는다.

서비스를 선택하면 API 활성화, 화면 메뉴, 허용된 Prefect Workflow 목록도 같은 구성으로 맞춘다.
기존 코드 경로 `specification_processing`, API URL, Flow·배포 ID는 보존한다.
LLMOps는 향후 요구·기존 MLflow 활용 범위를 확인한 뒤 추가하며 빈 실행 구성을 미리 만들지 않는다.

## 최초 준비와 배포

Docker Engine, Docker Compose v2와 Python 3.11 이상이 필요하다. 별도 Python 패키지는 설치하지 않는다.
이미지 빌드는 Buildx의 `--builder` 지원이 필요하다.
Teoria 전용 BuildKit은 `moby/buildkit:v0.30.0`으로 고정한다. 현재 서버의 구형 커널에서
최신 runc의 `/proc/acpi` 마스킹 오류가 발생해 검증한 호환 버전이다. 호스트 커널을 갱신한 뒤 재검토한다.
[설정 안내](configuration.md)에 따라 `deploy/compose/.env`를 준비한다.
비밀값은 Git에 저장하거나 `docker compose config`의 전체 출력으로 공개하지 않는다.

```bash
# 서비스·작업 이름만 표시한다. 해석된 비밀값은 출력하지 않는다.
bash deploy/compose/deploy.sh config --modules mlops
bash deploy/compose/deploy.sh config --modules semantic,formatid
bash deploy/compose/deploy.sh config --all

# 필요한 이미지만 명시적으로 빌드한다. 기존 릴리스 이미지가 있으면 생략한다.
bash deploy/compose/deploy.sh build --modules mlops

# 준비된 이미지로 초기화·migration·등록과 서비스를 실행한다.
bash deploy/compose/deploy.sh deploy --modules mlops

# 전체 기능을 사용할 때는 build와 deploy 모두 같은 구성을 지정한다.
bash deploy/compose/deploy.sh build --all
bash deploy/compose/deploy.sh deploy --all
```

위 명령들은 서로 다른 구성의 예시다. 같은 프로젝트에서 다음 예시로 전환하려면
아래의 구성 변경 절차를 따른다. 환경 파일을 바꿔 사용할 때는 각 명령에
`--env-file /absolute/path/to/.env`를 지정한다.
프로젝트 이름은 기본 `teoria`이며 기존 운영 프로젝트 이름을 유지한다.
필요한 경우 모든 명령에 동일한 `--project-name`을 사용한다.

공통 Admin/Runtime/정책 credential, PostgreSQL, Prefect, MinIO 계정을 준비한다.
MLOps는 MLflow DB 암호·데모 추론 token, FormatID는 별도 API/Worker 저장소 secret,
Semantic은 Runtime token·법령 Provider key가 필요하다. 빠진 필수 값은 배포 전 검사한다.
MinIO의 관리자 계정과 FormatID의 API·Worker 계정은 구분한다.

Semantic Runtime에는 승인·게시된 immutable artifact가 기존 `runtime-artifacts` 볼륨에 있어야 한다.
코드 배포가 Ontology를 자동 승인·게시하지 않으며 배포 시 active artifact checksum을 검사한다.
[Runtime 게시·이관](../platform/runtime.md)을 따른다.
FormatID Codex 인증은 `specification-model-auth`, 자산 진단 인증은 `metadata-model-auth`에 준비한다.
`TEORIA_ASSESSMENT_ENABLED=true`일 때만 진단 API와 전용 Worker를 함께 활성화한다.
이 Worker는 내부 `assessment` 프로필을 사용하며 별도 사용자 구성으로 선택할 필요는 없다.
모델 CLI 인증이 없는 상태의 컨테이너 기동을 AI 추출·진단 성공으로 간주하지 않는다.

## 초기화 작업

작업은 `jobs` 프로필에 두며 일반 `up`에 포함하지 않는다.
배포 명령이 다음 단계를 순서대로 실행한다.

1. DB·MinIO·Redis·선택한 검색 엔진을 시작하고 healthcheck를 기다린다.
2. DB 계정·권한, Data/Application migration과 OPA 서명 정책을 준비한다.
3. 선택 기능의 bucket·계정, OpenMetadata migration·권한, Runtime artifact를 확인한다.
4. API·Prefect·선택한 관리 서비스를 시작한다.
5. 선택 기능의 Prefect Flow만 등록하고 인증 API·실제 기능 flag·Runtime checksum·MLflow 연결을 확인한 후 Worker를 시작한다.

작업은 `run --rm --no-deps`로 실행하고 오류가 나면 다음 단계로 진행하지 않는다.
로그는 `deploy/compose/.state/<project>/logs/`에 접근 권한 600으로 저장한다.
작업 컨테이너는 제거하고 실패 원인과 종료 코드는 배포 명령에서 확인한다.
운영 데이터·로그를 출력할 때 인증정보·민감한 입력이 없는지 확인한다.

DB migration은 기존의 순번·이력·역할 분리를 유지한다. 현재 Application/Data migration 묶음은
공통 적용하므로 기능을 선택하지 않아도 관련 테이블이 존재할 수 있다.
선택하지 않은 기능은 등록·실행하지 않는다는 의미이며, 스키마까지 개별 설치하는 기능은 아니다.
이미 적용한 SQL을 수정하거나 기능 비활성화 때문에 테이블·원본·결과를 삭제하지 않는다.

## 상태, 재시작과 종료

성공한 배포는 구성과 현재·직전 이미지 ID를 `deploy/compose/.state/<project>/deployment.json`에 저장한다.
아래 명령은 저장된 선택을 그대로 사용한다. 상태 파일은 checkout과 함께 보존한다.

```bash
bash deploy/compose/deploy.sh status
bash deploy/compose/deploy.sh stop
bash deploy/compose/deploy.sh start
bash deploy/compose/deploy.sh down
```

- `start`: 준비된 구성의 기존 이미지를 사용한다. 빌드·migration·Flow 재등록을 하지 않는다. 설정이 바뀌었으면 `deploy`를 요구한다.
- `stop`: 신규 요청 진입을 막고, 소유 Prefect pool·schedule을 멈춘 뒤 실행 중 Flow 종료를 기다려 중지한다.
- `down`: 같은 중지 절차 후 선택한 서비스의 컨테이너·네트워크를 제거한다. 볼륨·이미지는 보존한다.
- `deploy`: 변경된 이미지·초기화·등록을 반영하며, 성공한 배포 뒤 이미지 정리를 수행한다.

유지보수 전 pool·schedule의 기존 pause 상태를 기록하고 재개 시 복원한다.
관리자가 원래 멈춰둔 예약은 임의로 재개하지 않는다. 선택에서 빠진 기능은 계속 멈춰둔다.
현재 API에서 비활성 기능 실행을 받지 않아도 Prefect에 남은 배포는 별도로 관리해야 한다.
진단 Worker는 새 작업 claim을 멈추고 현재 작업 완료 후 종료한다(최대 600초 대기).
Worker와 API·제어 서비스를 먼저 종료한 뒤 DB·검색·객체 저장소를 중지한다.
Prefect 종료 대기 기본값은 300초이며 `--timeout`으로 조정한다.
진행·대기·취소 중·일시정지된 Flow가 남아 있으면 강제 취소하지 않고 중단한다.
실행을 확인·완료한 뒤 다시 시도한다. API/Prefect에 연결할 수 없는데 Worker가 실행 중이면 종료를 중단한다.

기존 전체 스택을 처음 이 구조로 전환할 때는 현재 이미지가 새 API 설정·유지보수 모듈을
지원하는지 먼저 확인한다. 구형 API가 실행 중이면 이전 절차로 pool·예약·작업을 점검해 종료한 뒤
새 이미지로 배포한다. `.state`가 없는 기존 환경을 준비 완료로 자동 추정하지 않는다.

구성 변경은 기존 구성으로 `down`한 다음 새 선택으로 배포한다.

```bash
bash deploy/compose/deploy.sh down
bash deploy/compose/deploy.sh deploy --modules semantic,formatid
```

선택에서 제외한 기능의 DB·파일·인증 볼륨은 그대로 남는다.
자동 시작 정책이나 별도 배포 자동화가 서비스를 재개하지 않도록 운영 설정도 함께 확인한다.
`--profile '*' up`은 도구·MCP·초기화까지 실행하므로 전체 기능 시작 명령으로 사용하지 않는다.

## 이미지와 캐시 정리

Teoria가 빌드한 이미지에는 `io.teoria.project=teoria` 라벨을 붙인다.
새 배포의 준비 확인 후 현재·직전 성공 이미지, 다른 저장된 프로젝트의 보존 이미지,
실행·중지 컨테이너가 참조하는 이미지를 제외한 Teoria 이미지만 제거한다.
선택하지 않은 모듈의 태그 있는 준비 이미지도 보존한다. 태그 없는 이전 이미지도 전체 조회해 검사한다.
라벨 없는 과거 이미지나 다른 프로젝트의 이미지를 이름 추측으로 지우지 않는다.

```bash
# 삭제 예정 목록만 확인
bash deploy/compose/deploy.sh cleanup
# 동일 기준으로 삭제
bash deploy/compose/deploy.sh cleanup --apply
```

빌드는 전용 Buildx builder `teoria`를 사용한다. `buildkitd.toml`은 캐시 GC 기준을
5GB 보존·20GB 사용량·10GB 여유 공간으로 설정하고, 빌드 뒤 오래된 캐시 정리도 실행한다.
GC는 즉시 적용되는 디스크 hard limit이 아니다. 서버 공용 default builder 캐시는 자동 삭제하지 않는다.
볼륨·게시 artifact·원본·모델 인증정보는 이미지 정리 대상이 아니다.
`down -v`, 전역 `docker system prune`을 정상 종료 절차에 넣지 않는다.

## 접속과 백업

| 대상 | 기본 주소 |
|---|---|
| Web | `http://localhost:8081/` |
| Admin API | `http://localhost:8081/admin-api/docs` |
| Runtime API — Semantic 선택 | `http://localhost:8081/runtime-api/docs` |
| Prefect | `http://localhost:8081/prefect/` |
| MinIO 객체 브라우저 | `http://localhost:8081/minio/` |
| MLflow — MLOps 선택 | `http://localhost:8081/mlflow/` |

외부 공개는 nginx를 사용하고 내부 DB·S3 API 포트를 별도로 노출하지 않는다.
Admin API는 bearer 인증을 유지한다. MinIO 브라우저는 MinIO 계정, MLflow 공개 경로는 Prefect 운영 인증을 사용한다.
MLflow는 `platform-postgres` 인스턴스를 공유하며 전용 `mlflow` DB·계정을 사용한다.
MLOps 배포의 `mlflow-postgres-init` Job이 DB·제한된 계정을 준비하며 기존 DB를 삭제하지 않는다.
모델 파일은 MinIO에 유지한다. 메타데이터 진단·법령은 Semantic, OPA·정책 제어 서버는 공통 구성에 유지한다.

기존 전용 PostgreSQL에서 전환할 때는 MLflow와 학습·배포 Worker를 중지하고,
기존 `mlflow` DB를 `pg_dump -Fc`로 백업한다. `mlflow-postgres-init` 실행 후
비어 있는 대상 DB에 `pg_restore --no-owner --no-acl --role=mlflow`로 복원한다.
테이블·행 수와 주요 이력을 검증한 뒤 새 MLflow를 시작한다.
기존 `mlflow-postgres` 볼륨은 복구용으로 보존하며 자동 삭제하지 않는다.
이 절차 없이 다른 환경의 기존 볼륨이 자동 이관되지는 않는다.

```bash
bash deploy/compose/postgres/backup.sh
```

DB 백업 기준은 [Data DB 운영](../pipelines/database.md), 게시 artifact는 [Runtime](../platform/runtime.md),
FormatID 실행은 [파이프라인](../procurement_specification_processing/pipeline.md),
Metadata ingestion은 [수집 안내](../pipelines/openmetadata.md)를 따른다.
객체 저장소의 원본·산출물, 모델·인증 볼륨은 PostgreSQL 백업과 별도로 보존한다.

## CPU·메모리 예산

모든 서비스·일회성 작업은 CPU·메모리 상한을 명시한다. Worker와 Redis의 역할별 제한,
Data/Application DB 분리와 volume 이름은 기존 값을 유지한다.
리소스 제한이 실제 데이터·최대 부하에서 충분한지는 운영 환경에서 별도로 측정한다.

```bash
python3 -m unittest discover -s deploy/compose/tests -v
uv run --project backend --locked --all-extras --group orchestration pytest backend/tests/entrypoints/test_compose_deployment.py backend/tests/integrations/prefect/test_maintenance.py
bash deploy/compose/deploy.sh config --all
```

검사는 8가지 모듈 조합의 의존성·활성화 상태·볼륨 경계와 배포 순서·실패 중단을 확인한다.
설정·모의 실행 검사 통과가 실제 Docker 기동·AI 작업·모델 서빙 성공을 대신하지 않는다.
