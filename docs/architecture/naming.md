# Naming conventions

## Product components

- **Teoria Registry**: Source, ontology, mapping, capability, data type and value-set definitions.
- **Teoria Runtime**: Executes published capabilities.
- **Teoria MCP**: Exposes capabilities to AI clients.
- **Teoria API**: HTTP interface for registry management and execution.
- **Teoria Console**: Web interface containing Explorer, Lineage, Capabilities, Validation and Changes.

## Code

- Python modules, functions and variables use `snake_case`.
- Classes use `PascalCase`; exceptions end with `Error`; results end with `Result`.
- Avoid generic modules such as `utils.py`, `helpers.py`, `manager.py` and `service.py`; name the responsibility, such as `validator.py`, `materializer.py` or `publisher.py`.
- Registry YAML models live under `teoria.registry.schema`; runtime result models live under `teoria.runtime`.

## Registry identifiers

- Object types are singular nouns: `legal_entity`.
- Properties name values: `opened_date`.
- Link types expose direction: `legal_entity_has_business_registration`.
- Capabilities describe user intent with verbs: `get_company_profile`.
- Source operations describe provider actions: `list_affiliates`.

## Configuration and deployment

- Environment variables use the `TEORIA_` prefix. The registry root is `TEORIA_REGISTRY_PATH`.
- 배포 이미지의 목표 이름은 `teoria-api`, `teoria-mcp`, `teoria-console`이다. 현재 Compose 검증 서비스는 로컬 프로젝트 이름을 사용한다.
- HTTP resources use plural nouns under `/api/v1`; executions and publications are resources rather than hidden side effects.
