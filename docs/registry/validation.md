# Registry 검증 구조

Registry 정적 검증은 네트워크에 의존하지 않는다. 사람이 작성한 Registry와 Provider Reference metadata가 Teoria 계약을 만족하는지 결정한다.

## 책임 경계

```text
registries/*.yaml
      │
      ▼
registry/schema/     Pydantic 메타모델과 단일 노드 규칙
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
adapters/cli/        종료 코드와 사용자 출력
```

실제 API 호출은 `runtime/source/` 계층에서 담당한다. 실행 순서와 조건 분기는 `registry/verification/source/`의 LangGraph가 담당한다.

## 확정 디렉터리

```text
src/teoria/
├── config.py
├── registry/
│   ├── schema/
│   ├── verification/source/
│   ├── loader.py
│   └── validator.py
├── runtime/
│   ├── source/
│   └── capability/
└── adapters/
    ├── cli/
    ├── mcp/
    └── secrets/

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
16. Provider Reference metadata, 문서 파일 및 Source 연결

이 정적 검증은 실제 API의 현재 가용성이나 실제 응답값까지 보장하지 않는다. 그 부분은 Source Verification의 `live` profile이 담당한다.

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

현재 전체 Registry의 성공 출력은 로드된 항목 수를 함께 보여준다.

```text
Validated 3 sources, 1 ontology, 1 mapping, 11 data types, 9 value sets, 3 provider references, and 5 capabilities.
```

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
export TEORIA_SOURCE_NTS_BUSINESS_REGISTRATION_API_KEY="..."

teoria verify source \
  --profile live \
  --source nts_business_registration \
  --operation get_business_registration_status \
  --input registries/sources/verification_cases/nts_business_registration/get_business_registration_status.yaml
```

자격증명이 없으면 Live Workflow는 통과하지 않으며 `BLOCKED`로 종료한다. 비밀값은 Graph State나 출력에 기록하지 않는다. 최종 성공 상태는 프로필별로 `VALID`(static), `BUILDABLE`(build), `VERIFIED`(live)로 구분한다.

Live 실행은 Source 요청 timeout, 최대 시도 횟수와 구조화 오류를 적용한다. Capability 실행에는 추가로 최대 페이지 수와 전체 deadline을 적용한다. 상세 설정과 오류 코드는 [Configuration](../configuration.md)을 참고한다.
