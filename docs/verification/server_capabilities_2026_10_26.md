# 테스트 독립화와 첫 서버 Capability — 2026-10-26

보관 Registry 의존을 제거하고 컴퓨터 서버의 승인 프로파일 관찰을 Data DB와
Source·Mapping·검색/비교/원문 근거 Capability까지 연결했다.
구현 사용법은 [서버 Capability](../procurement_specification_processing/server_capabilities.md)를 따른다.

## 테스트와 계약

기존 전체 백엔드 검사는 74 failed·2 errors였다. 원인은 존재하지 않는 조달 Registry를
플랫폼 회귀 검사가 읽는 것이었다. 플랫폼에 필요한 최소 합성 API·DB 계약을
`backend/tests/fixtures/registry/`에 두고, 인증·OPA·HTTP 재시도·중첩 응답 검증·페이지 처리·
Mapping·Binding·의미 호환·게시 artifact 검증은 독립 fixture로 유지했다.
조달 집계·공고·낙찰·참가자격 등 은퇴 업무에만 해당하는 계약 검사들은 제거했다.
활성 배포나 Registry에 은퇴 기능을 다시 연결하지 않았다.

서버 구현에서 발견한 두 플랫폼 계약 결함도 수정했다.
Database Source 배열은 Mapping 검증에서 원소 타입을 포함한 `list:<type>`로 판별하고,
Capability 목록 입력의 enum 기본값은 목록의 각 원소를 검증한다.
기존 source/posted artifact의 codec ID는 변경하지 않았다.

## 서버 경로

- Business 의미 작성 입력: 서버·메모리·용량·구성 관계.
- 정규화 프로파일: Stable Key 작성 입력을 게시 Stable Concept ID로 해석하고 검토·승인한다.
- Data DB: 새 migration `093`; 관찰 적재와 완료 상태를 같은 transaction으로 기록한다.
- Source 1개·Runtime 계약 1개·Mapping 1개·공개 Capability 3개·내부 조회 1개.
- 조회 구현: 선언형 검색과 `features/goods_querying/`의 비교·checksum 검증 근거 처리기.
- 서버 직접 관찰과 원문에 명시된 유일한 소유 서버가 있는 메모리 구성 관찰을 지원한다.
  해석된 관계·누락/중복 소유자·`specification_for`로 물리적인 귀속을 만들지 않는다.
- 원문·추출·정규화 본문은 파일/S3에 유지하고 Data DB에는 숫자 관찰·식별자·버전·참조를 둔다.

비교는 역할·범위·단위·의미와 프로파일 버전·연산·한정자가 같고 대상이 유일할 때만
수치 차이를 계산한다. 여러 대상이나 조건은 모호함으로 반환한다.
검색 기본값은 납품 요구·시스템 전체·GB·등호/하한 조건이며 지원 상한과 기보유 사양을 제외한다.
GB/GiB는 정확한 환산과 원문 표현 보존을 함께 확인한다.
부분 완료 실행과 문서의 상태도 조회 결과에 포함한다.

## 실제 검증 범위

격리 PostgreSQL에서 Application/Data migration을 적용하고 실제 Ontology
Draft→검토→승인→게시 및 프로파일 승인·내보내기를 실행했다.
서버 문서 두 개의 고정 합성 관찰을 operational Task 본문으로 처리하여 8개 숫자 관찰을
저장하고, 완료 재실행의 불변성을 확인했다. 관찰 두 번째 insert에 고의 충돌을 넣어
첫 insert와 완료 checkpoint가 모두 rollback되는지도 검증한다.
Prefect scheduler·실제 모델 호출을 실행한 테스트는 아니다.

실제 OPA에 저장소 정책을 적재하고 Registry release·승인 Binding·게시 Ontology를
불변 Runtime bundle로 컴파일했다. Production artifact 로딩 설정으로 Runtime 앱을
시작하여 실제 HTTP 경계에서 다음을 확인한다.

- 익명 discovery 401, 인증 discovery의 공개 Tool 3개와 내부 조회 숨김.
- 메모리 64GB 이상 검색의 납품 요구 2개, 페이지 크기 1의 두 번째 페이지.
- 지원 상한이 납품 하한 조건 검색에 섞이지 않음.
- 두 snapshot의 요구조건 비교와 64GB 차이.
- 원문 구절·node·의미 버전 반환 및 추출 artifact 변조 시 오류.
- Runtime 전용 DB credential의 view 조회 성공과 observation 쓰기 거부.

이전에 노출된 실제 GPU 서버 HWP의 선택한 512GB 요구조건도 고정 추출을 재사용해
적재→검색→원문 근거 조회로 검증한다. 고정 원문 SHA-256과 현재 Parser 0.9.15의
재파싱에서 선택 node 1/1의 동일 텍스트를 확인했다.
이 사례는 silver 원문 대조이며 전체 문서의 독립 정답이나 새로운 모델 정확도가 아니다.
선택 사례의 문서 상태는 partial로 보존한다.
원문 없는 환경에서도 compact source control은 검증하며, 실제 원본 replay는 로컬 원본이 있을 때 수행한다.

최종 검증 결과:

| 검증 | 결과 |
|---|---|
| 전체 백엔드·문서 검사기·Compose 테스트 | **620 passed, 46 skipped** |
| 생략 범위 | 별도 PostgreSQL/S3/Prefect 등 opt-in 설정 필요; 서버 통합 테스트 1개는 아래에서 따로 실행 |
| 격리 서버 통합 | **1 passed**; 실제 PostgreSQL·OPA·승인·bundle·Runtime HTTP·원본 replay·transaction rollback |
| Runtime Registry | Source 1·계약 1·Mapping 1·Capability 4 검증 성공 |
| 수집·통합 계약 | 법령 Connector 1·pipeline 1 검증 성공 |
| 이관 보고서 | 명시적 server manifest의 Runtime projection 1개 valid; 운영 게시 DB 대조는 not_checked |
| Docker | runtime·authoring·worker target build 성공; 이미지 내 discovery·작성 입력·Task/migration 검사 성공 |
| 역할별 의존성 | runtime 이미지에 Prefect 없이 공개 Capability 3개 discovery 성공 |
| Compose | `config --quiet` 성공; Runtime의 근거 volume 읽기 전용·Worker 모델 인증 분리 검사 통과 |
| 문서 | 로컬 링크 432개·문서 110개 검사, 오류 0 |
| 정적 검사 | F821/F822/F823/F811 및 `git diff --check` 통과 |

전체 검사에는 기존 Starlette TestClient/HTTPX deprecation warning 1건이 남아 있다.
초기 Docker build는 로컬 credential helper 오류로 중단됐고, public base image 조회에
인증 helper가 없는 격리 Docker 설정을 사용해 세 이미지를 모두 정상 build했다.
DB Source이므로 외부 Provider API의 Build/Live 호출 대상은 없으며 실제 SQL 조회로 검증했다.

주요 재현 명령:

```bash
uv run --project backend --locked --all-extras --group orchestration \
  pytest backend/tests tests/documentation deploy/compose/tests
uv run --project backend --locked --extra api teoria validate backend/contracts/runtime
uv run --project backend --locked --extra api teoria-pipelines validate backend
uv run --project backend --locked --extra api teoria-pipelines validate-integration backend \
  --platform-registries backend/contracts/runtime
uv run --project backend --locked --extra api teoria ontology-migration-report \
  --registries backend/contracts/runtime \
  --manifest backend/authoring/ontology_migrations/pending/2026_10_server_specifications/ontology_v2.yaml
uv run --project backend python tests/documentation/check_docs.py
docker compose -f deploy/compose/compose.yaml config --quiet
```

통합 검사는 별도의 빈 `teoria_data` PostgreSQL에 `teoria_pipeline`과 조회용 `teoria_runtime`
role을 만들고 OPA에 `deploy/compose/opa/bundle` 정책을 적재한 뒤 실행한다.
`TEORIA_TEST_SERVER_DATABASE_URL`, `TEORIA_TEST_SERVER_RUNTIME_DATABASE_URL`,
`TEORIA_TEST_SERVER_OPA_URL`을 그 격리 환경으로 지정하고 다음을 실행한다.
운영 URL을 사용하지 않는다.

```bash
uv run --project backend --locked --all-extras --group orchestration \
  pytest backend/tests/integration/test_server_capability_path.py
```

확인에 사용한 임시 PostgreSQL·OPA 컨테이너와 검증용 이미지 tag는 검증 후 제거한다.
운영 컨테이너·모델 인증·게시 artifact는 변경하지 않는다.

## 배포 상태

운영 Application/Data DB, Ontology·Binding, Runtime artifact 및 Worker 이미지는 변경하지 않았다.
격리 환경의 test principal이 수행한 의미 게시·프로파일 승인을 운영 승인으로 취급하지 않는다.
운영은 `2026.10.25.1` bundle과 기존 goods Draft를 유지한다.
새 입력은 검토 가능한 작성 자료이며 운영 게시·배포는 별도 단계다.
