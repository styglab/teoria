# Teoria MCP 서버

레지스트리에 정의된 capability를 MCP 도구로 자동 공개한다. 도구 이름은 capability `id`, 입력 JSON Schema는 capability 입력과 ontology/data type 정의에서 생성된다.

## 실행

프로젝트 루트에서 개발 설치 후 stdio 서버를 실행한다.

```bash
uv sync --locked
uv run --locked teoria validate registries
uv run --locked teoria-mcp
```

설치하지 않고 확인하려면 다음 명령도 사용할 수 있다.

```bash
PYTHONPATH=src python3 -m teoria.adapters.mcp.stdio
```

기본 레지스트리 경로는 `registries`이다. 다른 경로는 `TEORIA_REGISTRY_PATH` 환경변수로 지정한다. 이전 `TEORIA_REGISTRIES` 이름도 마이그레이션 기간 동안 지원한다. 원천 API 키는 기존과 동일하게 프로젝트 루트의 `.env` 또는 프로세스 환경변수에서 읽는다.

일반적인 MCP 클라이언트 설정은 다음과 같다.

```json
{
  "mcpServers": {
    "teoria": {
      "command": "uv",
      "args": ["run", "--locked", "teoria-mcp"],
      "cwd": "/absolute/path/to/teoria",
      "env": {
        "TEORIA_REGISTRY_PATH": "/absolute/path/to/registries"
      }
    }
  }
}
```

Codex에서는 같은 내용을 프로젝트의 `.codex/config.toml`에 둔다. 프로젝트 범위 설정은 trusted project에서 사용되며, 설정 변경 후에는 MCP 서버 또는 Codex 세션을 다시 시작한다.

## 도구 계약

각 도구는 Ontology 객체와 Link, 객체 단위 provenance를 반환한다. 상세한 속성별 provenance가 필요하면 입력의 `_options.include_property_provenance`를 `true`로 지정한다. 대량 재무정보 등은 `_options.max_objects`로 반환 객체 수를 제한할 수 있으며, 전체 개수와 잘림 여부는 `total_objects`, `truncated`에서 확인한다.

Source timeout과 재시도, 최대 페이지 수, Capability 전체 deadline은 공통 Settings를 따른다. 실패는 `code`, capability, source, operation, page, attempts, retryable 정보를 가진 구조화된 실행 오류로 생성된다. 설정값은 [Configuration](configuration.md)을 참고한다.

## Docker 실행

```bash
docker compose -f deploy/compose.yaml --profile stdio run --rm mcp-stdio
```

Compose는 프로젝트 루트 `.env`가 있으면 Source API 키를 컨테이너 환경으로 전달한다.
