# OpenMetadata 샘플·프로파일 조회

Teoria Admin API와 Data Assets 테이블 상세 화면에서 OpenMetadata가 이미 보관한
샘플·프로파일을 조회한다. 실제 데이터 값과 OpenMetadata entity 상태를 Teoria
Application DB에 저장하지 않는다. 조회 결과를 그대로 Suggestion evidence나
로그에 기록하지 않는다.

## API

Admin bearer 인증은 기존 `TEORIA_ADMIN_API_TOKEN`을 사용한다.

```text
GET /v1/admin/metadata/tables/{table_id}/sample-data?limit=10
GET /v1/admin/metadata/tables/{table_id}/sample-data?limit=10&include_values=true
GET /v1/admin/metadata/tables/{table_id}/profile
```

샘플은 기본적으로 모든 비NULL 값을 `[REDACTED]`로 반환한다. 원천 OpenMetadata의
PII masking을 해제하지 않는다. `include_values=true`는 인증된 Admin principal에
`metadata_sample_reader` 역할이 있을 때만 허용한다. 이 역할은 기본 역할에 넣지
않았으며, 필요한 계정의 `TEORIA_ADMIN_API_ROLES`에 명시적으로 추가한다.
현재 Admin bearer는 하나의 token/역할 집합 모델이므로 일반 사용자와 원문 조회자를
같은 token으로 운영하면 권한이 분리되지 않는다.

행 수는 최대 50, 컬럼은 최대 100, 문자열 값은 최대 500자로 제한한다.
중첩 객체·배열 값은 표시하지 않는다. `stored_row_count`는 저장된 샘플의 행 수이며
원천 테이블의 전체 행 수가 아니다. 줄인 결과는 `truncated`로 표시한다.
응답은 `Cache-Control: no-store`이며 UI는 이전 테이블의 값을 다른 테이블에
표시하지 않도록 요청 결과를 구분한다.

프로파일은 최신 table/column profile의 행·컬럼 수, null·distinct·unique
건수/비율과 길이 지표만 반환한다. min/max, 빈도값, distinct 값 목록과 custom
SQL metric은 원천 값 노출을 막기 위해 응답에 포함하지 않는다. 프로파일도 원천
전체 데이터의 안전성을 보장하는 결과가 아니다.

`available=false, reason=not_collected`는 샘플 또는 프로파일이 수집되지 않았다는
뜻이다. 수집된 샘플이 0행이면 `available=true`이다. OpenMetadata의 403은
권한 오류로, 404는 자산 부재로 반환하며 수집되지 않은 상태로 숨기지 않는다.

## 수집과 진단 경계

현재 기본 PostgreSQL ingestion은 `DatabaseMetadata`이며 스키마 메타데이터만
수집한다. 이번 변경은 조회 API/UI를 추가한 것이며 운영 DB에서 원문 샘플 수집이나
프로파일링 Job을 자동 실행하지 않는다. 실제 샘플이 필요하면 대상 테이블, 샘플 수,
접근 범위가 정해진 별도 OpenMetadata workflow를 Prefect가 실행하도록 구성해야 한다.
일반 Pipeline Worker에 OpenMetadata ingestion 패키지를 설치하지 않는다.

진단 Agent는 메타데이터를 먼저 확인하고 허용된 샘플/프로파일을 추가 근거로
사용한다. 샘플에서 미탐지한 것을 전체 테이블에 위험 정보가 없다는 뜻으로
해석하지 않는다. 실제 원문 값을 모델에 전달할 범위는 Agent 실행 정책에서 정한다.

API는 OpenMetadata 1.12.6의 `sampleData`와 `tableProfile/latest` 계약을 기준으로
구현했다. 2026-10-13에는 운영 DB를 복원한 격리 환경의 2.0.5에서 미수집 응답과
합성 샘플·프로파일 조회를 Live 검증했다. 기본 마스킹, 명시적 값 조회와 기존
서비스 DTO 변환이 통과했다. 2.0.5 프로파일 입력 timestamp는 epoch milliseconds이며
Teoria 화면은 초·밀리초를 모두 처리한다. 운영 원문 샘플 수집은 활성화하지 않았다.
