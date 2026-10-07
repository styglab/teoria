# Platform Admin UI

`platform/admin_ui/`는 발행된 Semantic Registry와 OpenMetadata 연결을 탐색하고,
Teoria가 소유하는 Suggestion과 Semantic Binding을 검토하는 관리자 화면이다.
일반 사용자용 Service UI와 분리한다.

Admin UI는 독립 TypeScript 프론트엔드 프로젝트이고, Admin API는 Registry Loader와 검증 기능을 사용하는 `teoria-platform` Python 패키지의 HTTP 인터페이스다. 따라서 UI는 `platform/admin_ui/`, API 구현은 `platform/src/teoria/admin/`에 둔다.

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

cd platform/admin_ui
npm install
npm run dev
```

Compose 환경에서 Admin UI와 Admin API는 호스트에 직접 공개하지 않는다. nginx가 UI 요청은 Admin UI 컨테이너로, `/admin-api/` 요청은 Admin API 컨테이너로 전달한다. 로컬 UI 개발 시에만 `teoria-admin-api`가 여는 `localhost:8001`을 직접 사용한다.

Compose에서 Admin API Swagger UI는 `http://localhost:8081/admin-api/docs`, Runtime API Swagger UI는 `http://localhost:8081/runtime-api/docs`에서 접근한다.

현재 범위:

- Ask Teoria: 승인된 의미 연결을 사용한 질문 실행과 근거 확인
- Capabilities: Registry 기능 계약, 의미·데이터·실행 준비도 확인
- Metadata: OpenMetadata 자산의 최소 탐색
- Suggestions: Metadata Intelligence 제안 검토와 승인
- Bindings: Stable Ontology Concept과 OpenMetadata Glossary/Data Asset 연결
- Ontology·Source·Mapping·Lineage 탐색

사이드바 메뉴는 각각 직접 접근 가능한 URL을 사용한다.

- `/admin/ask`
- `/admin/capabilities`
- `/admin/data-catalog`
- `/admin/review-queue`
- `/admin/semantic-bindings`
- `/admin/business-concepts`

Admin UI nginx는 위 경로를 SPA entrypoint로 fallback하므로 새로고침, 직접 URL 접근,
브라우저 앞·뒤 이동과 새 탭 열기를 지원한다.

Capability 준비도는 Registry의 semantic requirement와 교차 계약 검증, 승인된
Binding coverage를 조합해 계산한다. 별도 Workspace lifecycle은 두지 않으며,
변경 상태는 Ontology, Binding, Suggestion과 Runtime bundle의 권위 lifecycle에서
직접 확인한다.

Suggestion 승인은 유형별 application service를 실행한다. 테이블·컬럼 description,
Glossary Term 생성·할당과 quality test는 OpenMetadata REST API로 반영하고,
Ontology 변경은 Published version을 수정하지 않고 새 Draft version에만 반영한다.
Binding 제안은 Binding Draft를 만들며 별도 Binding 승인 전에는 활성 의미 연결이
아니다. 외부 대상 version이 제안 근거와 달라졌으면 적용하지 않고 stale evidence로
실패시킨다.

Data Catalog의 테이블 상세에서 `분석 요청 복사`를 누르면 해당 FQN이 포함된
`$analyze-metadata-asset` Codex Skill 요청을 복사한다. 운영 Admin API가 Codex를
백그라운드에서 직접 호출하는 기능은 아니다. 개발 단계에서는 Codex가 근거를
분석해 pending Suggestion을 제출하고, 관리자는 `Review Queue` 버튼으로 이동해
각 변경을 검토한다. Quality Test와 Test Suite application은 생성 응답만 신뢰하지
않고 OpenMetadata에서 생성 entity를 다시 읽은 뒤 적용 완료로 기록한다.

Binding 화면에서 생성한 연결은 항상 Draft다. 승인·거절은 인증 principal의
역할과 actor를 사용하며 review 요청은 별도 reviewer 필드를 받지 않는다. 운영에서
Bearer 인증을 사용할 때 UI는 현재 세션의 `teoria-admin-token` 값을
Authorization header로 전달한다. 장기 운영 인증은 OIDC 단계에서 교체한다.
