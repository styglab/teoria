# Teoria Provider API

Provider API는 Runtime Source와 수집 Connector가 함께 사용하는 백엔드 내부 연결 모듈이다.
구현은 `backend/src/teoria/integrations/provider_api/`에 두며 별도 배포·Python 프로젝트로 관리하지 않는다.

## 책임

포함 범위:

- Provider API wire contract schema
- 입력 검증과 HTTP request 생성
- HTTP 실행, credential interface, retry와 구조화 오류
- 응답 record path와 wire type 검증

포함하지 않는 범위:

- Semantic Registry, Ontology, Mapping, Capability
- Pipeline Definition, Prefect Flow, 정규화와 DB 적재
- MCP 또는 Runtime HTTP client

## 코드와 설정 위치

테스트는 `backend/tests/integrations/provider_api/`, 의존성은 `backend/pyproject.toml`이 소유한다.
이 문서의 `docs/packages/` URL은 기존 링크 호환을 위해 유지한다.

## 요청이 처리되는 순서

`schema.py`가 wire 계약을 표현하고 `validator.py`가 계약을 검증한다.
`request_builder.py`는 입력을 HTTP 요청으로 만들고, `executor.py`는 인증정보 주입·HTTP
실행·재시도를 수행한다. `response_validator.py`는 record path와 응답 타입을 검증한다.
인증정보 경계는 `secrets.py`, 오류와 진단은 `errors.py`·`diagnostics.py`에서 찾는다.

Platform과 Pipelines가 각자의 실행·적재 정책을 유지하면서 같은 Provider wire 처리만
공유한다. 기능의 Registry·Flow·Runtime 구현을 이 연결 모듈에서 역으로 import하지 않는다.

## 검증

```bash
uv run --locked --project backend pytest backend/tests/integrations/provider_api
```

## 상세 문서

호출 프로젝트의 계약 작성은 [Source authoring](../platform/registry/source_authoring.md)과
[Connector 작성](../pipelines/connectors.md)을 따른다.
