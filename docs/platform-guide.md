# Teoria 시작과 역할별 작업

Teoria는 데이터를 수집하고, OpenMetadata로 자산을 설명하고, Ontology·Binding으로
업무 의미를 연결한 뒤 Capability와 Context로 요청을 실행한다. 공공조달은 이 경로를
검증하는 첫 업무 도메인이다. 구성요소의 책임은 [전체 아키텍처](architecture/overview.md)를 따른다.

## 로컬 스택 시작

저장소 루트에서 환경 파일을 복사하고 의존성을 설치한다.

```bash
cp deploy/compose/.env.example deploy/compose/.env
uv sync --locked --all-packages --all-groups
```

`.env`의 필수 token·DB 암호·Prefect 인증정보를 준비한다.
현재 기본 배포는 첨부문서 처리용 S3 호환 저장소를 요구하지 않는다.
설정 이름과 기본값은 [환경 설정](deployment/configuration.md), 서비스 시작 조건은
[Compose](deployment/compose.md)를 따른다.

```bash
docker compose --env-file deploy/compose/.env \
  -f deploy/compose/compose.yaml up --build -d
```

| 대상 | 기본 주소 |
|---|---|
| Admin UI | `http://localhost:8081/` |
| Admin API 문서 | `http://localhost:8081/admin-api/docs` |
| Runtime API 문서 | `http://localhost:8081/runtime-api/docs` |
| Prefect UI | `http://localhost:8081/prefect/` |


OpenMetadata가 필요하면 `--profile metadata`를 추가한다. Server는 기본
`http://localhost:8585/`에서 확인한다. Server 시작만으로 메타데이터 수집이 실행되지는
않는다. [OpenMetadata 배포](deployment/openmetadata.md) 후 [수집 Job](pipelines/openmetadata.md)을 실행한다.

## 데이터 운영자: 수집부터 확인하기

수집 코드는 Compose와 K3s가 공유한다. K3s에서는 작업별 Job과 자원 예산·동시 실행 상한으로
병렬 실행을 제어한다. Compose는 Worker 전체 자원 상한을 사용하며 최신 수집 우선·Backfill
동시 실행 제한은 양쪽에 적용한다. 공통 정책은 [Prefect 운영](pipelines/prefect.md),
K3s 설정과 검증 범위는 [K3s 배포](deployment/k3s.md)를 따른다.

1. [배포 목록](pipelines/deployments.md)에서 수집 계약·Flow·파라미터를 찾는다.
2. [Prefect](pipelines/prefect.md)에서 실행하고 실패 Task와 재시도를 확인한다.
3. 수집 정의의 원본 보존 정책과 정규 적재 결과를 확인한 뒤 checkpoint 이동을 확인한다.
4. OpenMetadata Job을 실행해 수집된 테이블·view를 catalog에서 찾는다.

조달의 최신·보정·Backfill 수집은 [공공조달 수집](pipelines/domains/public_procurement.md),
법령 원문·시행 버전은 [법령 수집](pipelines/domains/legal_information.md)을 따른다. Flow를 수정할
때는 [Pipelines 개발 안내](pipelines/development.md)에서 구현과 검증 위치를 찾는다.

첨부파일 다운로드·문서 입찰요건 추출·참가자격 판단은 보류되어
[archive](../archive/bid_document_processing/README.md)에 보관한다. 현재 배포와 API에서 제공하지 않는다.

## Metadata 관리자: 자산을 이해하고 변경하기

1. [Admin 데이터 카탈로그](platform/admin_ui.md)에서 자산과 컬럼을 찾는다.
2. [자산 맥락](platform/metadata/asset_context.md)에서 기술·운영·의미·거버넌스 정보를 확인한다.
3. 설명 변경안을 직접 작성하거나 [자산 진단](platform/metadata/asset_assessment.md)을 요청한다.
4. [제안 검토·적용](platform/metadata/suggestions.md)에서 현재 값·근거·대상 version을 비교한 뒤 승인하고 적용 결과를 확인한다.

OpenMetadata entity는 Teoria DB로 복제하지 않는다. AI 결과는 Suggestion이며 승인과
적용 성공 전에는 권위 metadata가 아니다. 개방 진단은 법령 근거를 가진 검토 초안이며
법률 적용성이나 공개 승인을 확정하지 않는다. Codex로 작업하려면
[진단 Skills](skills/analyze_metadata_asset.md)의 별도 실행·제출 절차를 따른다.

## Ontology 담당자: 의미를 연결하고 게시하기

자산과 Glossary를 확인하고 Stable Concept에 Binding을 작성한다. 기본 경로는
`Physical Asset → OpenMetadata Glossary Term → Teoria Ontology`다. 직접 자산 Binding은
보조 연결이며 용어 경로보다 우선하지 않는다.

Binding Draft를 검토·승인하고, Ontology 변경은 현재 Published version에서 새 Draft를
만들어 검토·승인·게시한다. [Ontology와 이관](platform/ontology.md)을 따른다.
변경된 의미를 운영 실행에 반영하려면 [Runtime bundle](platform/runtime.md)을 구성·활성화하고 재배포한다.

## 개발자: 실행 기능 추가하기

요청 시 직접 호출하는 API는 [Source](platform/registry/source_authoring.md), 지속 수집하는
API는 [Connector](pipelines/connectors.md)로 작성한다. Pipeline이 적재한 DB를 조회할 때는
Database Source와 Mapping을 작성한다. 같은 API를 양쪽에 중복 등록하지 않는다.

[Platform 개발 안내](platform/development.md)에서 기능의 Domain과 진입점을 찾고,
[Registry 안내](platform/registry/guide.md)에 따라 Mapping·Capability를 정의한다.
조달 계산을 바꿀 때는 [집계 기준](platform/domains/public_procurement/contract_aggregation.md)을
먼저 확인한다. 검증한 계약은 bundle로 발행하고 API version을 확인한다.

## 클라이언트 개발자: 기능 발견과 호출

[MCP Gateway](mcp/gateway.md) 또는 Runtime HTTP API로 공개 Capability를 발견한다.
질문의 의미 조회·계획·실행은 [Context](platform/context.md)를 참고한다.
입력 schema는 discovery에서 가져오고 결과의 provenance·페이지·부분 실패를 확인한다.
외부 서비스의 권장 호출 순서는 [입찰체크 연동](integration/bid-check-service.md)을 따른다.
MCP에는 Source 키나 DB 권한을 주지 않는다.

## 변경 검증과 다음 단계

프로젝트별 테스트와 계약 검증은 [Platform](platform/development.md),
[Pipelines](pipelines/development.md), [MCP](mcp/gateway.md),
[Provider API](packages/provider_api.md)의 개발 안내를 따른다.
과거 종단 실행 결과는 [검증 기록](verification/index.md), 남은 제품 결과는
[로드맵](roadmap.md), 전체 문서 탐색은 [목차](index.md)에서 확인한다.

EC2의 K3s 배포와 main push 자동 배포는 [K3s 배포 안내](deployment/k3s.md)를 따른다.
