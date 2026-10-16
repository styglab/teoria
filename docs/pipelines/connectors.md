# Connector와 수집 계약 작성

Connector는 Prefect Worker 전용 외부 API 계약이다. Runtime이 직접 호출하지 않으므로 Source Registry에 중복 등록하지 않는다.

아래 경로는 `pipelines/` 기준이다.

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
→ Mapping → public_procurement Runtime Object
```

## 규칙

- Connector는 실행에 사용하는 API wire 계약이다. `definitions/`의 Pipeline은
  검토·검증용 수집 계약 목록이며 Python 실행 엔진의 설정 파일이 아니다.
- `flow_modules`는 해당 수집과 후속 처리를 소유하는 Flow 모듈 목록이다.
  Deployment entrypoint는 이 목록과 정확히 일치해야 한다.
- `operations`와 `sink`는 사용 Operation·적재 대상의 선언이다. Operation 목록은
  구현 및 Connector와, Runtime sink는 Platform Source와 일치하는지 검증한다.
- `cursor`는 수집 범위의 설명용 기준이고 `provenance`는 구현해야 하는 보존 정책이다.
  두 항목을 바꾸는 것만으로 실행 동작이 바뀌지 않는다. 실제 범위와 보존은 Python
  Flow·Task가 소유하며 실행 파라미터·스케줄은 `prefect*.yaml`을 함께 수정한다.
- 모든 Connector는 대응 수집 정의를 갖는다. 수집 Deployment의
  `pipeline:<definition_id>`·`domain:<domain_id>` tag는 수집 계약과 소유권을 연결한다.
  공고의 면허·지역 API 보강 등 후속 처리는 입력 공고를 제공하는 수집 계약에 연결한다.
- 조회 대상 같은 업무 입력은 `config/`, schedule·work pool·실행 파라미터는
  `prefect*.yaml`에 둔다. 선언된 운영 값은 [Deployment 목록](deployments.md)에서 확인한다.
- Flow는 Task 조합만 담당한다.
- API·DB side effect는 Task, 순수 정규화는 일반 함수로 구현한다.
- API→DB 변환은 `src/teoria_pipelines/domains/<domain>/<feature>/normalization.py`,
  DB→Runtime Object 변환은 Platform Mapping에 둔다.
  Ontology Concept와 자산의 업무 의미 연결은 별도 Semantic Binding으로 관리한다.
- Python Flow·Task·API client는 기능 패키지에 함께 둔다. `pipelines/connectors/`는
  YAML 계약이며 Python 호출 코드는 해당 기능의 `client.py`다.
- DB SQL과 transaction은 기능별 `repository.py`가 소유한다. Task는 repository를
  호출해 실행·재시도 경계를 표현한다. 조달 전체 저장소를 합치는 facade는 두지 않는다.
- Raw 보존 수집에는 connector, operation, fetched time, hash와 payload를 남기고 secret은 저장하지 않는다.
  `retain_raw_records: false`인 낙찰·개찰의 원본 비보존과 정규 이력 정책은 [Data DB](database.md#원본관찰정규-데이터)를 따른다.
- Checkpoint는 적재 성공 후에만 이동한다.
- 계약기관(`cntrctInstt*`)과 복수 수요기관(`dminsttList`) 역할을 구분한다.

## Provider 근거 문서

Connector의 근거 원문과 metadata를 다음 경로에 함께 보존한다.

```text
pipelines/references/providers/{provider}/{connector}/
├── metadata.yaml
└── 문서 파일
```

Metadata는 `target: connector`와 Connector ID를 사용하고 `registry`는 `pipelines/` 기준 상대 경로로 기록한다. API 키, 개인정보와 전체 Live 응답은 저장하지 않는다.

## 검증

모든 Operation에 검증 입력을 준비한다. 정적 검증·요청 Build를 먼저 수행하고,
credential이 있으면 안전한 데이터로 `--profile live`까지 실행한다.

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

### 법령 근거 저장소

`moleg_law_api`는 시행일 기준 법령 목록·전체 본문을 직접 수집한다.
`moleg_law_ingestion`은 `type: data_database` sink로 `legal_information`에
적재하며 Runtime Source 등록을 요구하지 않는다. 기존 sink는 기본
`type: runtime_source`로 Source와 relation 검증을 유지한다.
자세한 실행·원문 보존·시행 버전 규칙은 [법령 수집](domains/legal_information.md)을 참고한다.

## 다음 작업

- Flow·Task를 처음 익힐 때는 [PostgreSQL ETL 예제](writing_pipelines.md)를 따라 해 본다. 실제 기능의 코드 배치는 [개발 안내](development.md)를 따른다.
- 스케줄 등록·재시도는 [Prefect 운영](prefect.md)을 따른다.
- 개찰 보강의 완료 판정은 [공공조달 수집](domains/public_procurement.md)을 따른다.
