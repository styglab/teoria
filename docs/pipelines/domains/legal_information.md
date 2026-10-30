# 법령 수집 및 버전 관리


법제처 공식 API를 직접 호출하는 독립 수집 기능이다. `korean-law-mcp`는
요청·연혁 처리의 참고 자료이며 실행 의존성이 아니다. 수집·파싱·Data DB는
`backend/src/teoria/features/legal_information/collection/`가 소유한다. 이번 단계는 법령 근거
저장소이며 개인정보 위험등급, 적법성 판정, Ontology와 OpenMetadata 쓰기는
구현 범위에 포함하지 않는다.

## 실행

인증값은 `TEORIA_CONNECTOR_MOLEG_LAW_API_KEY`에 설정한다. Provider 요청의
`OC`에 전달되며 Registry·로그에는 값 대신 환경변수 이름만 사용한다.
Docker 배포는 `deploy/compose/.env`, 로컬 실행은 `.env` 또는 아래처럼
`TEORIA_ENV_FILE`로 선택한다. Data DB migration은 운영 변경 전에 별도 검토하고
격리된 DB에서 먼저 검증한다.

```bash
export TEORIA_ENV_FILE=deploy/compose/.env
# 로컬 DB 주소 또는 격리된 테스트 DB 주소를 설정한다.
export TEORIA_PIPELINE_DATA_DATABASE_URL='postgresql://.../teoria_data'
uv run --locked --project backend teoria-pipelines migrate
uv run --locked --project backend --group orchestration \
  teoria-pipelines law sync --pipelines pipelines
```

`backend/config/legal_information/collection_targets.yaml`은 수집 범위다. 초기 범위는 개인정보 보호법,
공공데이터법, 정보공개법과 각 시행령 6개다. 이름은 공식 명칭을 쓰고, 필요하면
`law_id`를 명시한다. 최초 이름 검색은 현행 목록의 정확한 이름과 유일한 ID만
허용한다. 최초 등록 이후에는 DB에 고정한 ID로 추적하므로 제명 변경에 영향을
받지 않는다. 같은 이름의 폐지·재제정 법령은 서로 다른 ID를 자동 병합하지 않는다.

```bash
# 한 대상만 수집: 전체 수집과 별도 checkpoint를 사용한다.
uv run --locked --project backend --group orchestration \
  teoria-pipelines law sync --pipelines pipelines \
  --target personal_information_protection_act

# 모든 연혁 본문을 재확인한다.
uv run --locked --project backend --group orchestration \
  teoria-pipelines law sync --pipelines pipelines --reconcile-all

# 저장된 원문을 재가공한다. 법제처 호출이나 API 인증값이 필요하지 않다.
uv run --locked --project backend --group orchestration \
  teoria-pipelines law reparse --all

uv run --locked --project backend teoria-pipelines law versions \
  --target personal_information_protection_act

# versions 결과의 정확한 식별자·시행일을 사용한다.
uv run --locked --project backend teoria-pipelines law show \
  --law-id 11357 --mst 283839 --effective-date 2026-09-11 --article 24의2
```

로컬 Flow 실행도 Prefect 설정을 사용한다. 운영 Prefect에 연결하려면 올바른
`PREFECT_API_URL`과 `PREFECT_API_AUTH_STRING`을 함께 설정한다. API URL을
설정하지 않은 개발 실행은 Prefect ephemeral server를 사용한다. 개발 server와
client의 Basic Auth 설정도 서로 맞아야 한다.

## 원문과 버전

- `law`: 법령 ID 및 수집 대상 ID의 고정 연결.
- `law_version`: `(law_id, mst, effective_date)` 시행일별 식별자와 목록 정보.
- `ingestion.law_raw_payloads`: 응답 XML bytes 및 SHA-256. 법제처 응답 링크가
  OC를 되돌려주므로 인증값을 제거한 XML을 보관하고 이 bytes의 hash를 사용한다.
  일반 XML의 순서·속성·CDATA를 재직렬화하지 않는다.
- `ingestion.law_raw_observations`: 실행·인증정보 없는 요청 파라미터·관측 시각.
- `law_snapshot`: 원문 hash, 파서 버전, 해당 시점의 기본정보·목록 정보.
- `law_provision`: snapshot에 연결된 장·절 등 제목, 조·항·호·목 및 부칙.
  `parent_path`는 계층, `path`는 원문 위치, `number`는 Provider 번호다.
- `law_attachment`: 동일 본문에 포함된 별표·서식 정보와 파일 링크 XML.
  첨부파일 바이너리 다운로드·내용 파싱은 이번 단계에서 수행하지 않는다.
- `law_collection_run`: 대상·목록·적재 건수 및 실패한 대상/버전.
  실행 상태는 기존 `ingestion.pipeline_runs`를 참조한다.

같은 원문·파서 버전의 재실행은 snapshot을 중복 생성하지 않는다. 같은 식별자의
원문이 수정되거나 파서 버전이 바뀌면 새 snapshot을 추가하며 이전 조항과 원문은
보존한다. 기본 조회는 해당 시행 버전의 최신 snapshot을 반환하고 근거에 사용할
snapshot ID·hash·parser version을 함께 제공한다. 과거 snapshot은 DB에서 ID로
직접 조회할 수 있다. 원문 bytes는 Data DB의 `bytea`에 보관되므로 운영에서는
Data DB Docker volume과 백업에 포함되며 로컬 코드 폴더에 누적하지 않는다.

## 완전성 및 실행 순서

```text
대상 확인 → 법령 ID 확인 → 연혁·현행·예정 목록 전체 수집
→ 목록 XML 보관 → 목록 등록 → 수집할 버전 선택
→ 버전 본문 수집 → 본문 XML 보관 → 버전 검증·조항 파싱
→ snapshot·조항 트랜잭션 적재 → 전체 성공 시 checkpoint 갱신
```

목록은 `LID`, `nw=1,2,3`, `display<=100`, `page`를 사용한다. 모든 페이지의
전체 건수·페이지 번호·법령 ID와 `(MST, 시행일)` 중복을 검증한다. 안전한 최대
페이지 수를 넘거나 기존 버전이 목록에서 사라지면 성공으로 축약하지 않고 실패로
기록한다. HTML 오류·잘못된 XML·DTD·빈 본문은 정상 빈 결과로 취급하지 않는다.

본문은 `MST + efYd`를 고정하고 `JO` 제한 없이 전체를 조회한다. 본문이 항상
MST를 되돌려주지는 않으므로 법령 ID·시행일·공포일·공포번호를 목록과 대조하고,
MST가 존재하면 추가 대조한다. 요청 날짜가 실패해도 현재 법령이나 MST 단독
본문으로 대신 저장하지 않는다.

Raw 저장 후 구조 검증에 실패한 응답은 근거 추적을 위해 남아 있지만 최신 정규
snapshot으로 승격되지 않는다. 다른 버전은 계속 수집하고 실패 버전은 다음 실행에
재시도한다. 한 버전이라도 미완료이면 전체 checkpoint는 갱신하지 않는다.

예약 시각과 활성 여부는 [자동 생성 배포 목록](../deployments.md)을 따른다.
일별 수집과 전체 연혁 재확인은 별도 Deployment다.
매일 전체 목록을 확인하고 신규·파서 변경·목록 정보 변경·현행·시행예정 본문을
수집한다. 일요일에는 모든 본문을 다시 받아 오래된 원문의 정정도 확인한다.
기본 호출 속도는 초당 1회이며 HTTP 재시도는 기존 Provider Executor가 담당한다.

시행예정도 보관하지만 자동으로 현재 적용 법령으로 판단하지 않는다. 조항별 시행일과
부칙의 예외를 보존하며, 기준일별 법적 적용성 판단은 후속 정책 평가 기능의 책임이다.
이번 단계는 자동 법률 판단이나 개방 승인 기능을 제공하지 않는다.

## Platform 연결 경계

법령 Data DB만 사용하는 Pipeline sink는 `type: data_database`,
`schema_name: legal_information`을 사용한다. 기존 Runtime Source sink는 기본
`type: runtime_source`이며 기존 Source·relation 검증을 유지한다. Runtime에서
법령 DB를 사용하기 시작할 때 Database Source와 읽기 권한을 별도로 추가한다.
Admin 진단용 읽기 계정에는 migration 083의 검색 view와 스키마 USAGE만 허용한다.
원본 테이블·Raw 권한과 Runtime Capability 등록은 추가하지 않는다.

법령 조문 구조 자체는 Ontology로 발행하지 않는다. 이후 보호대상 정보 유형,
처리 목적, 개방 시나리오와 보호조치의 업무 의미가 필요해지면 OpenMetadata
Glossary와 Teoria Business Ontology를 연결한다. 위험등급 및 적용 조건은 승인된
정책 규칙으로 관리하고 법령 변경은 재검토를 유발한다. 자동 탐지 결과는
Suggestion→Review→Application 절차를 거쳐 OpenMetadata에 적용해야 한다.

## 참고 계약

- [공식 시행일 목록 가이드](https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=lsEfYdListGuide)
- [공식 시행일 본문 가이드](https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=lsEfYdInfoGuide)
- [참고한 korean-law-mcp 계보 조회](https://github.com/chrisryugj/korean-law-mcp/blob/c6feff0cbd10cc5b907cdd4f4b3fcf8c59dcc7f7/src/lib/law-lineage.ts)
- [Connector](../../../backend/contracts/ingestion/connectors/moleg_law_api.yaml)
- [Provider Reference](../../../backend/references/providers/moleg/moleg_law_api/metadata.yaml)

## 조회 기능과의 연결

수집된 snapshot을 사용하는 Admin 진단 API와 기준일별 검색 규칙은
[법령 근거 검색](../../platform/metadata/law_evidence.md)에 설명한다. Pipeline은 원문·버전·
검색용 read view를 소유하고 Platform은 조회·진단을 소유한다.

## 현재 전용 배포

법령 작업은 `backend/config/legal_information/prefect_deployments.yaml`에 정의한다.
Compose `prefect-law-deploy`가 `teoria-legal-information` pool과 `laws` queue에 등록하고,
`prefect-law-worker`가 동시 실행 1개·CPU 1·메모리 2GiB 상한으로 실행한다.
기존 조달 수집 pool을 재개하지 않는다. 월~토 04:15 변경 동기화,
일요일 04:15 전체 연혁 보정을 실행한다(Asia/Seoul).
K3s는 전용 dispatcher와 `teoria-legal-information-secrets`를 사용하며 실제 클러스터 검증은 별도다.
[복구 검증](../../../archive/documentation/verification/law_recovery_2026_10_25.md)을 따른다.
