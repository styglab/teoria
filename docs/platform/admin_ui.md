# Admin UI 사용과 개발

Admin UI는 자산을 탐색하고 업무 의미·연결·변경 제안을 관리하는 화면이다.
전체 스택 실행 후 `http://localhost:8081/`에 접속하면 `/admin/overview`로 이동한다.

현재 조달 질문 테스트 화면은 제거했다. 물품 Ontology·기능 연결은 검토 중이며,
기능 계약 목록이 비어 있는 것은 현재 활성 Registry의 의도된 상태다.

## 작업에 맞는 화면 찾기

| 하려는 작업 | 메뉴와 URL | 확인할 내용 |
|---|---|---|
| 연결·최근 활동 확인 | 현황 `/admin/overview` | 자산·연결 상태, 조회 범위 내 최근 검토 |
| 테이블·컬럼 탐색 | 데이터 카탈로그 `/admin/data-catalog` | 설명·소유자·태그, 스키마·계보·적재 상태 |
| 업무 개념 작성 | 의미 모델 `/admin/semantic-model/ontology` | version, 개념·관계·규칙, Draft 검토·게시 |
| 의미 연결 검토 | 의미 연결 `/admin/semantic-model/bindings` | 자산·Glossary·Concept 참조와 승인 상태 |
| 관리 공백 확인 | 거버넌스 `/admin/governance` | 소유자·분류 등 관리 공백 |
| 변경안 승인·복구 | 검토·적용 `/admin/changes/review` | 현재 값·제안·근거·적용 이력 |
| 운영 상태 확인 | 운영 `/admin/operations` | 원천별 연결과 작업 상태 |
| 실행 계약 확인 | 기능 계약 `/admin/developer/capabilities` | 의미·데이터·실행 준비도 |

현황의 제안·최근 활동은 조회한 범위의 결과이며 전체 누적 통계가 아니다.
자산의 상세 탭, 원천별 조회 범위와 장애 표시는 [자산 맥락](metadata/asset_context.md)에 설명한다.

## 자산을 조회하고 설명 변경안 만들기

1. 데이터 카탈로그에서 스키마를 고르고 자산을 검색한다. 설명·소유자·태그 누락 필터를 사용할 수 있다.
2. 자산을 열어 개요·스키마·의미·거버넌스·품질/프로파일·계보·운영 탭을 확인한다.
3. 테이블의 `설명 변경안` 또는 컬럼의 `설명 변경`에서 변경안을 제출한다.
4. `검토·적용`에서 원천의 현재 값, 제안 값, 제안 당시 근거 version을 비교하고 승인한다.

제출은 pending Suggestion을 만든다. OpenMetadata 반영은 승인 후 application service가
대상 version을 재검증한 뒤 수행한다. 최신 자산 조회 실패는 빈 값으로 표시하지 않는다.
목록 검색·스키마·페이지는 URL에 유지되며 상세를 보고 돌아와도 탐색 상태를 복구한다.

## 진단과 적용 결과 확인

자산 상세의 `자산 진단`에서 진단 항목과 최대 30개 대상 컬럼을 선택하고 실행한다.
상태·제안 링크·근거와 findings를 확인한 뒤 제안을 별도로 검토한다.
비동기 Worker 설정은 [자산 진단](metadata/asset_assessment.md), 공통 승인·적용·복구는
[제안 처리](metadata/suggestions.md)를 따른다.

제안 목록은 서버가 상태와 자산의 정확한 참조를 필터링하고 cursor로 페이지를 조회한다.
`적용 이력 보기`에서 시도별 실행자·시각·결과·오류를 확인한다. 종료 기록이 없는 작업을
성공으로 단정하지 않고 서버의 재시도·기존 결과 확인·재분석 안내를 따른다.
Binding Draft와 Ontology Draft는 생성된 정확한 초안으로 이동하며 별도 승인을 거친다.

개발용 Skill 요청 복사도 제공한다. 정비·의미 연결·개방 진단 요청의 범위와 제출 방법은
[진단 Skills](../skills/analyze_metadata_asset.md)를 따른다. 비동기 Worker와 Skill 실행은
서로 다른 진입점이다.

## 관리자 연결

상단 관리자 연결에서 Admin token을 입력하면 `/v1/admin/auth/session`으로 확인한다.
공개 metadata status 응답을 인증 성공으로 사용하지 않는다. token은 브라우저
sessionStorage에만 보관하고 로그아웃하면 제거한다. 입력은 기본 마스킹되며 `토큰 보기`를
누르는 동안만 표시한다. 인증 실패 시 연결 상태를 확인하고 다시 입력한다.

사용하는 값은 `TEORIA_ADMIN_API_TOKEN`이며 OpenMetadata bot token과 다르다.
설정 줄·따옴표·Bearer 접두사를 붙여넣은 경우 입력 형식을 정리한다. 운영 API는 bearer
인증과 principal별 역할을 사용한다. 토큰 없는 카탈로그 조회 여부와 샘플 조회 권한은
[환경 설정](../deployment/configuration.md), [자산 맥락](metadata/asset_context.md)을 참고한다.

## 프론트엔드 개발

UI는 `frontend/`, Admin API는 `backend/src/teoria/entrypoints/admin/`가 소유한다.

```text
Admin UI → Admin API → OpenMetadata / Application DB / Data DB read view
MCP → Runtime API → Capability Runner
```

저장소 루트에서 Admin API를 실행하고 별도 터미널에서 UI를 시작한다.

```bash
uv run --locked --project backend --extra api teoria-admin-api
```

```bash
cd frontend
npm ci
npm run dev
```

UI 변경은 같은 디렉터리에서 `npm test`와 `npm run build`로 검증한다.
Compose는 UI·Admin API를 직접 공개하지 않고 nginx가 `/`와 `/admin-api/`로 전달한다.
API 문서는 `http://localhost:8081/admin-api/docs`, Runtime 문서는
`http://localhost:8081/runtime-api/docs`다. 개발 API의 기본 포트는 8001이다.

화면·테스트·스타일은 `src/features/<feature>/`에 함께 둔다. `src/api/`는 metadata,
suggestions, asset_assessment, ontology, binding, capability, context, registry,
auth별 계약과 호출을 소유한다. HTTP 전송·token·오류 처리는 `http_client.ts`를 공유한다.

`components/workspace/WorkspaceLayout.tsx`와 `workspace.css`는 공통 페이지 틀을
제공한다. 데이터 카탈로그의 여백·중립적 선택 색상·구분선을 공통 기준으로 사용한다.
화면별 API를 직접 사용하고 기능을 모두 묶는 `admin.ts` 객체를 다시 만들지 않는다.

직접 URL·새로고침·새 탭 접근은 nginx SPA fallback으로 지원한다. 이전
`/admin/business-concepts`, `/admin/semantic-bindings`, `/admin/review-queue`,
`/admin/settings`, `/admin/capabilities`, `/admin/ask`는 현재 경로로 redirect한다.

## 화면 코드의 책임

`features/access/AdminAccess.tsx`는 관리자 세션을, `AdminLoginDialog.tsx`는
토큰 입력·정규화와 로그인 요청을 담당한다. 자산 진단의 선택·요청은
`AssetAssessmentPanel.tsx`, 실행 이력·근거·제안 링크 표시는 `AssessmentHistory.tsx`에 둔다.

`api/http_client.ts`의 `AdminApiError`는 HTTP 상태와 서버 오류 코드를 보존한다.
인증·권한·진단 오류 안내는 `status`와 `code`로 판단하며 메시지 문자열을 검색하지 않는다.
