# Source verification cases

Operation별 Build·Live 검증 입력을 다음 위치에 둔다.

```text
{source_id}/{operation_id}.yaml
```

```bash
uv run --locked --package teoria-platform teoria verify source \
  --profile build \
  --source {source_id} \
  --operation {operation_id} \
  --input platform/registries/sources/verification_cases/{source_id}/{operation_id}.yaml
```

실제 호출은 `--profile live`를 사용한다. 공개 가능한 값만 커밋하고 API 키·개인정보·비공개 응답은 로컬 secret과 `.local/`에서 관리한다.
