# Teoria 문서

**사용 → 기능 이해 → 운영 → 개발** 순서로 찾는다. 현재 설명과 과거 실험 기록은 분리했다.
명령은 별도 안내가 없으면 저장소 루트에서 실행한다.

## 처음 읽을 문서

| 문서 | 알 수 있는 것 |
|---|---|
| [사용 안내](platform-guide.md) | 화면별 작업과 데이터 흐름 |
| [아키텍처](architecture/overview.md) | 시스템별 책임과 저장 위치 |
| [로드맵](roadmap.md) | 구현된 기능·한계·다음 작업 |

## 기능별 안내

| 기능 | 안내 |
|---|---|
| 규격서 분석 | [시작](procurement_specification_processing/index.md) · [단계와 Codex](procurement_specification_processing/pipeline.md) · [품질 평가](procurement_specification_processing/evaluation.md) |
| 물품 의미 모델 | [물품·구성품·분류·속성](architecture/specification_goods_model.md) · [사전](platform/goods_dictionary.md) · [프로파일](procurement_specification_processing/normalization_profiles.md) |
| Ontology·의미 연결 | [작성·승인·게시](platform/ontology.md) · [자산 맥락](platform/metadata/asset_context.md) · [변경 제안](platform/metadata/suggestions.md) |
| 메타데이터 진단 | [자동 진단](platform/metadata/asset_assessment.md) · [법령 근거](platform/metadata/law_evidence.md) · [진단 Skill](skills/analyze_metadata_asset.md) |
| Runtime·AI 연결 | [Registry](platform/registry/guide.md) · [Runtime](platform/runtime.md) · [Context](platform/context.md) · [MCP](mcp/gateway.md) |
| 관리 화면 | [화면 사용·프런트엔드 개발](platform/admin_ui.md) |

## 설치와 운영

| 작업 | 안내 |
|---|---|
| 환경 설정·인증 | [설정 기준](deployment/configuration.md) |
| 로컬 실행·Worker 반영 | [Compose](deployment/compose.md) |
| EC2 배포 구성 | [K3s](deployment/k3s.md) — 구성 검증과 실제 배포 성공은 별도 |
| OpenMetadata | [서버 배포](deployment/openmetadata.md) · [메타데이터 수집](pipelines/openmetadata.md) |
| 파이프라인 운영 | [Prefect](pipelines/prefect.md) · [선언된 배포 목록](pipelines/deployments.md) · [Data DB](pipelines/database.md) |
| 법령 수집·조회 | [법령 전용 파이프라인](pipelines/domains/legal_information.md) |

## 개발

[저장소 구조](architecture/repository-structure.md)에서 소유 기능을 먼저 확인한다.

- [의미 모델·Runtime 개발](platform/development.md)
- [수집·문서 처리 개발](pipelines/development.md) · [Flow 작성 위치](pipelines/writing_pipelines.md)
- [Source 작성](platform/registry/source_authoring.md) · [Connector 작성](pipelines/connectors.md)
- [Provider 연결 모듈](packages/provider_api.md) · [Source 작성 Skill](skills/source-registry-author.md)

## 기록과 보관

- [검증 기록](verification/index.md): 실제 실행·배포의 입력·버전·결과·한계.
- [과거 문서](../archive/documentation/index.md): 이전 설계·삭제한 실험·비활성 조달 업무. 현재 실행 안내로 사용하지 않는다.
