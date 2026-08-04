# Platform Admin UI

`platform/admin-ui/`는 발행된 Semantic Registry를 탐색하는 읽기 전용 관리자 화면이다. 일반 사용자용 Service UI와 분리한다.

Admin UI는 독립 TypeScript 프론트엔드 프로젝트이고, Admin API는 Registry Loader와 검증 기능을 사용하는 `teoria-platform` Python 패키지의 HTTP 인터페이스다. 따라서 UI는 `platform/admin-ui/`, API 구현은 `platform/src/teoria/admin/`에 둔다.

```text
Admin UI → Admin API → Registry Loader
MCP      → Runtime API → Capability Runner
```

## 실행

전체 Compose 실행 후 nginx를 통해 `http://localhost:8081/`로 접속한다.

```bash
docker compose --env-file .env -f deploy/compose.yaml up -d --build admin-ui
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

초기 범위는 Overview, Ontology 목록, Object·Link 그래프와 Object 상세다. Lineage와 Git-backed Draft 편집은 별도 feature로 확장한다.
