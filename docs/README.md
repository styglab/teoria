# Teoria 문서

## 설계

- [Architecture](architecture/overview.md): 전체 구성
- [Repository Structure](architecture/repository-structure.md): 프로젝트 소유권과 의존
- [Naming](architecture/naming.md): 코드·Registry·배포 이름
- [Configuration](configuration.md): 환경변수와 secret

## Semantic Registry

- [공통 원칙](registry/common.md)
- [Data Type과 Value Set](registry/core_registry.md)
- [Source](registry/source_registry.md) / [작성 절차](registry/source-authoring.md)
- [Ontology](registry/ontology_registry.md)
- [Mapping](../platform/registries/domains/company/mappings/README.md)
- [Capability](../platform/registries/domains/company/capabilities/README.md)
- [Validation](registry/validation.md)

## 실행

- [Connector와 Pipeline](ingestion/connectors.md)
- [Prefect 운영](ingestion/prefect.md)
- [MCP Gateway](mcp.md)
- [Registry lifecycle](architecture/registry-lifecycle.md)
- [Source 작성 Skill](skills/source-registry-author.md)

Provider 원문은 소유 프로젝트의 `references/`에 둔다. `archive/`는 과거 산출물이며 현재 규격의 기준이 아니다.
