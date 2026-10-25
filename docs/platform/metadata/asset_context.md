# 자산 맥락과 샘플·프로파일 조회

Teoria Admin API와 Data Assets 테이블 상세 화면에서 OpenMetadata가 이미 보관한
샘플·프로파일을 조회한다. 실제 데이터 값과 OpenMetadata entity 상태를 Teoria
Application DB에 저장하지 않는다. 조회 결과를 그대로 Suggestion evidence나
로그에 기록하지 않는다.

## 통합 자산 맥락

데이터 자산의 상세에는 기술·운영·의미·거버넌스 정보를 함께 보여주는
통합 메타데이터 패널이 있다. `GET /v1/admin/metadata/asset-context/{table_id}`는
원천을 조회하며 응답을 Teoria DB에 저장하지 않는다.
데이터 자산(`/admin/data-catalog`)에서 Table을 선택하면 전용 상세 페이지를 볼 수 있다.
`TEORIA_ADMIN_METADATA_PUBLIC_READ=true`면 카탈로그·상세·통합 패널·계보·프로파일을
토큰 없이 조회할 수 있다. 기본값은 false다. 샘플 데이터 조회와 변경 작업은 관리자
인증을 유지한다.

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

## 샘플·프로파일 API

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
수집한다. 조회 기능은 운영 DB에서 원문 샘플 수집이나
프로파일링 Job을 자동 실행하지 않는다. 실제 샘플이 필요하면 대상 테이블, 샘플 수,
접근 범위가 정해진 별도 OpenMetadata workflow를 Prefect가 실행하도록 구성해야 한다.
일반 Pipeline Worker에 OpenMetadata ingestion 패키지를 설치하지 않는다.

Codex Skill에서 허용된 샘플·프로파일을 추가 근거로 사용할 수 있다. 비동기 자산 진단
Worker는 현재 원문 샘플을 모델 입력으로 사용하지 않는다. 샘플에서 미탐지한 것을 전체 테이블에 위험 정보가 없다는 뜻으로
해석하지 않는다. 실제 원문 값을 모델에 전달할 범위는 Agent 실행 정책에서 정한다.

버전별 호환성 검증 결과는 [OpenMetadata 업그레이드 검증](../../verification/openmetadata_upgrade_2026_10_13.md)을 참고한다.

## 구현 위치

통합 조회는 `backend/src/teoria/features/metadata_management/catalog/asset_context.py`, OpenMetadata 연계는
`metadata/openmetadata/`, HTTP는 `admin/metadata_api.py`가 소유한다. 공공조달의 운영
조회는 `domains/public_procurement/metadata_operations.py`, output 계약과 read view는
Pipelines가 소유한다. 화면은 `frontend/src/features/metadata/`에서 찾는다.

스키마 메타데이터를 수집하려면 [OpenMetadata Job](../../pipelines/openmetadata.md),
조회 결과로 진단하려면 [자산 진단](asset_assessment.md)을 참고한다.
