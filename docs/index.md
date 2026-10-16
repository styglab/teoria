# Teoria 문서

Teoria는 OpenMetadata의 데이터 자산과 Business Ontology·Capability를 연결하는
Metadata & Ontology Platform이다. 처음 사용할 때는 시작 안내를 읽고, 기능을 고치거나
운영할 때는 해당 프로젝트의 문서로 이동한다. 명령은 별도 안내가 없으면 저장소 루트에서 실행한다.

## 처음 시작하기

- [시작과 역할별 작업](platform-guide.md): 로컬 실행, 데이터 운영·메타데이터 관리·개발의 순서
- [전체 아키텍처](architecture/overview.md): 구성요소, 데이터 흐름과 권위 경계
- [저장소 구조](architecture/repository-structure.md): 코드·계약의 소유권과 의존 규칙
- [제품 로드맵](roadmap.md): 다음 결과와 완료 조건

## 작업별 문서 찾기

| 하려는 작업 | 먼저 읽을 문서 | 다음 문서 |
|---|---|---|
| 전체 스택 실행·설정 | [Compose](deployment/compose.md) | [환경변수·인증](deployment/configuration.md) |
| 처음 Prefect 파이프라인 작성 | [PostgreSQL ETL·검증·배포 따라 하기](pipelines/writing_pipelines.md) | [개발 안내](pipelines/development.md), [Connector](pipelines/connectors.md) |
| 수집 기능 추가·수정 | [Pipelines 개발](pipelines/development.md) | [Connector 작성](pipelines/connectors.md), [Data DB](pipelines/database.md) |
| 수집 실행·실패 복구 | [Prefect 운영](pipelines/prefect.md) | [배포 목록](pipelines/deployments.md), [조달 수집](pipelines/domains/public_procurement.md) |
| 메타데이터 수집 | [OpenMetadata Job](pipelines/openmetadata.md) | [Server 배포·업그레이드](deployment/openmetadata.md) |
| 법령 수집·버전 조회 | [법령 수집](pipelines/domains/legal_information.md) | [진단용 법령 검색](platform/metadata/law_evidence.md) |
| 자산 탐색·설명 변경 | [Admin UI](platform/admin_ui.md) | [자산 맥락·샘플·프로파일](platform/metadata/asset_context.md) |
| 자산 진단·제안 적용 | [자산 진단](platform/metadata/asset_assessment.md) | [제안 검토·적용](platform/metadata/suggestions.md), [Codex Skills](skills/analyze_metadata_asset.md) |
| Ontology·Binding 변경 | [의미 모델과 이관](platform/ontology.md) | [Runtime bundle 배포](platform/runtime.md) |
| Capability·Source·Mapping 개발 | [Platform 개발](platform/development.md) | [Registry 작성](platform/registry/guide.md) |
| 질문 계획·실행 | [Context](platform/context.md) | [Runtime](platform/runtime.md) |
| MCP 연결 | [MCP Gateway](mcp/gateway.md) | [외부 서비스 연동](integration/bid-check-service.md) |
| Provider wire 처리 수정 | [Provider API 라이브러리](packages/provider_api.md) | 각 소유 프로젝트의 Source·Connector 작성 문서 |

## 업무 정책과 외부 연동

공공조달의 의미·계산 기준은 Platform, 수집·문서 처리 절차는 Pipelines가 소유한다.

- [계약 집계 기준](platform/domains/public_procurement/contract_aggregation.md)과 [활동·참여 집계](platform/domains/public_procurement/activity_aggregation.md)
- [공고 상태](platform/domains/public_procurement/notice_status.md)
- [분야 분류와 확장 계획](platform/domains/public_procurement/procurement_classification.md)
- [시장 분석 구현](platform/domains/public_procurement/market_analysis.md)
- [입찰체크 연동](integration/bid-check-service.md), [탐색 계약](integration/procurement_exploration_contract.md)
- [Source 작성 Skill](skills/source-registry-author.md)

## 검증 기록과 실험 배포

[검증 기록 목차](verification/index.md)는 특정 날짜·version에서 확인한 결과와 한계를
보존한다. 현재 설정·스케줄·기능 수로 읽지 않는다. Kubernetes는
[EC2 K3s 자동 배포](deployment/k3s.md)와 로컬 Compose를 구분한다.

## 문서 작성과 정리 기준

문서 위치는 소유 프로젝트를 따른다. Platform의 조회·진단과 Pipelines의 수집은 같은
외부 시스템을 사용해도 구분한다. 전체 설계는 `architecture/`, 서비스 조립은
`deployment/`, 외부 호출 계약은 `integration/`, Skill 사용은 `skills/`에 둔다.

각 문서는 독자가 해결할 질문을 먼저 밝힌다. 개념 설명, 실행 절차, 계약 참조를
구분해 작성하고 같은 작업을 설명하는 짧은 문서는 합친다. 변경 이유·독자·검증 범위가
다른 정책은 독립 문서로 유지한다. 프로젝트 개발 안내는 코드 위치와 수정·검증 순서를
설명하고 상세 계약은 링크한다. 새 파일·폴더는 내용이 생길 때 만들며 빈 분류를 미리 만들지 않는다.

같은 규칙·설정·스케줄은 기준 문서 한 곳에서 관리한다. 실행 계약·Provider 원문·SQL은
소유 프로젝트에 유지하고 문서는 그 위치를 안내한다. 배포 목록은 YAML에서 생성한다.
시점별 수치·실행 ID·검증 환경은 `verification/`에, 다음 구현 범위는 로드맵에 둔다.

문서를 이동·통합할 때는 본문 링크, AGENTS·Skill 지침, 템플릿 참조, 문서 생성 코드와
테스트의 경로를 함께 바꾸고 링크를 검증한다. 이번 소유권별 재구성에서는 기존
`projects/`·`ingestion/`·`registry/`·`domains/` 문서를 해당 프로젝트로 옮겼다.
기존 저장소 내부 참조는 새 기준 문서를 가리키도록 갱신했으며, 외부에서 저장한 이전
경로는 Git 이력에서 찾을 수 있다. 루트 README를 제품 입구로 유지하고 하위 README는 만들지 않는다.

## 문서 변경 검증

문서를 추가·이동·통합하면 링크·제목 anchor와 목차 도달 여부를 검사한다.
자동 생성 배포 목록은 직접 편집하지 않고 YAML 변경 후 재생성한다.

```bash
python3 -m unittest discover -s tests/documentation
python3 tests/documentation/check_docs.py
uv run --locked --package teoria-pipelines teoria-pipelines deployment-docs --check docs/pipelines/deployments.md
```

`tests/documentation/check_docs.py`는 README·AGENTS·docs·저장소 Skill의 Markdown에서 로컬 링크를
검사하고 `docs/index.md`에서 모든 문서에 도달하는지 확인한다. 외부 URL은 요청하지 않는다.
기본 ATX 제목(`#` 형식)의 fragment도 검사한다. CI의 `documentation` Job이 같은 명령을 실행한다.
법령 수집 문서의 이전 `pipelines/law_collection.md` 경로는 `pipelines/domains/legal_information.md`로
이동했고 내부 참조를 함께 갱신했다. 계약 집계에서 옮긴 활동·참여 기준은 별도 문서로 연결한다.

EC2 자동 배포는 [K3s 배포](deployment/k3s.md)를 따른다.
