# Teoria architecture

Teoria는 하나의 Python 코드베이스를 공유하는 모듈형 모놀리스로 개발한다. 현재 CLI와 MCP adapter를 제공하며, API와 Console은 같은 경계를 따라 독립 배포 가능하게 추가한다.

```text
Registry authoring and publication       Published registry execution

Teoria Console                           MCP / HTTP / CLI
       │                                        │
Registry API                              Runtime
       │                                        │
Registry validation ── published bundle ────────┘
```

## Module boundaries

- `teoria.registry`: Registry schema, loading, resolution, validation, graph, diff and bundle publication.
- `teoria.registry.verification`: Authored Source verification workflows and their deterministic state.
- `teoria.runtime`: Capability binding, Source execution, mapping, materialization and provenance.
- `teoria.adapters`: CLI, MCP, HTTP API and persistence adapters.
- `teoria.transforms`: Allow-listed semantic conversion functions referenced by Mapping Registry.
- `teoria.observability`: 향후 tracing, metrics와 audit integration 위치.
- `apps/console`: Browser UI. It accesses registries through the HTTP API, never through the filesystem.

Dependencies point inward: adapters may call registry and runtime; runtime may use registry schemas and catalogs; registry must not depend on MCP, HTTP API or Console code.

## Deployment units

- `teoria-mcp`: 현재 제공하는 로컬 STDIO Capability 서버. 원격 transport는 향후 추가한다.
- `teoria-api`: 향후 Registry 조회, 검증 및 authoring workflow.
- `teoria-console`: 향후 Registry Explorer와 관리 웹 애플리케이션.

These are deployment units, not separate source repositories. Split Python distributions only after an independent consumer or release cycle actually requires it.
