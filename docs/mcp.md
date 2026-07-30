# Teoria MCP 서버

레지스트리에 정의된 capability를 MCP 도구로 자동 공개한다. 도구 이름은 capability `id`, 입력 JSON Schema는 capability 입력과 ontology/data type 정의에서 생성된다.

## 실행

프로젝트 루트에서 개발 설치 후 stdio 서버를 실행한다.

```bash
python -m pip install -e '.[dev]'
teoria-mcp
```

설치하지 않고 확인하려면 다음 명령도 사용할 수 있다.

```bash
PYTHONPATH=src python -m teoria.mcp.server
```

기본 레지스트리 경로는 `registries`이다. 다른 경로는 `TEORIA_REGISTRIES` 환경변수로 지정한다. 원천 API 키는 기존과 동일하게 프로젝트 루트의 `.env` 또는 프로세스 환경변수에서 읽는다.

일반적인 MCP 클라이언트 설정은 다음과 같다.

```json
{
  "mcpServers": {
    "teoria": {
      "command": "teoria-mcp",
      "env": {
        "TEORIA_REGISTRIES": "/absolute/path/to/registries"
      }
    }
  }
}
```

각 도구는 ontology 객체와 link, 객체 단위 provenance를 반환한다. 상세한 속성별 provenance가 필요하면 입력의 `_options.include_property_provenance`를 `true`로 지정한다. 대량 재무정보 등은 `_options.max_objects`로 반환 객체 수를 제한할 수 있으며, 전체 개수와 잘림 여부는 `total_objects`, `truncated`에서 확인한다.
