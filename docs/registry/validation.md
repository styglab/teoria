# Validation

Platform과 Pipelines는 소유 CLI로 검증하고 DB 경계는 통합 검증한다.

## Semantic Registry

```bash
uv run --locked --package teoria-platform teoria validate platform/registries
```

검사 범위는 YAML schema, ID·파일명, Registry 참조, Mapping target, Capability binding과 Provider Reference 연결이다. `--source {source_id}`로 한 Source만 제한할 수 있다.

Source 요청과 실제 응답 검증:

```bash
uv run --locked --package teoria-platform teoria verify source \
  --profile build \
  --source {source_id} \
  --operation {operation_id} \
  --input platform/registries/sources/verification_cases/{source_id}/{operation_id}.yaml
```

Profile은 `static`, `build`, `live` 순서다. Live에서 credential이 없으면 `BLOCKED`, 계약이 틀리면 `FAIL`이며 둘 다 `PASS`가 아니다.

## Data Pipelines

```bash
uv run --locked --package teoria-pipelines teoria-pipelines validate pipelines
uv run --locked --package teoria-pipelines --group validation \
  teoria-pipelines validate-integration pipelines \
  --platform-registries platform/registries
```

첫 명령은 Connector와 Pipeline, 두 번째는 Pipeline sink와 Platform Database Source의 relation·field·type 호환성을 확인한다.

Connector Operation 검증:

```bash
uv run --locked --package teoria-pipelines teoria-pipelines verify connector \
  --profile build \
  --connector {connector_id} \
  --operation {operation_id} \
  --input pipelines/verification_cases/{connector_id}/{operation_id}.yaml
```

실제 API는 `--profile live`를 사용한다. 출력에는 secret과 민감한 원본 응답을 남기지 않는다.

## 회귀 테스트

```bash
uv run --locked --package teoria-provider pytest packages/provider/tests
uv run --locked --package teoria-platform pytest platform/tests
uv run --locked --package teoria-pipelines pytest pipelines/tests
uv run --locked --package teoria-mcp pytest mcp/tests
```

Source 변경은 Platform test·Registry 검증, Connector 변경은 Pipeline test·Pipeline/통합 검증, DB migration 변경은 Database Source 호환성까지 실행한다.
