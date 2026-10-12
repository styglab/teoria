# Data Pipeline Connector와 Pipeline

Connector는 Prefect Worker 전용 외부 API 계약이다. Runtime이 직접 호출하지 않으므로 Source Registry에 중복 등록하지 않는다.

```text
connectors/{connector_id}.yaml
definitions/{domain}/{pipeline_id}.yaml
verification_cases/{connector_id}/{operation_id}.yaml
references/providers/{provider}/{connector}/
```

현재 조달 데이터 흐름:

```text
pps_contract_api → pps_contract_ingestion
→ raw/normalized DB → teoria_public_procurement Database Source
→ Mapping → public_procurement Ontology
```

## 규칙

- Connector는 API 호출 계약, Pipeline은 수집 범위·cursor·sink를 정의한다.
- Flow는 Task 조합만 담당한다.
- API·DB side effect는 Task, 순수 정규화는 일반 함수로 구현한다.
- API→DB 변환은 `src/teoria_pipelines/domains/<domain>/<feature>/normalization.py`,
  DB→Ontology 의미는 Platform Mapping에 둔다.
- Python Flow·Task·API client는 기능 패키지에 함께 둔다. `pipelines/connectors/`는
  YAML 계약이며 Python 호출 코드는 해당 기능의 `client.py`다.
- Raw에는 connector, operation, fetched time, hash와 payload를 남기고 secret은 저장하지 않는다.
- Checkpoint는 적재 성공 후에만 이동한다.
- 계약기관(`cntrctInstt*`)과 복수 수요기관(`dminsttList`) 역할을 구분한다.

## 검증

```bash
uv run --locked --package teoria-pipelines teoria-pipelines validate pipelines
uv run --locked --package teoria-pipelines --group validation \
  teoria-pipelines validate-integration pipelines \
  --platform-registries platform/registries

uv run --locked --package teoria-pipelines teoria-pipelines verify connector \
  --profile build \
  --connector {connector_id} \
  --operation {operation_id} \
  --input pipelines/verification_cases/{connector_id}/{operation_id}.yaml
```

실제 응답 검증은 `--profile live`를 사용한다. Reference `registry` 경로는 `pipelines/` 기준으로 기록한다.

### 개찰 보강 완료 판정

개찰 원본은 모든 페이지의 totalCount·행 수·중복·공고 키와 알려진 낙찰자를
검증한 뒤 저장한다. 일부 페이지만 조회하거나 응답이 잘린 경우 기존 참여업체를
교체하지 않고 해당 공고만 재시도한다. 정규 저장 대상은 순위 1~10위와 낙찰자다.
전체 참가자 수와 정규 저장 수를 비교하지 않는다. 수집 상태의
`participant_count`는 원본 조회 행 수를 유지하고, `selected_business_numbers`는
검증한 저장 대상 업체 집합을 보관한다. 같은 낙찰 원본 hash에 대해 정규 테이블의
업체 집합이 정확히 일치해야 queue를 완료한다. 기존 상태의 NULL 집합은 미검증이며
재조회 없이 일괄 완료로 바꾸지 않는다. 전체 조회는 기존 timeout·호출 속도 제한을
따르므로 참가자가 많은 공고는 제한 시간 내에 완료하지 못해 재시도할 수 있다.

2026-10-12 점검에서 과거 용역 계약 `2021-07-29`는 DB에 1,661건이 있었지만,
이를 대조할 원본 보관 이력은 없었다. 제공기관은 같은 날짜의 일부 행에서 오류
99를 반환한다. API의 totalCount와 DB 건수만 같다는 이유로 해당 gap을 해결로
표시하지 않는다. 해당 gap은 15회 재시도 한도에 도달해 자동 재시도가 중단된
상태다. 이 날짜는 제공기관 응답 복구 후 계약 식별자와 원본 hash를
검증해야 하며, 다른 날짜의 과거 계약 backfill은 계속 진행한다.

### 법령 근거 저장소

`moleg_law_api`는 시행일 기준 법령 목록·전체 본문을 직접 수집한다.
`moleg_law_ingestion`은 `type: data_database` sink로 `legal_information`에
적재하며 Runtime Source 등록을 요구하지 않는다. 기존 sink는 기본
`type: runtime_source`로 Source와 relation 검증을 유지한다.
자세한 실행·원문 보존·시행 버전 규칙은 [법령 수집](law_collection.md)을 참고한다.
