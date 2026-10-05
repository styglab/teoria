# Platform Admin UI

`platform/admin-ui/`는 발행된 Semantic Registry와 OpenMetadata 연결을 탐색하고,
Teoria가 소유하는 Suggestion과 Semantic Binding을 검토하는 관리자 화면이다.
일반 사용자용 Service UI와 분리한다.

Admin UI는 독립 TypeScript 프론트엔드 프로젝트이고, Admin API는 Registry Loader와 검증 기능을 사용하는 `teoria-platform` Python 패키지의 HTTP 인터페이스다. 따라서 UI는 `platform/admin-ui/`, API 구현은 `platform/src/teoria/admin/`에 둔다.

```text
Admin UI → Admin API ─┬→ Registry Loader
                      ├→ Teoria Application DB
                      └→ OpenMetadata REST API
MCP      → Runtime API → Capability Runner
```

## 실행

전체 Compose 실행 후 nginx를 통해 `http://localhost:8081/`로 접속한다.

```bash
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml up -d --build admin-ui
```

프론트엔드만 개발할 때는 Admin API를 먼저 실행한다.

```bash
TEORIA_REGISTRY_PATH=platform/registries \
  uv run --locked --package teoria-platform teoria-admin-api

cd platform/admin-ui
npm install
npm run dev
```

Compose 환경에서 Admin UI와 Admin API는 호스트에 직접 공개하지 않는다. nginx가 UI 요청은 Admin UI 컨테이너로, `/admin-api/` 요청은 Admin API 컨테이너로 전달한다. 로컬 UI 개발 시에만 `teoria-admin-api`가 여는 `localhost:8001`을 직접 사용한다.

Compose에서 Admin API Swagger UI는 `http://localhost:8081/admin-api/docs`, Runtime API Swagger UI는 `http://localhost:8081/runtime-api/docs`에서 접근한다.

현재 범위:

- Metadata: OpenMetadata 자산의 최소 탐색
- Suggestions: Metadata Intelligence 제안 검토와 승인
- Bindings: Stable Ontology Concept과 OpenMetadata Glossary/Data Asset 연결
- Ontology·Capability·Source·Mapping·Lineage 탐색

Binding 화면에서 생성한 연결은 항상 Draft다. 승인·거절은 인증 principal의
역할을 사용하며 요청 body의 reviewer 문자열을 신뢰하지 않는다. 운영에서
Bearer 인증을 사용할 때 UI는 현재 세션의 `teoria-admin-token` 값을
Authorization header로 전달한다. 장기 운영 인증은 OIDC 단계에서 교체한다.
