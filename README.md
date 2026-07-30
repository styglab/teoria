# Teoria

Teoria는 외부 데이터 소스를 온톨로지 의미로 연결하고, AI가 실행 가능한 Capability로 제공하는 AI context platform이다.

```text
Source Registry → Ontology Registry → Mapping Registry → Capability Registry
     원천 계약          도메인 의미           의미 연결             실행 단위
```

## 현재 제공 기능

- API Source 계약, 공통 Data Type과 Value Set 정의
- 한국 기업정보 Ontology와 Source–Ontology Mapping
- Capability 입력 바인딩, Source 호출, 응답 검증, 객체·링크 materialization
- 객체 및 속성 provenance
- Registry와 Provider Reference 정적 검증
- timeout, retry, 최대 페이지 및 Capability deadline
- Registry Capability를 자동 공개하는 MCP stdio 서버
- CLI와 Docker 기반 검증 실행

Registry 편집용 HTTP API와 Console은 현재 구조에 경계를 확보해 둔 향후 구현 범위다.

## 프로젝트 구조

```text
registries/
  core/                 공통 data types와 value sets
  sources/              원천 API 계약
  sources/verification_cases/
  domains/company/      ontology, mappings, capabilities
references/providers/   Source 작성 근거 문서와 metadata
src/teoria/
  registry/             schema, loader, resolver, validator, verification
  runtime/              source, mapping, capability 실행
  adapters/             CLI, MCP, secret provider
  transforms/           Mapping codec 함수
apps/console/            향후 Registry Explorer·관리 UI
deploy/                  Dockerfile과 Compose 구성
tests/                   단위·Registry 검증 테스트
archive/                 시점별 실행 결과와 과거 설계 산출물
```

## 개발 시작

```bash
uv sync --locked
cp .env.example .env
uv run --locked pytest
uv run --locked teoria validate registries
```

`.env`에는 필요한 Source API 키만 입력한다. 실제 비밀값이 든 `.env`는 Git에 포함하지 않는다.

특정 Source의 요청 생성까지 검증하려면 다음과 같이 실행한다.

```bash
uv run --locked teoria verify source \
  --profile build \
  --source nts_business_registration \
  --operation get_business_registration_status \
  --input registries/sources/verification_cases/nts_business_registration/get_business_registration_status.yaml
```

`--profile live`는 실제 API 호출과 응답 계약 검증까지 수행한다.

Docker에서 전체 Registry를 검증할 수도 있다.

```bash
docker compose -f deploy/compose.yaml build registry-check
docker compose -f deploy/compose.yaml run --rm registry-check
```

## 문서

- [문서 안내](docs/README.md)
- [Architecture](docs/architecture/overview.md)
- [Registry 공통 원칙](docs/registry/common.md)
- [Data Type과 Value Set](docs/registry/core_registry.md)
- [Ontology Registry](docs/registry/ontology_registry.md)
- [Registry 검증](docs/registry/validation.md)
- [Configuration](docs/configuration.md)
- [MCP 서버](docs/mcp.md)
- [Provider References](references/README.md)

Source 필드와 요청 파라미터 ID는 원본 시스템 표기를 보존한다. Teoria가 정의하는 Registry, Ontology, Mapping, Capability ID에는 `snake_case`를 사용한다.
