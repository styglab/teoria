1. 프로젝트명
- 프로젝트 테오리아
- teoria (theoria) - 높은 곳에서 전체를 관찰하여 본질을 이해
- AI context
- source > ontology > mapping > capability

2. 구조
```
Source Registry
↓
Ontology Registry
세상을 정의 (명사)
 - Object
 - Property
 - Relationship
↓
Mapping Registry
↓
Capability Registry
업무를 수행 (동사)
- operation
- decision
- action
- workflow

```

3. 프로젝트 구조
```
registries/             사람이 작성하는 Registry YAML
  core/
    data_types.yaml
    value_sets.yaml
  sources/
  ontologies/
  mappings/
  capabilities/
src/teoria/
  models/               Registry Pydantic 모델
  registry/             로딩, 참조 해결, 검증 및 진단
tests/
  unit/
  fixtures/
  registry_cases/
```

Source의 필드 ID와 요청 파라미터는 원본 시스템의 표기를 보존한다.
snake_case 규칙은 Registry ID와 Teoria가 정의하는 ID에 적용한다.

4. 개발 및 검증
```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
.venv/bin/teoria validate registries
.venv/bin/teoria validate registries --source nts_business_registration
```

Source 요청 생성 검증:

```bash
.venv/bin/teoria verify source \
  --profile build \
  --source nts_business_registration \
  --operation get_business_registration_status \
  --input registries/sources/verification_cases/nts_business_registration/get_business_registration_status.yaml
```

`--profile live`는 같은 순서로 실제 API를 호출하고 응답 계약까지 검증한다. 인증정보는 출력이나 Registry에 저장하지 않고 CLI가 안내하는 환경변수로만 주입한다.

현재 검증기는 다음 항목을 확인한다.

- YAML 및 Pydantic 모델 구조
- Source와 Data Type ID 중복
- Source 내부 Object `ref`
- 공통 Data Type 참조
- Object 및 Operation ID 중복
- 요청의 `required` 필드 선언 여부
- 필드 타입별 `items`, `fields`, `default`, `max_items` 규칙
- HTTP method, path, content type, 오류 상태 코드
- 응답 `record_path` 문법과 Object 순환 참조

전체 검증 구조와 규칙은 [Source Registry 검증 구조](docs/registry/validation.md)를 참고한다.

