# Platform Admin UI

Admin UI의 기본 진입점은 `/admin/overview`다. 정보 구조는 현황, 데이터 카탈로그,
의미 모델, 거버넌스, 검토·적용, 운영과 개발 도구로 나눈다. 데이터 카탈로그는
자산 중심의 통합 조회 영역이고, 의미 모델과 거버넌스는 각각 업무 개념·연결과
소유자·분류 공백을 관리한다. 개발 도구의 기능 계약과 질문 테스트는 핵심 관리
업무와 분리한다.
현황의 자산 수와 연결 상태는 OpenMetadata에서 조회한다. 검토 지표와 최근 활동은
조회된 최근 제안 범위이며 전체 누적 통계가 아니다. 원천 오류가 다른 페이지를
차단하지 않으며 조회 실패와 기록 없음은 구분한다.

자산 상세는 `/admin/data-catalog/assets/<encoded_fqn>?tab=<view>` 전용 페이지다.
개요·스키마·의미·거버넌스·품질/프로파일·계보·운영을 탭으로 전환하고, URL로
직접 열거나 새로고침할 수 있다. 목록은 실제 OpenMetadata 스키마를 왼쪽에 표시하고 선택한 범위의 모든 페이지를
조회한 뒤 이름·설명·FQN·태그·소유자를 검색한다. 설명·소유자·태그 누락 필터,
이름 정렬과 페이지 크기를 제공하며 검색 조건·스키마·페이지는 URL로 유지한다.
상세에서 목록으로 돌아가도 탐색 상태를 복구한다. 데이터는 브라우저에서 일시적으로만
사용하며 스키마 변경·이동 시 이전 응답을 반영하지 않는다. 컬럼 상세는 검색과
설명 누락 필터가 있는 표다. 개요에는 운영 지표와 바로가기를 표시하고 소개 문구를
추가하지 않는다.

자산에서 검토/의미 연결로 이동하면 asset FQN과 entity ID를 유지한다.
연결은 해당 자산의 직접 연결과 실제 Glossary를 통한 연결 ID로 조회한다.
제안은 해당 자산의 근거 참조와 일치하는 최근 50개에서 상세를 조회하며 범위가
잘리면 표시한다. 설명 제안은 원천의 현재 값과 제안 값을 함께 표시한다.

상단의 공통 관리자 연결은 `/v1/admin/auth/session`으로 자격을 확인한다.
공개 metadata status 응답을 인증 성공으로 사용하지 않는다. 로그아웃하면 token을
제거하고 관리자 화면을 닫는다. 변경 API의 principal과 승인 생명주기는 유지한다.

데이터 자산의 상세에는 기술·운영·의미·거버넌스 정보를 함께 보여주는
통합 메타데이터 패널이 있다. `GET /v1/admin/metadata/asset-context/{table_id}`는
원천을 조회하며 응답을 Teoria DB에 저장하지 않는다.
2026-10-13에 Data DB migration 084와 새 Admin API·UI를 운영에 적용했다.
데이터 자산(`/admin/data-catalog`)에서 Table을 선택하면 전용 상세 페이지를 볼 수 있다.
운영 환경은 `TEORIA_ADMIN_METADATA_PUBLIC_READ=true`로 설정해 카탈로그·상세·
통합 패널·계보·프로파일을 토큰 없이 조회한다. 기본값은 false이며, 샘플 데이터
조회와 제안 생성·검토·적용 등 변경 작업은 기존 관리자 인증을 유지한다.
관리자 인증이 필요한 배포에서는 같은 화면에서 기존 Admin token을 입력한다. token은
브라우저 sessionStorage에 보관하며 서버 코드·화면 본문·로그에 표시하지 않는다.
토큰 입력은 `deploy/compose/.env`의 `TEORIA_ADMIN_API_TOKEN` 값을 사용한다.
설정 줄 전체, 따옴표로 감싼 값 또는 `Bearer` 접두사가 있는 값을 붙여넣으면
입력 형식만 정리한 뒤 인증한다. OpenMetadata token과는 별개다. 기본 입력은
마스킹하며 사용자가 `토큰 보기`를 누른 동안만 입력값을 표시한다. 인증 실패는
명시적으로 안내하고 다시 입력할 수 있으며, 연결 중 중복 제출을 막는다.

| 영역 | 원천과 표시 내용 |
|---|---|
| 기술 | OpenMetadata의 스키마·컬럼·설명, 요청 시 물리적 계보 |
| 운영 | Data DB의 명시적 Pipeline output 계약, 최근 적재 실행·성공·체크포인트 |
| 업무 | OpenMetadata Glossary와 Teoria의 직접·용어 기반 Ontology Binding 및 상태 |
| 거버넌스 | OpenMetadata 소유자·태그, 자산별 제안·최근 검토·적용 상태 |

운영 조회에는 `084_asset_collection_context.sql`의 제한된 read view가 필요하다.
공공조달의 서비스·DB·스키마·테이블이 정확히 일치할 때만 연결하며 테이블명
유사성이나 FQN prefix로 Pipeline을 추정하지 않는다. 미연결 자산은 미연결로,
미실행 Pipeline은 실행 기록 없음으로 표시한다. 현재 운영 패널은 적재 audit이며
Prefect schedule·전체 Flow 상태를 복제하거나 대신하지 않는다. checkpoint와 최근
성공만으로 전체 과거 데이터의 수집 완전성을 보장하지 않는다.

Binding은 자산·컬럼의 실제 FQN과 실제 Glossary term으로 조회한다. draft·deprecated도
상태를 표시하며 승인된 연결로 간주하지 않는다. 최근 50개 Binding·Suggestion을
표시하고 잘린 결과를 명시한다. Suggestion 원문·근거 excerpt·데이터 샘플은 이 API에서
반환하지 않는다. 검토·승인·적용은 의미 연결과 제안 검토 화면에서 수행한다.

OpenMetadata는 기술·자산 메타데이터의 원천이며 해당 조회가 실패하면 오류를 반환한다.
Data DB나 Application DB 장애는 해당 영역만 unavailable로 표시한다. DB 연결 미설정,
필요 migration 미적용, 명시적 연결 없음은 빈 정상 결과와 구분한다.
자산 전환 후 이전 요청의 늦은 결과를 다른 자산에 표시하지 않으며 응답은 no-store다.

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

- 질문 테스트: 승인된 의미 연결을 사용한 실행 결과와 근거 확인
- Capabilities: Registry 기능 계약, 의미·데이터·실행 준비도 확인
- Metadata: OpenMetadata 자산의 최소 탐색
- Suggestions: Metadata Intelligence 제안 검토와 승인
- Bindings: Stable Ontology Concept과 OpenMetadata Glossary/Data Asset 연결
- Ontology·Source·Mapping·Lineage 탐색

사이드바 메뉴는 각각 직접 접근 가능한 URL을 사용한다.

- `/admin/overview`
- `/admin/data-catalog`
- `/admin/semantic-model/ontology`
- `/admin/semantic-model/bindings`
- `/admin/governance`
- `/admin/changes/review`
- `/admin/operations`
- `/admin/developer/capabilities`
- `/admin/developer/ask`

이전 `/admin/business-concepts`, `/admin/semantic-bindings`, `/admin/review-queue`,
`/admin/settings`, `/admin/capabilities`, `/admin/ask` 경로는 저장된 링크 호환을 위해
정식 경로로 redirect한다.

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
분석해 pending Suggestion을 제출하고, 관리자는 `제안 검토` 화면으로 이동해
각 변경을 검토한다. Quality Test와 Test Suite application은 생성 응답만 신뢰하지
않고 OpenMetadata에서 생성 entity를 다시 읽은 뒤 적용 완료로 기록한다.

Binding 화면에서 생성한 연결은 항상 Draft다. 승인·거절은 인증 principal의
역할과 actor를 사용하며 review 요청은 별도 reviewer 필드를 받지 않는다. 운영에서
Bearer 인증을 사용할 때 UI는 현재 세션의 `teoria-admin-token` 값을
Authorization header로 전달한다. 장기 운영 인증은 OIDC 단계에서 교체한다.
