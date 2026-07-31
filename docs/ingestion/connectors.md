# Data Pipeline Connector와 Pipeline

Connector는 Prefect Worker 전용 외부 API 계약이다. Runtime이 직접 호출하지 않으므로 Source Registry에 중복 등록하지 않는다.

```text
connectors/{connector_id}.yaml
definitions/{domain}/{pipeline_id}.yaml
verification_cases/{connector_id}/{operation_id}.yaml
references/providers/{provider}/{connector}/
```

현재 조달 데이터 흐름:

```text
pps_contract_api → pps_contract_ingestion
→ raw/normalized DB → teoria_public_procurement Database Source
→ Mapping → public_procurement Ontology
```

## 규칙

- Connector는 API 호출 계약, Pipeline은 수집 범위·cursor·sink를 정의한다.
- Flow는 Task 조합만 담당한다.
- API·DB side effect는 Task, 순수 정규화는 일반 함수로 구현한다.
- API→DB 변환은 `normalization/`, DB→Ontology 의미는 Platform Mapping에 둔다.
- Raw에는 connector, operation, fetched time, hash와 payload를 남기고 secret은 저장하지 않는다.
- Checkpoint는 적재 성공 후에만 이동한다.
- 계약기관(`cntrctInstt*`)과 복수 수요기관(`dminsttList`) 역할을 구분한다.

## 검증

```bash
uv run --locked --package teoria-pipelines teoria-pipelines validate pipelines
uv run --locked --package teoria-pipelines --group validation \
  teoria-pipelines validate-integration pipelines \
  --platform-registries platform/registries

uv run --locked --package teoria-pipelines teoria-pipelines verify connector \
  --profile build \
  --connector {connector_id} \
  --operation {operation_id} \
  --input pipelines/verification_cases/{connector_id}/{operation_id}.yaml
```

실제 응답 검증은 `--profile live`를 사용한다. Reference `registry` 경로는 `pipelines/` 기준으로 기록한다.
