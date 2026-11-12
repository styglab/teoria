# 문서 안내

처음 읽는다면 **사용 안내 → 아키텍처 → 저장소 구조** 순서로 시작한다.

| 목적 | 문서 |
|---|---|
| 화면 사용 | [사용 안내](platform-guide.md) |
| 플랫폼 경계·저장 권위 | [아키텍처](architecture/overview.md) |
| 변경할 코드 찾기 | [저장소 구조](architecture/repository-structure.md) |
| 설치·검사·개발 규칙 | [개발 안내](development.md) |
| 구현 범위·남은 작업 | [로드맵](roadmap.md) |

## 플랫폼

- [메타데이터 조회·진단·검토](platform/metadata.md)
- [Ontology·Binding](platform/ontology.md)
- [Runtime·Context·artifact 운영](platform/runtime.md)
- [Registry·Mapping·Capability](platform/registry/guide.md)
- [Source 작성·검증](platform/registry/source_authoring.md) · [작성 Skill](skills/source-registry-author.md)
- [MCP](mcp/gateway.md) · [관리 화면 개발](platform/admin_ui.md)

## 업무

- [물품 모델](domains/goods/model.md) · [표현 연결](domains/goods/expression_links.md)
- [규격서 처리](domains/goods/specifications/pipeline.md)
- [정규화 프로파일](domains/goods/specifications/normalization_profiles.md) · [추출 평가](domains/goods/specifications/evaluation.md)

## 배포·운영

- [배포 시작 안내](../deploy/README.md): Compose에 익숙한 개발자를 위한 구조와 명령
- [Kubernetes](deployment/kubernetes.md) · [K3s](deployment/k3s.md) · [환경 설정](deployment/configuration.md)
- [모델 실행·서빙](deployment/model_execution.md) · [모델 이미지 Registry](deployment/image_registry.md)
- [Prefect](pipelines/prefect.md) · [Connector](pipelines/connectors.md) · [Data DB](pipelines/database.md)
- [OpenMetadata Server·수집](deployment/openmetadata.md) · [법령 수집](pipelines/domains/legal_information.md)

검증 증거: [물품 Draft 준비](verification/goods_native_draft_preparation_2026_11_09.md).
