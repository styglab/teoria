# Teoria 문서

현재 코드와 Registry를 이해하거나 수정할 때 다음 순서로 읽는다.

1. [Architecture](architecture/overview.md): 모듈 경계와 배포 단위
2. [Naming](architecture/naming.md): 코드·Registry·배포 네이밍
3. [Registry 공통 원칙](registry/common.md): 각 Registry의 책임과 참조 형식
4. [Data Type과 Value Set](registry/core_registry.md): 공통 값 형식과 표준 코드
5. [Source Registry](registry/source_registry.md): 원천 API 계약 작성법
6. [Ontology Registry](registry/ontology_registry.md): Object, Property, Link의 의미 설계
7. [Mapping Registry](../registries/domains/company/mappings/README.md): Source 필드와 Ontology 속성 연결
8. [Capability Registry](../registries/domains/company/capabilities/README.md): AI가 호출하는 실행 단위
9. [Registry 검증](registry/validation.md): 정적·Build·Live 검증
10. [Configuration](configuration.md): 환경변수, secret, 실행 한도
11. [MCP](mcp.md): Capability 도구 공개와 실행
12. [Registry lifecycle](architecture/registry-lifecycle.md): 향후 publication 운영 모델

외부 기관 문서의 보존 규칙은 [Provider References](../references/README.md)에 있다. `archive/`는 특정 실행 결과나 과거 설계 산출물이며 현재 규격 문서의 기준으로 사용하지 않는다.
