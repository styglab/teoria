# Runtime 실행과 artifact 배포

Runtime은 Source record를 Mapping으로 Runtime Object·Link에 변환하고 Capability를
실행한다. MCP와 외부 서비스는 이 HTTP API를 사용한다. Ontology 편집·승인과
지속 수집은 각각 Admin과 Pipelines가 담당한다.

## 요청이 처리되는 순서

```text
HTTP 요청 → Bearer 인증·OPA 정책 → 입력 검증 → Capability Runner
→ Source API 또는 Data DB 읽기 → Mapping → Object·Link와 provenance
```

| API | 용도 |
|---|---|
| `GET /health` | 프로세스 상태 |
| `GET /v1/version` | 적재한 Registry·Runtime version 확인 |
| `GET /v1/capabilities` | 공개 Capability와 입력 계약 발견 |
| `POST /v1/capabilities/{capability_id}:execute` | 검증된 입력으로 실행 |

실행 결과에는 식별자로 병합한 Object·Link와 원천 근거가 포함된다. Runner는
Source timeout, 재시도, 최대 페이지와 Capability deadline을 적용한다. 입력 계약과
실행 종류는 [Capability](registry/capabilities.md), 값 변환은 [Mapping](registry/mappings.md)을
참고한다. API의 전체 요청·응답 schema는 실행 중인 `/docs`가 기준이다.

## Registry release와 Runtime bundle

`platform/registries/`는 사람이 작성하는 계약 원본이다. Registry 발행은 그 내용을
검증해 version별 release로 고정한다. Runtime bundle 구성은 이 release와 Application
DB의 Published Ontology, Approved Binding snapshot, CapabilityVersion을 함께 고정한다.
운영 Runtime은 checksum 검증을 통과한 bundle만 읽는다.

게시된 Ontology와 승인된 Binding, 접근 가능한 Application DB를 먼저 준비한다.
아래 version은 예시이며 새 배포마다 고유한 version을 사용한다.

```bash
uv run --locked --package teoria-platform teoria validate platform/registries
uv run --locked --package teoria-platform teoria publish platform/registries \
  --version 2026.10.16.1 --output dist/registry
uv run --locked --package teoria-platform teoria compile-runtime-bundle \
  dist/registry/2026.10.16.1 --output dist/runtime \
  --version 2026.10.16.1
uv run --locked --package teoria-platform teoria activate-artifact dist/runtime \
  --version 2026.10.16.1
```

`compile-runtime-bundle`은 `TEORIA_APP_DATABASE_URL`을 사용한다. 기본 Ontology
namespace는 `teoria`이며 `--ontology-namespace`를 반복해 지정할 수 있다.
필요한 stable concept를 해석할 수 없거나 호환성이 맞지 않으면 구성이 실패한다.

`manifest.json`, `bundle.json`과 구성요소 checksum이 artifact의 무결성을 확인한다.
Registry checksum에는 파일 경로도 포함되므로 계약 파일 위치 변경도 새 release가 필요하다.
원본 Registry에 release 상태나 `.release.json`을 추가하지 않고 생성물은 Artifact Store에서
보관한다. 이미 발행한 version의 내용과 경로는 직접 수정하지 않는다.

## 실행과 version 전환

```bash
export TEORIA_RUNTIME_ARTIFACT_STORE=dist/runtime
export TEORIA_ENVIRONMENT=production
uv run --locked --package teoria-platform teoria-runtime-api
```

인증·DB·OPA 연결은 [환경 설정](../deployment/configuration.md)을 먼저 준비한다.
운영은 별도 Runtime bearer token과 `TEORIA_POLICY_MODE=opa`를 사용한다.
정책 서비스 장애나 undefined decision은 요청을 허용하지 않는다.

bundle 선택은 `TEORIA_RUNTIME_ARTIFACT_PATH`로 version 디렉터리를 직접 지정하거나,
`TEORIA_RUNTIME_ARTIFACT_STORE`의 `active.json`을 사용한다. 운영에서 둘 다 없으면
시작하지 않는다. 개발 환경에서만 원본 Registry를 직접 읽는 경로가 허용된다.

활성화 명령은 checksum을 검증한 뒤 active pointer를 원자적으로 교체한다.
실행 중인 프로세스는 시작할 때 bundle을 적재하므로, pointer 변경 뒤 Runtime과
해당 bundle을 사용하는 Admin 프로세스를 재시작·재배포하고 `/v1/version`을 확인한다.
되돌릴 때는 보존한 이전 version을 다시 활성화하고 같은 순서로 반영한다.

## 구현과 검증 위치

HTTP는 `platform/src/teoria/runtime/api.py`, 실행 조립은 `runtime/composition.py`,
Runner는 `runtime/capability/runner.py`, Source 실행은 `runtime/source/`, 값 변환은
`runtime/mapping/transforms/`가 소유한다. Domain handler는 공통 Runner에 등록한다.

artifact 검증·구성은 `registry/artifact.py`와 관련 모듈, App DB snapshot 조회는
`registry/artifact_snapshot.py`, 명령은 `cli/registry.py`에서 찾는다.
Runtime cache는 `runtime/cache/`가 소유한다. Redis 장애는 실행을 막지 않고 캐시 없이
동작한다. 정책 bundle 빌드·서명·서비스 시작 순서는 [Compose](../deployment/compose.md)를 따른다.

Source DB 실행과 시장 분석 reader는 native async PostgreSQL을 사용한다.
HTTP부터 Repository까지 `await`를 연결하고 분류 계층 보강 같은 내부 SQL helper도
같은 연결·transaction 안에서 완료를 기다린다. 동시 실행·취소의 기준은
[Platform 개발 안내](development.md#io와-동시-실행)를 따른다.
실제 기관 프로필·활동 검색과 분류 보강 경로의 배포 검증은
[2026-10-16 검증 기록](../verification/async_deployment_collection_2026_10_16.md)에 있다.
