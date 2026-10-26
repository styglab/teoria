# 백엔드 책임·FastAPI 구조 정리 — 2026-10-26

검토에서 확인한 의존 방향·API 조립·서비스/저장소 책임·파일 이름을 정리하고 기존 Compose 운영에 반영했다.
저장소의 기능 경계와 외부 HTTP·CLI·Prefect 배포 이름을 유지했다. K3s 운영 배포 결과는 아니다.

## 코드 배치

- FastAPI 앱 생성과 Uvicorn 실행: `entrypoints/admin_api.py`, `runtime_api.py`, `policy_control_plane.py`.
- Admin·Runtime 객체 조립: `entrypoints/composition/admin.py`, `runtime.py`.
- 기능 HTTP 처리: 각 기능의 `*_router.py`. Runtime은 `runtime_router.py`와 명시적인 `Depends`로 request의 서비스 구성을 받는다.
- Factory가 생성한 Provider·OpenMetadata·OPA·Context HTTP client는 API lifespan 동안 재사용하고 종료 시 닫는다. 주입받은 client의 소유권은 호출자에게 유지한다.
- 메타데이터 진단 Worker도 OpenMetadata client를 async context로 관리한다.
- Ontology 작성·검토·게시 정책: `OntologyAuthoringService`. SQL·revision integrity·저장은 `OntologyRepository`.
- 물품 프로파일 정책: `NormalizationProfileService`. 저장·감사는 `NormalizationProfileRepository`.
- 의미 판정의 내구성 실행과 checkpoint: `SemanticOperationService`와 `SemanticOperationRepository`.
- 프로파일 승인과 Ontology artifact version 잠금은 같은 connection/transaction을 공유한다. 상태·감사·불변 산출물의 commit/rollback 순서를 유지한다.
- 후보 처리는 `candidate_context()`, `published_artifact()`, `find_revision()` 공개 서비스 메서드를 사용하며 내부 context 메서드·DB URL을 직접 사용하지 않는다.

기능→진입점 역참조를 제거했다. 수집 계약 로더에서 Prefect manifest 읽기를 분리하고 CLI가 두 검증 결과를 조합한다.
Source 요청 생성·응답 검증 adapter는 Registry 소유로 옮겨 검증이 Runtime 구현을 역으로 참조하지 않도록 했다.

## 이름과 호환

- Runtime Contract 그래프는 `registry/runtime_contract_graph.py`, Registry 개요 표현은 `registry/presentation.py`.
- MCP protocol·Tool·schema·설정은 `entrypoints/mcp/`, HTTP transport는 `integrations/runtime_http/`.
- Codex 실행 구현은 `integrations/codex/runner.py`; 패키지 루트는 공개 export만 유지한다.
- 한 번의 의미 판정 cycle은 `semantic_cycle.py`. 표준 적용 테스트는 소유 코드와 같은 `normalization/` 이름을 사용한다.
- Mapping 기본 변환은 `registry/codecs/primitives.py`. 기업·과세 변환은 `registry/codecs/legacy/`에 격리했다.
- `common.*`, `company.*`, `tax.*` codec ID는 이전 게시 계약 호환을 위해 유지한다. 등록된 업무 Source·Capability·조달 수집을 복원하지 않는다.
- 은퇴한 개찰 이력 정리 SQL은 `archive/maintenance/`에 보관했다. 적용된 migration 본문은 변경하지 않았다.

## FastAPI 기준

공식 [여러 파일과 APIRouter](https://fastapi.tiangolo.com/tutorial/bigger-applications/),
[의존성 주입](https://fastapi.tiangolo.com/advanced/advanced-dependencies/),
[lifespan](https://fastapi.tiangolo.com/advanced/events/)과
[HTTPX client 재사용](https://www.python-httpx.org/async/#opening-and-closing-clients)을 참고했다.
문서가 특정 폴더 이름을 강제하는 것은 아니며, 기능 소유권에 맞춰 적용했다.
개발용 CORS에는 실제 프로파일 수정 API가 사용하는 PUT과 DELETE도 허용했다. 운영 인증·허용 origin 정책은 유지했다.

## 검증

| 대상 | 결과 |
|---|---|
| 백엔드·기능 간 계약 | 567 passed, 건너뛴 테스트 없음 |
| 실제 격리 자원 | PostgreSQL·Prefect·MinIO로 승인/게시/실패/재개 경로 검증 |
| Transaction | Ontology 게시와 프로파일 승인에서 감사 저장을 실패시켜 상태·artifact·감사가 함께 rollback됨을 확인 |
| Lifespan | 앱이 소유한 pool 종료, 주입 client 비종료, 개발 PUT preflight 검증 |
| 구조 | 기능→진입점 금지, 기능 간 비순환 의존, 계약 로더의 Prefect 비의존, 정책 서비스 inline SQL 금지 |
| API 계약 | Admin 71개·Runtime 4개 경로의 메서드·본문·응답 schema 유지 |
| OpenAPI component ID | 동명 TransitionInput 2개의 모듈 접두어는 파일 이름 변경에 따라 admin_api→admin_router로 변경; 이를 정규화하면 전체 OpenAPI가 동일 |
| Registry·Connector·통합 검증 | 성공, 새 업무 Capability 없음 |
| 문서·Compose 테스트 | 문서 검사기 7개·Compose 6개 통과 |
| Docker | Authoring·Runtime·MCP·규격서·법령·Metadata·Check target 7개 build 성공 |
| 후보 이미지 smoke | Admin factory·lifespan·health, production artifact·OPA Runtime discovery, MCP 실제 STDIO 성공 |
| 운영 | API·MCP·Worker 등 변경 서비스 8개 새 이미지, running, restart 0, 정의된 healthcheck 정상 |

새 migration은 없다. 기존 적용 SQL·Ontology 이관 이력·게시 bundle은 변경하지 않았다.
기존 Starlette TestClient의 HTTPX 관련 deprecation warning 1건은 테스트 성공과 별도로 남아 있다.

## 운영 전환

활성 Prefect 작업과 AI 진단 claim이 없는 상태에서 pool 세 개를 일시정지하고 API·Worker를 교체했다.
기존 배포 ID·스케줄·입력을 바꾸지 않고 heartbeat 확인 뒤 pool을 원래대로 열었다.
은퇴한 수집 배포 20개와 수집/구형 AI 추출 pool의 paused 상태를 유지한다. 규격서 배포 세 개는 계속 수동 실행이다.
이전 이미지는 `teoria-rollback-<service>:20261026T063913Z`에, 전환 전 상태는 `backups/teoria/backend_cleanup_20261026T063913Z/`에 보관했다.
이전부터 열린 외부 STDIO 세션을 강제로 종료하지 않았으며 재연결 시 새 MCP 이미지를 사용한다.

다음 작업은 교체 후 실제 Worker에서 실행해 완료했다.

| 작업 | Flow run ID | 시작–종료 UTC | 상태 |
|---|---|---|---|
| `moleg-law-daily` | `70d3f8d4-0ccc-453b-8ec4-a0cfbc853ca6` | 2026-10-26 06:42:39.231476+00:00 – 2026-10-26 06:42:54.127843+00:00 | Completed |
| `openmetadata-postgres-metadata-sync` | `54b7ca48-4e95-4648-a0ef-a8a6e1028298` | 2026-10-26 06:42:44.555914+00:00 – 2026-10-26 06:43:03.517764+00:00 | Completed |

관리 화면·API·법령 검색은 nginx 경유 HTTP 200, 보호된 관리·Runtime API는 토큰 없는 요청 HTTP 401을 확인했다.
신규 관리 API의 존재하지 않는 ID 조회는 예상 HTTP 404로 응답한다. 운영 MCP는 STDIO initialize·discovery·tools/list를 완료했으며 도구 수는 0이다.
새 규격서 Worker에서 synthetic DOCX 파싱과 원본 checksum 검증도 성공했다. 실제 사용자 문서의 전체 모델 정확도 평가를 수행한 것은 아니다.

## 불변 상태

- Runtime version: `2026.10.25.1`
- Runtime checksum: `sha256:907356fe1bc90b4f0a44fcf8eb670c2f10a73827dd6fa7e920cc9da697e5a5f6`
- Ontology·Binding·진단 상태별 건수는 전환 전후 동일하다. 새 Ontology 게시·Binding 승인·자동 의미 채택은 수행하지 않았다.

| 서비스 | 새 image ID |
|---|---|
| `runtime-api` | `sha256:a044abb538ba5d8a5d13d394580280eb6a45d2d6e94ee5fb0aefc3f8aebbd7c1` |
| `admin-api` | `sha256:fdf298dd55c5cb053f650d3d4a0f1ff1eef87a256546e5adf8e6c671e407c012` |
| `policy-control-plane` | `sha256:fdf298dd55c5cb053f650d3d4a0f1ff1eef87a256546e5adf8e6c671e407c012` |
| `prefect-worker` | `sha256:37224701832e255ef242dc3af784c808789dcab6dcfdcfb7b7a55c1f08ab4dec` |
| `prefect-law-worker` | `sha256:24e4ba0335198ff7153f7711a9ba64ba4a1b2dc8cf993975014d51381771c2de` |
| `prefect-metadata-worker` | `sha256:08cf1bec1226f748a45f9cf8531bded8d8b36bf8ae752c3b88683d00e3abe5ca` |
| `metadata-assessment-worker` | `sha256:fdf298dd55c5cb053f650d3d4a0f1ff1eef87a256546e5adf8e6c671e407c012` |
| `mcp` | `sha256:e2a045f7d358c2e9e23def4b06e053dbfc19f3547618443ff804fe9593b311c4` |

기록: 2026-10-26 06:48:49 UTC

## 추가 유지보수 적용

- OpenMetadata Docker ingestion은 `ExitStack`에 client 종료와 생성된 컨테이너 제거를
  각각 등록한다. 컨테이너 생성·대기·로그 조회·삭제 실패 시에도 client 종료를 시도한다.
- 현재 참조하지 않는 공고 보강·개찰·계약 수집 설정 5개와 남은 환경변수 안내를 제거했다.
- 법령 검색·물품 정규화의 백엔드 내부 계약 테스트를 `backend/tests/integration/`으로
  옮겼다. 루트 `tests/integration/`에는 배포 구성요소의 공개 HTTP 라우팅 검증을 유지한다.
- 규격서 CLI의 review·표준 workflow·평가·문서 처리를 같은 모듈의 이름 있는 함수로
  정리했다. review 전용 Prefect 환경은 성공·실패 모두 호출자의 설정으로 복원한다.
- AI 진단 Worker는 추론 HTTP client를 async context에서 재사용한다. 취소·오류 시
  소유 연결을 닫고, 외부에서 주입한 client는 호출자가 닫도록 유지한다.

변경 관련 테스트 105개가 통과했다. 격리 PostgreSQL·객체 저장소·Prefect 평가를 포함한
전체 백엔드·문서 검사 단위 테스트·Compose 검사 결과는 603 passed, 74 failed,
2 errors다. 실패·오류는 현재 작업 공간에 없는
`archive/procurement_services/platform/registries`를 참조하는 기존 회귀 검사와 관련된다.
이동한 법령 검색·물품 정규화 계약 테스트는 전체 실행에서 통과했다.
격리 검증용 컨테이너는 실행 후 제거했다.

Compose 전체 profile 설정 검사와 활성 Runtime·수집 계약 검증은 통과했다.
문서 링크 검사에는 이번 변경 외의 누락된 과거 조달 Capability·ETL 보관 파일 참조
5개가 남아 있다. 해당 보관 파일은 이 작업에서 복원하거나 변경하지 않았다.
이번 추가 유지보수는 소스·테스트·문서에 적용했으며 운영 컨테이너는 재배포하지 않았다.
