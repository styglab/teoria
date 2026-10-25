# Data DB와 migration

Teoria Data Pipelines가 수집 DB의 물리 schema와 migration을 소유한다. Semantic Platform은 Database Source Registry를 통해 정규 relation을 읽을 뿐 migration을 실행하지 않는다.

- `ingestion`: 실행 감사, 원본 Provider 응답, Checkpoint
- `public_procurement`: 현재 규격서 실행·문서별 상태·산출물 참조와 보존된 이전 조달 데이터

파일명은 적용 순서를 포함한 `<3자리 번호>_<설명>.sql`을 사용한다. 적용된 파일명은 `ingestion.schema_migrations`에 기록되므로 이미 적용한 migration 파일을 수정하지 않고 새 파일을 추가한다.

```bash
uv run --locked --package teoria-pipelines \
  teoria-pipelines migrate \
  --migrations pipelines/database/migrations
```

실행에는 `TEORIA_PIPELINE_DATA_DATABASE_URL`이 필요하다. 로컬 Compose에서는 `postgres-migrate` 일회성 서비스가 같은 명령을 실행한다.

## 규격서 실행과 참조

`090_specification_processing_runs.sql`의 세 테이블을 사용한다.
`specification_processing_runs`는 실행·표준 참조·완료 상태,
`specification_processing_documents`는 문서별 결과 요약,
`specification_processing_artifacts`는 URI·checksum·크기·미디어 유형을 저장한다.
원문·추출 본문·표준 본문은 파일/S3에 둔다. 완료 상태는 모든 산출물 저장 뒤 기록한다.
`091`은 Pipeline·Runtime role에 schema 사용 권한을 부여한다.

## 원본·관찰·정규 데이터

이전 Provider 원본·관찰·정규 데이터와 `ingestion.pipeline_runs`, checkpoint, 보강 큐는
과거 이력으로 보존한다. 현재 수집이 진행되거나 이 데이터가 모두 완전하다는 의미가 아니다.
새 규격서 작업의 상태를 이전 수집 실행 테이블에서 판정하지 않는다.
이번 전환에는 데이터 삭제·WAL 정리·디스크 회수를 포함하지 않는다.

migration은 적용된 파일을 수정하지 않고 새 순번으로 추가한다.
현재 처리·저장 계약은 [규격서 파이프라인](../procurement_specification_processing/pipeline.md),
실행·실패 대응은 [Prefect](prefect.md)를 따른다.
