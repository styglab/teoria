# Teoria 문서

문서는 현재 계약과 운영 방법만 유지한다. 완료된 migration 과정과 시점별 분석은
Git 이력에서 확인하며 현재 규칙처럼 복제하지 않는다.

## 시작점

- [Platform guide](platform-guide.md): 실행과 역할별 작업 흐름
- [Architecture](architecture/overview.md): 시스템과 데이터 권위 경계
- [Repository structure](architecture/repository-structure.md): 프로젝트 소유권
- [Ontology](architecture/ontology.md): Business Ontology와 Binding 계약
- [Product roadmap](roadmap.md): 남은 제품 결과와 완료 조건

## 작성과 운영

- [Registry guide](registry/README.md)
- [Source authoring](registry/source-authoring.md)
- [Connector](ingestion/connectors.md)와 [Prefect](ingestion/prefect.md)
- [Configuration](configuration.md)
- [Deployment](../deploy/README.md)
- [Admin UI](admin-ui.md)와 [MCP](mcp.md)
- [입찰체크 연동](integration/bid-check-service.md)
- [Source authoring skill](skills/source-registry-author.md)

Provider 원문은 해당 프로젝트의 `references/providers/`에 둔다. 검증 결과를
별도 보관해야 할 때만 목적과 보존 기간이 드러나는 경로를 명시적으로 만든다.
