---
name: author-source-registry
description: Create or revise a Teoria Source Registry and operation verification cases from provider API reference documents, then run static, build, regression, and actual API live validation by default when credentials are available, diagnose failures, and iteratively correct source-contract defects. Use for requests that turn files under platform/references/providers into a final platform/registries/sources YAML, audit an existing Source against its original documentation, or complete the reference-to-registry verification workflow.
---

# Author Source Registry

외부 API 원문을 근거로 Runtime API Source 또는 Ingestion API Connector와 verification case를 만들고, 실행 검증 결과까지 포함해 완료한다. 문서에 없는 계약은 추측하지 않으며 검증 실패가 곧 계약 오류라고 가정하지 않는다.

## Workflow

### 1. 저장소 규칙 확인

작업 전에 다음 파일을 끝까지 읽는다.

- `AGENTS.md`
- `docs/registry/source-authoring.md`
- `docs/registry/source_registry.md`
- `docs/registry/templates/source.yaml`
- 대상과 유사한 기존 Source 및 verification case

이 Skill은 Source, Reference metadata, verification case만 기본 범위로 삼는다. 요청받지 않은 Ontology, Mapping, Capability는 만들지 않는다. 사용자 변경과 관련 없는 파일은 수정하지 않는다.

### 2. 원문과 대상 확정

파일을 만들기 전에 실행 경계를 먼저 확정한다.

- Semantic Runtime이 API를 직접 호출하면 `platform/registries/sources/{source_id}.yaml`을 만든다.
- Prefect 등 Ingestion Worker만 API를 호출하면 `pipelines/connectors/{connector_id}.yaml`을 만들고 verification case는 `pipelines/verification_cases/{connector_id}/`에 둔다.
- API 데이터를 정규화한 DB를 Runtime이 조회하는 구조에서는 API Connector를 Source Registry에 중복 등록하지 않는다.

Source는 `platform/references/providers/{provider}/{source}/metadata.yaml`, Connector는 `pipelines/references/providers/{provider}/{connector}/metadata.yaml`과 `files`에 등록된 모든 문서를 확인한다. ID가 명확하면 `{provider}_{service}` 형태의 짧고 안정적인 `snake_case`를 사용한다.

DOCX 또는 텍스트 문서는 먼저 다음 명령으로 구조화해 전체 표를 누락 없이 검토한다.

```bash
python3 .agents/skills/author-source-registry/scripts/extract_reference.py \
  platform/references/providers/{provider}/{source}/{document} > /tmp/{source}-reference.json
```

Connector 원문이면 입력 경로로 `pipelines/references/providers/{provider}/{connector}/{document}`를 사용한다.

여러 파일이나 디렉터리를 한 번에 넘겨도 된다. PDF는 `pdftotext`가 설치된 경우 지원한다. 스캔 이미지처럼 텍스트를 얻을 수 없으면 사용할 수 있는 문서/OCR 도구로 직접 확인하고, 확인할 수 없는 범위를 결과에 명시한다.

편집 전에 아래 근거 목록을 만든다.

- 제공·배포 기관, 서비스 ID, 버전, 운영 base URL
- 인증 위치와 원본 파라미터명
- 모든 Operation의 원본 이름, method, path, 설명
- Operation별 request query/header/body 필드, 타입, 필수 여부, 기본값과 제한
- 성공 status/content type, control/data 구조, record path
- 응답 필드의 원본 이름, 타입과 설명
- pagination 요청 및 전체 건수 경로
- 문서에 명시된 오류 status/code/message

샘플 값만으로 타입·필수 여부·코드 의미를 단정하지 않는다. 조건부 필수처럼 현 스키마로 정확히 표현하지 못하는 계약은 억지로 단순화하지 말고 제한으로 보고한다.

### 3. Source와 case 작성

`docs/registry/templates/source.yaml`을 기준으로 다음을 함께 작성한다.

```text
platform/registries/sources/{source_id}.yaml
platform/registries/sources/verification_cases/{source_id}/{operation_id}.yaml
platform/references/providers/{provider}/{source}/metadata.yaml
```

Ingestion Connector로 확정된 경우 대응 위치는 다음과 같다.

```text
pipelines/connectors/{connector_id}.yaml
pipelines/verification_cases/{connector_id}/{operation_id}.yaml
pipelines/references/providers/{provider}/{connector}/metadata.yaml
```

Connector 문서는 최상위 `connector:`를 사용하고 Reference metadata에는 `target: connector`와 Connector 경로를 기록한다.

- Source 필드와 요청 파라미터 ID는 원문 표기를 보존한다.
- Teoria가 정의하는 Source, Object, Operation ID만 `snake_case`로 쓴다.
- 반복 객체는 `components.objects`로 재사용하되 원문의 서로 다른 구조를 억지로 합치지 않는다.
- 모든 Operation에 공개 가능하고 비민감한 verification case를 만든다.
- secret 값은 저장하지 않고 `TEORIA_SOURCE_<SOURCE_ID>_API_KEY`만 참조한다.
- Source가 만들어지기 전 Reference는 `draft`, Source와 경로가 완성된 변경에서는 `active`로 둔다.
- 원문에 없는 필드, 타입, 기본값, 필수 여부, 오류 코드를 만들지 않는다.

응답 형식 선택 파라미터는 별도로 판단한다. API가 `json`, `xml` 같은 형식 선택값을 제공하고 Source의 `response.content_type`과 record path를 JSON 기준으로 정의했다면, 해당 요청 필드에 `default: json`을 둬 Teoria가 항상 그 표현을 요청하게 한다. 이는 제공기관 자체 기본값이 아니라 **Teoria 실행 기본값**이다. 원문이 지원하지 않는 형식값은 만들지 않는다.

이 실행 기본값을 검증할 때는 verification case에서 형식 선택 필드를 생략한다. Build 결과의 prepared request에 선택값이 자동 주입되는지 확인하고, 같은 case로 Live를 실행해 선언한 content type과 record path가 통과하는지 확인한다. case에 값을 직접 넣어 기본값 검증을 우회하지 않는다.

### 4. 원문 대조

작성한 YAML을 근거 목록과 다시 대조한다. Operation 수와 각 Operation의 요청·응답 필드 수를 세고, 원문의 각 행이 정확히 한 정의에 반영되었거나 제외 이유가 있는지 확인한다. 이름이 비슷하다는 이유로 다른 Operation의 필드를 대체하지 않는다.

### 5. 검증 실행

먼저 대상 Source를 정적으로 검증한다.

```bash
uv run --locked --package teoria-platform teoria validate platform/registries --source {source_id}
```

그 다음 모든 Operation에 대해 요청 생성 검증을 실행한다.

```bash
uv run --locked --package teoria-platform teoria verify source \
  --profile build \
  --source {source_id} \
  --operation {operation_id} \
  --input platform/registries/sources/verification_cases/{source_id}/{operation_id}.yaml
```

응답 형식 실행 기본값을 선언했다면 Build 결과에서 case가 값을 제공하지 않았는데도 해당 파라미터가 주입됐는지 추가로 확인한다.

마지막으로 회귀 검증을 실행한다.

```bash
uv run --locked --package teoria-platform pytest platform/tests
uv run --locked --package teoria-platform teoria validate platform/registries
```

Source 작성 또는 검증 요청은 실제 API 검증까지 포함하는 것으로 처리한다. 필요한 credential이 환경에 존재하면 모든 Operation을 `--profile live`로 실행한다.

Connector는 동일한 profile 의미를 가지는 전용 명령을 사용한다.

```bash
uv run --locked --package teoria-pipelines teoria-pipelines verify connector \
  --profile build \
  --connector {connector_id} \
  --operation {operation_id} \
  --input pipelines/verification_cases/{connector_id}/{operation_id}.yaml
```

Connector 변경의 회귀 검증은 다음을 실행한다.

```bash
uv run --locked --package teoria-pipelines pytest pipelines/tests
uv run --locked --package teoria-pipelines \
  teoria-pipelines validate pipelines \
  --platform-registries platform/registries
```

```bash
uv run --locked --package teoria-platform teoria verify source \
  --profile live \
  --source {source_id} \
  --operation {operation_id} \
  --input platform/registries/sources/verification_cases/{source_id}/{operation_id}.yaml
```

사용자가 명시적으로 Live 호출을 제외한 경우에만 생략한다. 인증정보, 민감한 입력, 원본 전체 응답을 출력하거나 커밋하지 않는다. credential이 없으면 Live 검증만 `BLOCKED`로 표시하며 Build나 전체 검증을 Live 성공으로 표현하지 않는다. 일부 Operation에만 안전한 공개 검증 입력이 있으면 실행 가능한 Operation은 Live로 검증하고 나머지는 각각의 차단 이유를 남긴다.

### 6. 실패 진단과 수정 반복

실패를 먼저 다음 중 하나로 분류한다.

- **Source 계약 결함:** method/path/필드/type/record path/pagination/required 정의가 원문 또는 안전하게 확인한 응답과 다름. Source와 case를 수정하고 전체 검증을 반복한다.
- **Verification case 결함:** 필수 입력 누락, 잘못된 section, 공개 테스트 값의 형식 오류. case를 수정한다.
- **Credential 또는 외부 환경:** 키 누락·거부, DNS, timeout, 제공기관 장애. Source를 추측 수정하지 않고 `BLOCKED` 또는 외부 실패로 보고한다.
- **Runtime/validator 결함:** Registry 계약이 맞지만 실행 코드가 처리하지 못함. 증거와 재현 명령을 보고하고, 사용자가 요청한 범위에 포함될 때만 코드를 수정한다.

수정할 때마다 대상 정적 검증과 해당 Operation Build 검증부터 재실행한 뒤 전체 테스트로 회귀를 확인한다. 실패를 숨기기 위해 필드나 required를 제거하지 않는다.

## Completion Report

최종 응답에는 다음을 모두 남긴다.

- 생성·수정한 파일
- 원문에서 확인한 Operation 수와 정의한 Operation 수
- Operation별 요청·응답 필드 대조 결과와 의도적으로 제외한 항목
- 실행한 명령과 각 결과(`PASS`, `FAIL`, `BLOCKED`)
- 검증 중 발견해 수정한 계약 문제
- Live 검증 여부와 미실행 이유
- 스키마로 표현하지 못했거나 원문에서 확인되지 않은 제한

Static, 모든 Build, 전체 test/registry validation이 통과해야 작성 작업을 완료로 표현한다. 모든 Operation의 Live 결과도 `PASS`, `FAIL`, `BLOCKED` 중 하나로 보고한다. credential 또는 외부 조건 때문에 Live를 실행하지 못했다면 전체 검증이 성공했다고 표현하지 말고 정적·Build 성공과 Live `BLOCKED`를 분명히 구분한다. 실행 산출물을 `archive/`에 저장하는 것은 사용자가 명시적으로 요구한 경우에만 한다.
