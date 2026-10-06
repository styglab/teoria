# Teoria 문서

처음 보는 경우 [Platform Guide](platform-guide.md)에서 구성과 역할별 사용
흐름을 확인하고, [Product Roadmap](roadmap.md)에서 현재 단계와 다음 완료
조건을 확인한다.

## 설계

- [Architecture](architecture/overview.md): 전체 구성
- [AI-Native Metadata Platform](architecture/ai-native-metadata-platform.md): Metadata·Ontology·Binding 권위와 목표 구조
- [Procurement Ontology Redesign](architecture/procurement-ontology-redesign.md): Palantir식 객체·사건·링크 원칙과 조달 Ontology 재구축안
- [Source-to-Object Matrix](architecture/source-to-object-matrix.md): 다중 원천의 객체·식별자·관찰·권위·충돌 정책
- [Ontology Source Profile](architecture/ontology-source-profile-2026-10-06.md): 운영 데이터의 식별·계보·연결·완전성 baseline
- [Repository Structure](architecture/repository-structure.md): 프로젝트 소유권과 의존
- [Semantic Governance](architecture/semantic-governance.md): 인증, 승인, Binding 생명주기와 조달 Ontology v2
- [Ontology Authoring](architecture/ontology-authoring.md): Stable Concept, version lifecycle, publish artifact
- [Legacy Registry Migration](architecture/legacy-registry-migration.md): 기존 Ontology/Capability를 중단 없이 분리·이전하는 기준
- [OpenMetadata Ingestion Orchestration](architecture/openmetadata-ingestion-orchestration.md): Airflow 없는 Prefect·ephemeral Job 운영 경계
- [PostgreSQL Deployment](architecture/postgresql-deployment.md): Data Plane과 Control/Application DB 배치·이전·분리 기준
- [Naming](architecture/naming.md): 코드·Registry·배포 이름
- [Configuration](configuration.md): 환경변수와 secret
- [Platform Guide](platform-guide.md): 플랫폼 구성, 실행, 역할별 사용법
- [Product Roadmap](roadmap.md): AI-Native vertical slice와 단계별 완료 조건

## Semantic Registry

- [공통 원칙](registry/common.md)
- [Data Type과 Value Set](registry/core_registry.md)
- [Source](registry/source_registry.md) / [작성 절차](registry/source-authoring.md)
- [Runtime Contract Registry](registry/runtime-contract-registry.md)
- [Mapping](../platform/registries/domains/company/mappings/README.md)
- [Capability](../platform/registries/domains/company/capabilities/README.md)
- [Validation](registry/validation.md)

## 실행

- [Connector와 Pipeline](ingestion/connectors.md)
- [Prefect 운영](ingestion/prefect.md)
- [MCP Gateway](mcp.md)
- [입찰체크 서비스 연동 가이드](integration/bid-check-service.md)
- [공공조달 Capability 현황](integration/public-procurement-capabilities.md)
- [Platform Admin UI](admin-ui.md)
- [Registry lifecycle](architecture/registry-lifecycle.md)
- [Source 작성 Skill](skills/source-registry-author.md)

Provider 원문은 소유 프로젝트의 `references/`에 둔다. `archive/`는 과거 산출물이며 현재 규격의 기준이 아니다.
