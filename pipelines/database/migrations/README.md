# Data database migrations

Teoria Data Pipelines가 수집 DB의 물리 schema와 migration을 소유한다. Semantic Platform은 Database Source Registry를 통해 정규 relation을 읽을 뿐 migration을 실행하지 않는다.

- `ingestion`: 실행 감사, 원본 Provider 응답, Checkpoint
- `public_procurement`: 정부조달 계약과 기관·공급자 정규 데이터

파일명은 적용 순서를 포함한 `<3자리 번호>_<설명>.sql`을 사용한다. 적용된 파일명은 `ingestion.schema_migrations`에 기록되므로 이미 적용한 migration 파일을 수정하지 않고 새 파일을 추가한다.

```bash
uv run --locked --package teoria-pipelines \
  teoria-pipelines migrate \
  --migrations pipelines/database/migrations
```

실행에는 `TEORIA_PIPELINE_DATA_DATABASE_URL`이 필요하다. 로컬 Compose에서는 `data-db-migrate` 일회성 서비스가 같은 명령을 실행한다.
