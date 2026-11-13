# Runtime 실행과 artifact 배포

Runtime은 Source record를 Mapping으로 Runtime Object·Link에 변환하고 Capability를
실행한다. MCP와 외부 서비스는 이 HTTP API를 사용한다. Ontology 편집·승인과
지속 수집은 각각 Admin과 Pipelines가 담당한다.

현재 활성 bundle `2026.10.25.1`에는 업무 Capability가 없다.
과거 조달 실행은 제공하지 않으며 물품 검색·비교는 후속 구현이다.

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
실행 종류는 [Capability](registry/guide.md), 값 변환은 [Mapping](registry/guide.md)을
참고한다. API의 전체 요청·응답 schema는 실행 중인 `/docs`가 기준이다.

## Registry release와 Runtime bundle

`backend/contracts/runtime/`는 사람이 작성하는 계약 원본이다. Registry 발행은 그 내용을
검증해 version별 release로 고정한다. Runtime bundle 구성은 이 release와 Application
DB의 Published Ontology, Approved Binding snapshot, CapabilityVersion을 함께 고정한다.
운영 Runtime은 checksum 검증을 통과한 bundle만 읽는다.

게시된 Ontology와 승인된 Binding, 접근 가능한 Application DB를 먼저 준비한다.
아래 version은 예시이며 새 배포마다 고유한 version을 사용한다.

```bash
uv run --locked --project backend --extra api teoria validate backend/contracts/runtime
uv run --locked --project backend --extra api teoria publish backend/contracts/runtime \
  --version 2026.10.16.1 --output dist/registry
uv run --locked --project backend --extra api teoria compile-runtime-bundle \
  dist/registry/2026.10.16.1 --output dist/runtime \
  --version 2026.10.16.1
uv run --locked --project backend --extra api teoria activate-artifact dist/runtime \
  --version 2026.10.16.1
```

`compile-runtime-bundle`은 `TEORIA_APP_DATABASE_URL`을 사용한다.
새 Registry에서 제거된 Capability·Source를 가리키는 Binding은 bundle snapshot에서 제외한다.
Application DB의 승인·검토 이력은 변경하지 않으며, 유지된 대상의 version·호환성 검사는 생략하지 않는다. 기본 Ontology
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
uv run --locked --project backend --extra api teoria-runtime-api
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

HTTP는 `backend/src/teoria/entrypoints/runtime_api.py`, 실행 조립은 `entrypoints/composition/runtime.py`,
Runner는 `platform/ontology/runtime/capability/runner.py`, Source 실행은 `platform/ontology/runtime/source/`,
값 변환은 `platform/ontology/contracts/codecs/`가 소유한다. Domain handler는 조립 시 공통 Runner에 주입한다.

artifact 검증·구성은 `platform/ontology/contracts/artifact.py`, App DB snapshot 조회는
`platform/ontology/bindings/publication_export.py`, 명령은 `entrypoints/commands/registry.py`에서 찾는다.
Runtime cache는 `runtime/cache/`가 소유한다. Redis 장애는 실행을 막지 않고 캐시 없이
동작한다. 정책 bundle 빌드·서명·서비스 시작 순서는 [Kubernetes 배포](../deployment/kubernetes.md)를 따른다.

Source DB 실행은 native async PostgreSQL을 사용한다. HTTP부터 Repository까지 `await`를
연결하며 transaction·승인·취소 경계를 보존한다. 이전 시장 분석 reader는 비활성 보관했다.

## Context

Context는 게시 의미·승인 Binding 조회와 업무 query handler의 계획·실행 정책 검증을 맡는다.
현재 물품 검색·비교 handler는 미등록이며 `plan`·`execute`는 미구성 오류를 반환한다.
과거 조달 질문으로 fallback하지 않는다.

| Admin API | 역할 |
|---|---|
| `GET /v1/admin/context/resolve?term=...` | 게시 의미·활성 bundle 연결 조회 |
| `POST /v1/admin/context/plan` | 등록 handler의 실행계획 작성 |
| `POST /v1/admin/context/execute` | 질문으로 계획을 다시 만들고 실행 |
| `POST /v1/admin/context/query` | execute의 deprecated 호환 경로 |

plan·execute는 관리자 인증과 각 단계 OPA 검증을 거친다. execute는 plan JSON/ID 재생 API가 아니다.
새 handler는 `platform/ontology/runtime/context/query.py` 계약을 구현해 `entrypoints/composition/`에서 주입한다.
업무 handler가 질문 해석·입력·결과를 맡고 공통 Engine은 의미 조회·정책 검증을 맡는다.

## 문서 요구조건의 게시 의미 조회

`get_goods_document_requirements`는 원문 관찰 → 승인 표현 연결 → 고정 프로파일 → Runtime 조회의 첫 경로다.
Registry 계약은 `validated` 상태이며 운영에서 자동 활성화하지 않는다. 업무 정의는 goods Ontology,
조회 응답은 별도 `goods_requirements.document` Runtime projection이다.

문서 본문·관찰을 DB에 다시 복제하지 않는다. 조회용 artifact는 승인된 연결과 프로파일로 적용한 관찰만 고정한다.
원문 hash·게시 개념·프로파일 revision·적용 규칙·표현 연결 mapping ID·값·단위·scope·근거를 함께 보존한다.
미연결·보류 관찰은 원래 추출 결과에 남고, 조회 artifact에는 보류 개수를 기록한다.

### 준비

먼저 실제 의미 검토·Ontology 게시·표현 연결 승인·프로파일 승인을 완료한다.
`TEORIA_SPECIFICATION_AUTHORING_API_URL`과 별도 bearer token을 설정한다.
아래는 입력 형식 예시다. 운영 version·UUID·URI·SHA256은 실제 export와 저장 참조로 바꾼다.

```json
{
  "version": "2026.11.10.1",
  "run_id": "approved_memory_run",
  "profile_revision_id": "승인된_프로파일_UUID",
  "extraction": {"uri": "s3://teoria-artifacts/.../extracted.json", "sha256": "원본_산출물_SHA256"},
  "alignment": {"uri": "s3://teoria-artifacts/.../source_term_alignment.json", "sha256": "연결_산출물_SHA256"},
  "execution_receipt": {"uri": "s3://teoria-artifacts/.../execution_receipt.json", "sha256": "실행_기록_SHA256"}
}
```

```bash
uv run --locked --project backend --extra api teoria-pipelines specification build-runtime-view \
  --manifest /path/to/runtime_view_input.json --output /path/to/goods_views
```

명령은 Admin의 승인 프로파일·표현 스냅샷·게시 Ontology를 읽는다. 저장된 resolved 표시는 신뢰하지 않고
승인 스냅샷에서 연결을 재해석하며 원문 hash·값·귀속·scope·단위와 프로파일을 다시 검증한다.
실행 receipt의 run/document·원본 hash·산출물 URI/hash가 입력과 일치해야 한다.
원문 관찰·Draft·승인 상태는 변경하지 않는다. 출력은 `<version>/view.json`이며 같은 version의 다른 내용을 덮어쓰지 않는다.

### Runtime 연결

검토한 Capability를 활성화한 새 Registry release와 Runtime bundle을 별도로 준비한다.
Runtime에 아래 두 값을 함께 설정한다. SHA256은 생성 명령의 `artifact.sha256`이다.

```dotenv
TEORIA_GOODS_RUNTIME_VIEW_PATH=/app/runtime_artifacts/goods_views/2026.11.10.1/view.json
TEORIA_GOODS_RUNTIME_VIEW_SHA256=실제_파일_SHA256
```

Runtime은 파일 hash·내부 checksum·version 디렉터리·개념 소유 관계와 bundle의 게시 version/checksum을 검증한다.
불일치는 시작을 차단한다. 활성 Capability에 고정 view가 없거나 검증된 bundle 없이 view만 지정해도 시작하지 않는다.
요청 중에는 메모리에 적재한 불변 view만 읽으며 작성 DB·Admin API·원본 Registry를 조회하지 않는다.
Kubernetes의 `runtime-artifacts` PVC에 view를 배치하고 Runtime에 읽기 전용으로 마운트한다.
위 환경변수를 명시하며 실제 배포 성공은 별도 검증한다.

FormatID의 프로파일 적용 결과에서 **게시 의미로 조회**를 열면 `metadata_admin` 인증을 가진 Admin → Runtime HTTP 경계를 거친다.
run/document로 범위를 고정하고 최대 100개씩 조회하며 게시되지 않은 문서를 빈 성공으로 표시하지 않는다.
호출 주체·역할은 인증 principal에서 전달한다. 원문 추출값은 기존 결과 화면에서 확인한다.

검증: `backend/tests/integration/test_goods_runtime_view.py`의 격리 게시 fixture에서 모듈당 32GB의
값·scope·승인 연결·원문 근거·bundle version을 HTTP까지 대조한다. 운영 goods Draft를 게시하거나
실문서 자동 연결 정확도를 승인한 결과는 아니다.
