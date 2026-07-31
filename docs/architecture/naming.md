# Naming conventions

## 제품과 프로젝트

- **Teoria Semantic Platform** / `platform/` / distribution `teoria-platform`
- **Teoria Data Pipelines** / `pipelines/` / distribution `teoria-pipelines`
- **Teoria MCP Gateway** / `mcp/` / distribution `teoria-mcp`
- **Teoria Console** / `platform/console/`

실행 명령은 `teoria`, `teoria-pipelines`, `teoria-mcp`를 사용한다. Docker 이미지도 각각 `teoria-platform`, `teoria-pipelines`, `teoria-mcp`로 명명한다.

## 코드

- Python module, 함수와 변수는 `snake_case`를 사용한다.
- Class는 `PascalCase`, 예외는 `Error`, 결과는 `Result`로 끝낸다.
- `utils.py`, `helpers.py`, `manager.py`, `service.py` 같은 일반 이름을 피하고 `validator.py`, `materializer.py`, `checkpoints.py`처럼 책임을 이름에 표시한다.
- Semantic Registry schema는 `teoria.registry.schema`에 둔다.
- Runtime 결과 모델은 `teoria.runtime`에 둔다.
- Prefect Flow와 수집 구현은 `teoria_pipelines`에만 둔다.
- MCP protocol 코드는 `teoria_mcp`에만 둔다.

## Registry ID

- Object Type: 단수 명사, 예: `legal_entity`
- Property: 값의 의미, 예: `opened_date`
- Link Type: 방향이 드러나는 관계, 예: `legal_entity_has_business_registration`
- Capability: 사용자 의도를 나타내는 동사, 예: `get_company_profile`
- Source Operation: Provider 동작, 예: `list_affiliates`
- Ingestion Connector: Provider 기반 ID, 예: `pps_contract_api`
- Database Source: 소유 시스템과 의미 도메인, 예: `teoria_public_procurement`
- Pipeline: 지속 업무, 예: `pps_contract_ingestion`

Provider는 Source와 Connector에, 의미 경계는 Domain에 나타낸다. 여러 Provider가 같은 객체·식별자·관계와 사용자 질문을 공유하면 하나의 Domain으로 통합한다.

## 환경변수

- 모든 Teoria 환경변수는 `TEORIA_` 접두사를 사용한다.
- Semantic Registry 루트: `TEORIA_REGISTRY_PATH`
- Pipeline 프로젝트 루트: `TEORIA_PIPELINE_PATH`
- Pipeline에서 참조할 Platform Registry: `TEORIA_PLATFORM_REGISTRY_PATH`
- Source 비밀키: `TEORIA_SOURCE_<SOURCE_ID>_API_KEY`
- Connector 비밀키: `TEORIA_CONNECTOR_<CONNECTOR_ID>_API_KEY`
