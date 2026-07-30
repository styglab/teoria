# Registry 검증 구조

Registry 정적 검증은 원본 문서(`raw/`)와 네트워크에 의존하지 않는다. 사람이 작성한 Source, Data Type, Value Set, Ontology YAML이 Teoria 계약을 만족하는지 결정한다.

## 책임 경계

```text
registries/*.yaml
      │
      ▼
models/              Pydantic 메타모델과 단일 노드 규칙
      │
      ▼
registry/loader.py   YAML 문법, 중복 키, 파일 로딩
      │
      ▼
registry/validator.py ID, 참조, 타입, 요청·응답 의미 규칙
      │
      ▼
diagnostics.py       코드, 파일, 위치, 메시지
      │
      ▼
cli.py               종료 코드와 사용자 출력
```

실제 API 호출은 `execution/source/` 계층에서 담당한다. 실행 순서와 조건 분기는 `verification/source/`의 LangGraph가 담당하며, 실행 서비스는 LangGraph에 의존하지 않는다.

## 확정 디렉터리

```text
src/teoria/
├── models/
│   ├── common.py
│   ├── data_type.py
│   ├── ontology.py
│   ├── value_set.py
│   └── source.py
├── registry/
│   ├── diagnostics.py
│   ├── loader.py
│   ├── resolver.py
│   └── validator.py
└── cli.py

src/teoria/execution/source/
├── models.py
├── request_builder.py
├── executor.py
└── response_validator.py

src/teoria/verification/
├── core/
└── source/
    ├── state.py
    └── graph.py

tests/
├── unit/
├── fixtures/
└── registry_cases/
```

## 검증 순서

1. YAML 문법과 중복 키
2. Pydantic 메타모델
3. 파일명과 Source ID
4. Source, Object, Operation, Field ID 중복
5. Object `ref`와 공통 `data_type` 참조
6. 배열, 객체, 기본값, enum 등 필드 규칙
7. `required` 범위와 대상 필드
8. HTTP method, path, content type, 오류 상태
9. 응답 schema와 `record_path`
10. 객체 참조 순환
11. Value Set 및 표준값 ID 중복
12. Ontology Object type과 Property ID 중복
13. Property의 Data Type 및 Value Set 참조
14. Object primary key 참조
15. Link type endpoint 및 cardinality

## 실행

전체 Registry:

```bash
teoria validate registries
```

Source 하나:

```bash
teoria validate registries --source nts_business_registration
```

성공하면 종료 코드 `0`, 하나라도 오류가 있으면 종료 코드 `1`을 반환한다.

## Source Verification Workflow

```text
validate_structure
        ↓
   profile=static ───────────────→ complete
        ↓
build_request
        ↓
   profile=build ────────────────→ complete
        ↓
check_credentials
        ↓
execute_request
        ↓
validate_response
```

요청 생성까지만 검증:

```bash
teoria verify source \
  --profile build \
  --source nts_business_registration \
  --operation get_business_registration_status \
  --input registries/sources/verification_cases/nts_business_registration/get_business_registration_status.yaml
```

실제 API 호출과 응답 검증:

```bash
export NTS_BUSINESS_REGISTRATION_SERVICEKEY="..."

teoria verify source \
  --profile live \
  --source nts_business_registration \
  --operation get_business_registration_status \
  --input registries/sources/verification_cases/nts_business_registration/get_business_registration_status.yaml
```

자격증명이 없으면 Live Workflow는 통과하지 않으며 `BLOCKED`로 종료한다. 비밀값은 Graph State나 출력에 기록하지 않는다. 최종 성공 상태는 프로필별로 `VALID`(static), `BUILDABLE`(build), `VERIFIED`(live)로 구분한다.
