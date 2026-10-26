# Teoria 문서

현재 활성 업무는 명시 입력 규격서의 파싱·물품 정보 추출·표준 후보 관리와 물품 Ontology 구축이다.
Ontology·Binding·Mapping·Capability·Runtime·OpenMetadata·Prefect 기반은 유지한다.
기존 기업·공고·계약·낙찰 수집과 분석은 비활성 보관했다.
법령 수집·조회는 메타데이터 진단의 근거 저장소로 재개했다.
명령은 별도 안내가 없으면 저장소 루트에서 실행한다.

## 처음 시작하기

- [시작과 역할별 작업](platform-guide.md): 현재 실행 경로·입력·저장소·초안과 게시 경계
- [전체 아키텍처](architecture/overview.md), [저장소 구조](architecture/repository-structure.md): 시스템 책임과 코드 소유권
- [제품 로드맵](roadmap.md): 추출 결과와 Ontology 연결·물품 Capability의 남은 범위
- [현재 배포 검증](verification/goods_focus_deployment_2026_10_25.md): 실제 Compose 전환·bundle·Worker·모델·초안 상태

## 현재 작업별 안내

| 작업 | 안내 |
|---|---|
| 규격서 실행·후보 관리·표준 적용 | [규격서 처리 목차](procurement_specification_processing/index.md), [파이프라인 계약](procurement_specification_processing/pipeline.md) |
| 추출 품질 개선·평가 | [고정 평가 절차](procurement_specification_processing/evaluation.md) |
| 서버 요구조건 검색·비교·근거 조회 | [서버 Capability](procurement_specification_processing/server_capabilities.md) |
| 물품 Ontology 작성·검토·게시 | [Ontology](platform/ontology.md), [Admin UI](platform/admin_ui.md) |
| 자산·Glossary·Concept 연결 | [자산 맥락](platform/metadata/asset_context.md), [제안 검토·적용](platform/metadata/suggestions.md) |
| 법령 수집·조회 | [법령 운영](pipelines/domains/legal_information.md), [진단 근거](platform/metadata/law_evidence.md), [복구 검증](verification/law_recovery_2026_10_25.md) |
| 메타데이터 진단 | [자산 진단](platform/metadata/asset_assessment.md), [진단 Skills](skills/analyze_metadata_asset.md) |
| Runtime 계약과 배포 | [Registry](platform/registry/guide.md), [Runtime](platform/runtime.md), [Context](platform/context.md) |
| 로컬 배포·환경 설정 | [Compose](deployment/compose.md), [설정·인증](deployment/configuration.md) |
| Prefect 작업 실행·재시도 | [운영](pipelines/prefect.md), [선언된 배포 목록](pipelines/deployments.md), [Data DB](pipelines/database.md) |
| OpenMetadata 실행·수집 | [Server](deployment/openmetadata.md), [격리 ingestion Job](pipelines/openmetadata.md) |
| 코드 변경 | [Platform](platform/development.md), [Pipelines](pipelines/development.md), [Provider API](packages/provider_api.md) |
| MCP 연결 | [Gateway](mcp/gateway.md) |
| EC2 K3s 설정 | [K3s](deployment/k3s.md), [이전 실험](deployment/experimental_k3s.md) |

새 Source·Connector를 실제로 추가할 때만 [Source 작성](platform/registry/source_authoring.md),
[Source Skill](skills/source-registry-author.md), [Connector 작성](pipelines/connectors.md)을 사용한다.
현재 Runtime Provider Source는 없고 Pipeline Connector는 법령용 `moleg_law_api` 하나다. [파이프라인 작성 안내](pipelines/writing_pipelines.md)에서 현재 기능의 작성 위치를 확인한다.
일반 주문 ETL 예제는 `archive/examples/db_sales/`로 보관하며 운영에 등록하지 않는다.

## 과거 업무 구현과 검증 기록

아래 문서는 이전 조달·법령 기능의 정책·연동·시점별 결과다. 현재 기능으로 재등록하거나
문서의 과거 건수·성공을 현재 배포 상태로 사용하지 않는다.
실행 코드·계약·전용 테스트는 `archive/procurement_services/`에 있다.

- [과거 조달 수집](pipelines/domains/public_procurement.md)
- [과거 계약 집계](platform/domains/public_procurement/contract_aggregation.md), [활동·참여 집계](platform/domains/public_procurement/activity_aggregation.md)
- [과거 시장 분석](platform/domains/public_procurement/market_analysis.md), [공고 상태](platform/domains/public_procurement/notice_status.md), [분야 분류](platform/domains/public_procurement/procurement_classification.md)
- [과거 입찰체크 연동](integration/bid-check-service.md), [탐색 계약](integration/procurement_exploration_contract.md)
- [검증 기록 목차](verification/index.md): 당시 version·데이터·검증 범위와 한계

## 문서 관리 기준

현재 계약과 절차는 소유 프로젝트의 안내에 갱신한다. 날짜·version에 종속된 결과는
`verification/`에 보관한다. 기존 링크를 보존하며 문서 검증은 `tests/documentation/`에서 수행한다.
문서·저장소·실제 배포와 추출 품질 평가의 완료 상태를 구분한다.
