# Prefect 실행과 장애 대응

현재 Prefect는 명시적으로 입력한 규격서의 두 작업, 법령 전용 수집과 OpenMetadata 동기화를 관리한다.
이전 공고·계약·낙찰·개찰·업종 수집과 Backfill은 중단 상태다. 법령 작업은 독립 pool로 재개했다.
저장소의 선언값은 [배포 목록](deployments.md), 실제 운영 확인은 [배포 검증 기록](../../archive/documentation/verification/goods_focus_deployment_2026_10_25.md)을 따른다.

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
[상세 운영](domains/legal_information.md)과 [배포 목록](deployments.md)을 따른다.

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
[규격서 파이프라인](../procurement_specification_processing/pipeline.md)의 CLI를 사용한다.
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
uv run --locked --project backend teoria-pipelines deployment-docs --check docs/pipelines/deployments.md
```

운영 절차와 볼륨·인증은 [Compose](../deployment/compose.md), Metadata 격리는
[OpenMetadata Job](openmetadata.md)을 따른다.
