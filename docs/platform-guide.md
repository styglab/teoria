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

첨부파일 다운로드·문서 입찰요건 추출·참가자격 판단은 현재 배포와 API에서 제공하지 않는다.
당시 보류·제거 범위는 [검증 기록](verification/bid_document_archive_2026_10_16.md)에 남아 있다.
해당 파일 보관본은 현재 저장소에서 제거되었다.

후속 기능의 범위·데이터 모델·검증 단계는
[조달 규격 인텔리전스 서비스 설계 초안](procurement_specification_intelligence/overview.md)을
참고한다. 설계 제안이며 현재 보류 정책이나 실행 기능을 변경하지 않는다.
이전 메타데이터 후보 식별기와 평가 코드는 삭제했다. 이후 사용자 요청으로
[물품 공통 확인 우선순위](procurement_specification_intelligence/document_identification.md)를
구현하고 [서버 문서 최소 파싱](procurement_specification_intelligence/computer_server_validation.md)을
검증했다. 개발 실험이며 수집 배포·API에 연결하지 않았다. 메타데이터 우선순위와
실제 규격 포함 여부의 내용 검수를 구분하며 전체 파싱 계약은 후속 설계다.
[규격서 선별 적정성 평가](procurement_specification_intelligence/selection_evaluation_2026_10_20.md)는
kordoc을 고정한 새 공고 20건의 개발·평가 결과와 공통 규칙 v2, 미확인·실패 사례를 기록한다.
현재 후보 선정은 Precision 우선 v3다. 이후 [OCR 제외 파서 비교](procurement_specification_intelligence/parser_evaluation_2026_10_20.md)에서
기존 후보 10개와 6개 도구를 진단하고, [독립 파싱 모듈 설계](procurement_specification_intelligence/document_parsing.md)에
kordoc·형식별 원본 검사 조합과 최소 데이터 계약을 정리했다. 전체 파싱 모듈과 운영
연결은 아직 구현하지 않았다.
현재 [Codex 직접 분석](procurement_specification_intelligence/codex_analysis.md)과
[구성품·세부 규격 연결](procurement_specification_intelligence/composition_analysis.md)을
사용한다. 주요 구성·하위 대상·외부 참조를 구별하고 대표 규격을 실제 대상에 연결한다.
저장된 네 문서에서 주요 목록 28개와 대표 규격 27개를 검토했다. 사용자 검토안을
이미 본 개발 표본이며 독립 정확도나 전체 속성 추출 완료를 뜻하지 않는다.

예전 품목·구성요소·요구조건·통합·사전 구축 모듈과 전용 테스트·실험 스크립트는
삭제했다. 원본·파싱 결과와 과거 결과 JSON/CSV는 보존했다. 예전 사전 52개는
과거 참고 초안이며 현재 입력 사전이 아니다. 새 [초기 사전 구축 경로](procurement_specification_intelligence/dictionary_building_pipeline.md)는
원문 관찰·의미 통합·초안·최종 검토·수정·재검증·로컬 승인을 지원한다.
Codex가 의미 제안을 작성한다. [실제 서버 공고 10건의 재검증](procurement_specification_intelligence/verification/server_dictionary_bootstrap_2026_10_20.md)에서
원문 관찰 385개·속성 정의 후보 152개를 만들었다. 미해결 문제 19개가 남아 미승인 상태다.
후속 [속성 단위 감사](procurement_specification_intelligence/attribute_registry.md#현재-초안의-과분리와-재검토)에서
중복·표현 차이·요구 문장이 섞인 것을 확인했다. 152개는 정제된 표준 속성 수가 아니다.
구조 검사와 의미 검토는 별개이고 자동 승인·운영 Flow·API 연결은 없다.
후속 [검색 평가·개선 CLI](procurement_specification_intelligence/search_evaluation_pipeline.md)는
공고 단위 80/20 분리·Codex 원문 질문 정답 생성과 별도 검토·구조화 결과 평가·
Harness2 프롬프트 제안과 개발셋 선택·검증셋 비교를 자동화한다.
정답은 사람 검수 전 silver label이며 속성 사전 후보는 개발 관찰에서만 만든다.

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
