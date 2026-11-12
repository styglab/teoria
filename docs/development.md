# 개발 안내

먼저 [저장소 구조](architecture/repository-structure.md)에서 변경 소유자를 정한다.
Python은 `backend/pyproject.toml`·`uv.lock`, 프런트엔드는 `frontend/package.json`·`package-lock.json`을 기준으로 설치한다.

## 설치와 기본 검사

저장소 루트에서 실행한다.

```bash
uv sync --project backend --locked --all-extras --group orchestration
uv run --project backend --locked --all-extras --group orchestration pytest backend/tests
uv run --project backend --locked --extra api teoria validate backend/contracts/runtime
uv run --project backend --locked --extra api teoria-pipelines validate backend
uv run --project backend --locked --extra api teoria-pipelines validate-integration backend --platform-registries backend/contracts/runtime
uv run --project backend --locked --extra api pytest tests/documentation
python3 -m tests.documentation.check_docs
```

프런트엔드는 `frontend/`에서 실행한다.

```bash
npm ci
npm test -- --run
npm run build
npm run test:e2e
```

실환경 의존 검사는 DB·인증·객체 저장소 등 설정이 필요하다. skip된 검사를 성공으로 기록하지 않는다.
로컬 Kubernetes 통합 실행은 [k3d](deployment/k3d.md)를 사용한다. 운영은 k3s 또는 일반 Kubernetes를 사용한다.
배포 설정 변경 후 [k3d](deployment/k3d.md) 또는 [K3s](deployment/k3s.md)의 해당 검증을 추가한다.

## 구현 원칙

- 플랫폼·도메인·앱의 공개 계약으로 연결하고 객체 조립은 `entrypoints/composition/`에 둔다.
- HTTP·DB는 native async를 사용하고 API→Service→Repository를 `await`로 연결한다.
- 승인·transaction·잠금·checkpoint 순서를 유지한다. 계산·검증은 일반 함수로 둔다.
- DB 연결을 Task·event loop 사이에 공유하지 않는다. 동시 실행에는 상한을 둔다.
- Admin 쓰기의 actor는 인증된 principal이다. AI 결과는 승인 전 Suggestion이다.
- migration은 새 순번으로 추가한다. 적용 SQL·게시 artifact·이관 이력을 고치지 않는다.

## 데이터 처리 변경

물품 추출은 `domains/goods/data_processing/`, 의미 제안·적용은 `domains/goods/normalization/`,
복합 Flow는 `domains/goods/workflows/`를 수정한다. 주요 단계는 Prefect Task로 표현한다.
원본·산출물 저장과 정규 적재가 성공한 뒤에만 checkpoint를 갱신한다.
Worker의 의미 쓰기는 인증된 Admin HTTP API를 사용한다.

문서별 본문은 객체 저장소, 실행 상태·요약·URI·checksum은 Data DB에 둔다.
OpenMetadata ingestion은 공식 ingestion image를 별도 Job으로 실행한다.

## Provider·실행 계약 변경

Runtime이 직접 호출하는 API는 [Source 작성 절차](platform/registry/source_authoring.md)를 따른다.
Pipeline만 사용하는 API는 [Connector 절차](pipelines/connectors.md)를 따른다.
원본 wire 이름·필드·코드를 유지하고 인증정보를 파일이나 테스트에 쓰지 않는다.

관련 안내: [규격서 평가](domains/goods/specifications/evaluation.md) ·
[Runtime](platform/runtime.md) · [MCP 검증](mcp/gateway.md).

## 프런트엔드 변경

`shell/`은 화면 틀과 접근 경계, `routes.tsx`는 라우트, `navigation.ts`는 메뉴 경로를 소유한다.
업무 화면·API·응답 타입은 `platform/`, `domains/`, `apps/`의 해당 모듈에 함께 둔다.

- 서버 조회는 `api/server_queries.tsx`의 TanStack Query 정책을 사용한다. 쿼리 키에 조회 조건을 모두 포함하고 `AbortSignal`을 HTTP까지 전달한다.
- 토큰을 쿼리 키나 영속 캐시에 넣지 않는다. 인증 변경·만료 시 요청과 캐시를 초기화한다.
- 승인·게시·적용은 사용자 요청으로 실행하며 자동 재시도하지 않는다. 서버 성공 후 관련 조회를 갱신한다. 조회용 POST는 `changesData: false`로 지정한다.
- 공유할 검색·필터·페이지·탭은 URL에 둔다. 편집 중 값·대화상자·선택 전 미리보기는 화면 상태에 둔다.
- Query 캐시와 별도로 서버 응답을 전역 Map이나 Context에 복제하지 않는다. 스크롤·선택 복원 값은 UI 상태로 관리한다.

이 정책은 [TanStack Query 요청 취소](https://tanstack.com/query/latest/docs/framework/react/guides/query-cancellation)와
[캐시 무효화](https://tanstack.com/query/latest/docs/framework/react/guides/query-invalidation)를 따른다.

모델 운영의 공통 API는 `platform/mlops/`, MLflow 통신은 `integrations/mlflow/`,
고객 이탈 샘플은 `archive/customer_churn/`의 독립 Dockerfile로 빌드한다. 실행·검증 방법은 해당 README를 따른다.
공통 모델 API·플랫폼 화면은 예제를 import하지 않으며 composition·shell이 필요한 동작을 주입한다.
배포 목록 문서는 별도 보관하지 않고 `teoria-pipelines deployment-docs`로 현재 선언을 출력한다.

문서 파서는 별도 프로젝트다. 설치는 [Kory Parser 사용법](../archive/kory_parser/docs/usage.md),
회귀 테스트·평가·개선은 [평가 도구](../archive/kory_parser_evaluation/README.md)와
[평가 절차](../archive/kory_parser_evaluation/docs/evaluation_loop.md)를 따른다.
