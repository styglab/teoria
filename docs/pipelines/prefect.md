# Prefect 실행과 장애 대응

현재 Prefect는 명시적으로 입력한 규격서의 두 작업, 법령 전용 수집과 OpenMetadata 동기화를 관리한다.
이전 공고·계약·낙찰·개찰·업종 수집과 Backfill은 중단 상태다. 법령 작업은 독립 pool로 재개했다.
배포 선언의 기준은 `backend/config/*/prefect_deployments.yaml`이다. 실제 등록·실행은 Prefect UI에서 확인한다.

## 실행할 Deployment 찾기

| Deployment | 입력 | 실행 방식 |
|---|---|---|
| `specification-standard-management` | `mode=standard_management`의 manifest | 수동 |
| `specification-standard-workflow` | 기준 프로파일 revision과 추출 입력의 workflow manifest | 수동 |
| `specification-document-processing` | `mode=document_processing`과 고정 표준을 포함한 manifest | 수동 |
| `openmetadata-postgres-metadata-sync` | 허용된 ingestion image | 매일 05:00 Asia/Seoul |

규격서 pool은 Compose `teoria-specification`, K3s `teoria-specification-k3s`다.
queue는 `documents`, 전체 동시 실행 상한은 기본 2개이며 각 Deployment는 중복 실행을 막는다.
Metadata는 별도 `teoria-metadata` pool에서 동시 실행 1개다.
이전 `teoria-ingestion` pool과 해당 배포는 이력을 보존한 일시정지 상태로 유지한다.

## 법령 전용 작업

`moleg-law-daily`와 `moleg-law-weekly-reconciliation`은
`teoria-legal-information` / `laws`에서 동시 실행 1개로 운영한다.
월~토 04:15 변경 동기화, 일요일 04:15 전체 연혁 보정이며 시간대는 Asia/Seoul이다.
일요일 법령 보정은 법령 저장소 전용이며 조달 Backfill을 재개하지 않는다.
등록은 `prefect-law-deploy`, 실행은 `prefect-law-worker`가 담당한다.
세부 수집 정책은 [법령 운영](domains/legal_information.md)을 따른다.

## 등록과 실행

```bash
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml -f deploy/compose/compose_formatid.yaml run --rm --no-deps prefect-deploy
```

등록 명령의 `--kind ingestion`은 기존 CLI 호환 이름이다. 현재는 규격서 작업만 등록한다.
공통 등록 정보는 `backend/config/specification_processing/prefect_deployments.yaml`과
`backend/config/metadata_management/prefect_deployments.yaml`이다. 환경별 Pool·Queue는
`deploy/compose/prefect/`와 `deploy/k3s/prefect/`에서 선택한다. 등록 명령은 공통 선언과 환경 설정을
합성한 Prefect YAML을 만들어 실제 `prefect deploy`에 전달한다. 원본 설정 파일은 수정하지 않는다.
자동화 등록은 과거 수집 pool을 재개하지 않는다.

Prefect UI의 규격서 Deployment에서 `manifest` 객체를 입력해 실행하거나,
[규격서 파이프라인](../domains/goods/specifications/pipeline.md)의 CLI를 사용한다.
배포된 Worker에서 로컬 문서를 처리하려면 컨테이너 기준의 입력·산출물 URI를 사용한다.
문서 처리 mode는 표준의 URI와 SHA-256을 반드시 고정한다.

## 실패 지점 찾기와 재개

1. Flow에서 원문 보관·파싱·추출·표준 처리·저장 중 실패한 Task를 확인한다.
2. parser, 모델 인증, 입력 URI·checksum과 객체 저장소 접근을 확인한다.
3. Data DB의 `specification_processing_runs` 상태와 산출물 참조를 함께 확인한다.
4. 같은 입력·코드에는 같은 `run_id`로 재개한다. 다른 입력이나 코드에는 새 `run_id`를 사용한다.

파일/S3 저장이 끝난 뒤에만 DB 완료 체크포인트를 기록한다. Flow의 Completed만으로
독립적인 추출 품질이나 Ontology 승인·게시를 보장하지 않는다.
추출 표준의 자동 채택은 미게시 draft이며, 사람 검토가 필요한 Ontology 게시와 다르다.

## Worker 재배포

새 이미지 빌드 → 대상 pool 일시정지 → 실행 중 작업 종료 확인 → 배포 등록 →
Worker 교체 → heartbeat·기동 검사 → 원래 pool 상태 복원 순서로 진행한다.
이번 전환으로 중단한 과거 수집 pool은 복원 대상이 아니다.
`up --no-deps`로 DB·다른 서비스를 불필요하게 교체하지 않는다.
기존 작업을 종료한 증거 없이 DB 상태나 checkpoint를 강제로 진행시키지 않는다.

```bash
docker compose -f deploy/compose/compose.yaml -f deploy/compose/compose_formatid.yaml logs --tail 100 prefect-worker
uv run --locked --project backend teoria-pipelines deployment-docs
```

운영 절차와 볼륨·인증은 [Compose](../deployment/compose.md), Metadata 격리는
[OpenMetadata Job](../deployment/openmetadata.md)을 따른다.

## MLOps 예제

공통 모델 목록·버전 조회는 `platform/mlops/`가 맡는다. 합성 고객 데이터·학습·품질 기준·서빙은
`examples/customer_churn/`에 격리한다. 예제는 명시적 수동 실행이며 일반 업무 모델로 간주하지 않는다.
`backend/config/model_operations/prefect_deployments.yaml`의 기존 배포 이름은 유지한다.
Compose의 학습 pool은 `teoria-model-training-docker`이며 Docker Worker가 요청마다
`TEORIA_MODEL_TRAINING_IMAGE`로 일회성 컨테이너를 생성한다. 실행 이미지에 코드·의존성을 포함하고,
CPU 2개·메모리 2GiB·동시 실행 1개로 제한한다. 실행 종료 후 컨테이너를 제거하며 로그는 Prefect로 보낸다.
Dispatcher만 Docker socket을 사용하고 실제 학습 컨테이너에는 socket·배포 token·release volume을 주지 않는다.
DB·Prefect 인증정보는 pool에 값으로 저장하지 않고 Worker 환경변수 참조를 실행 시 해석한다.
학습 이미지 참조는 MLflow run의 `teoria.training_image` tag에 기록한다.
기존 CLI의 `register --backend process`는 Compose 환경 선택값으로 보존하며, pool의 실행 type은 `docker`다.

서빙은 별도 `TEORIA_MODEL_SERVING_IMAGE`의 Compose 서비스다. 이미지 변경은 Compose 재배포로 반영한다.
모델 버전 변경은 기존 별도 배포 Worker가 release 참조를 원자적으로 전환하고 서버를 재시작한다.
checksum·readiness·인증된 예측을 검증하며 실패하면 이전 release를 복원한다.
`/live`는 서버 생존, `/health`는 모델 로딩 완료를 나타낸다. 최초 설치는 모델 없이 서버를 시작할 수 있다.
기존 Flow·배포 ID는 유지하고 구 process 학습 pool은 중지 대상으로 보존하며 재개하지 않는다.
K3s MLOps Job·서빙 배포는 아직 제공하지 않는다.

### 격리 Docker 통합 검증

별도 검증 tag로 이미지를 빌드한 뒤 아래 선택형 테스트를 실행한다.
이 테스트는 기존 운영 서비스에 연결하지 않고 PostgreSQL·Prefect·MLflow·Worker·추론 서버와
전용 네트워크·release volume을 만들고 종료 시 제거한다.

```bash
docker buildx build --builder teoria --target model-training --load -t teoria-model-training:validation -f backend/Dockerfile .
docker buildx build --builder teoria --target model-dispatcher --load -t teoria-model-dispatcher:validation -f backend/Dockerfile .
docker buildx build --builder teoria --target model-serving --load -t teoria-model-serving:validation -f backend/Dockerfile .
TEORIA_TEST_MLOPS_DOCKER=1 uv run --project backend --locked --all-extras --group orchestration --group docker-orchestration --group model-operations pytest backend/tests/integration/data_operations/test_customer_churn_docker.py -q
```

합성 데이터 준비 → 일회성 학습 → MLflow 등록 → 배포 subflow → 모델 준비·인증된 예측 →
학습 컨테이너 제거를 확인한다. Prefect는 검증용 SQLite, MLflow artifact는 컨테이너 내부 디렉터리를 사용하므로
운영 PostgreSQL·Redis·MinIO 구성 전체의 배포 성공이나 K3s 지원을 뜻하지 않는다.

2026-11-10에 전용 학습·Dispatcher·서빙 이미지 빌드와 위 Docker 통합 테스트를 통과했다.
실제 검증 범위는 격리 환경의 모델 버전 1 학습·등록·배포·인증된 예측·학습 컨테이너 제거이며,
운영 Compose 전체 배포는 수행하지 않았다.
