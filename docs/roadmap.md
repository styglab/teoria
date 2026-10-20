# Teoria product roadmap

로드맵은 완료된 migration 일지가 아니라 남은 제품 결과와 완료 조건만 관리한다.
현재 구현 사실은 코드, Registry와 [Architecture](architecture/overview.md)가 기준이다.

## 현재 제공하는 기반

- [Pipelines](pipelines/development.md): Connector·Prefect 수집, 원본·정규 적재와 Data DB
- [Prefect 실행 정책](pipelines/prefect.md): 두 배포의 공통 등록·Queue 우선순위·동시 실행 상한.
  Compose는 Worker 전체 제한, [K3s](deployment/k3s.md)는 작업별 Job·자원 예산을 적용한다.
  실제 EC2에서의 병렬 실행·자원 포화 검증은 남아 있다.
- [Platform Runtime](platform/runtime.md): Source·Mapping·Capability 실행, Context 계획·실행과 OPA 정책 연계
- [Ontology와 Binding](platform/ontology.md): 작성·검토·게시, Stable Concept와 immutable bundle
- [Metadata 관리](platform/metadata/asset_assessment.md): OpenMetadata 조회, AI 제안·검토·적용·복구
- [Admin UI](platform/admin_ui.md)와 [MCP](mcp/gateway.md): 관리·실행 기능의 사용자 진입점
- HTTP·DB native async 실행과 연결 상한: 계산·검증은 일반 함수로 유지하고
  승인·적용·checkpoint 순서와 취소 시 rollback을 보존한다. 로컬 Compose 반영과 실제
  실행은 [2026-10-16 검증](verification/async_deployment_collection_2026_10_16.md)에서 확인했다.

구현 파일·이관 이력은 각 프로젝트의 개발 안내와 Git 이력에서 확인한다.
실제 질문과 배포 환경의 검증 범위는 [검증 기록](verification/index.md)에 남긴다.

## 다음 결과

### 1. Context Engine vertical slice

현재 API·지원 질문·실행 제약은 [Context](platform/context.md)를 따른다.

승인된 Ontology, Binding과 Capability를 사용해 질문을 실행계획으로 변환한다.

완료 조건:

- 계획에 사용한 concept, capability, source와 artifact version을 설명한다.
- 접근권한과 시간 범위를 실행 전에 검증한다.
- 부분 실패와 불확실성을 결과에 보존한다.

현재 공고 검색과 계약금액 질문의 해석·집계는 공공조달 패키지에 분리되어 있다.
이 구조는 범용 자연어 planner의 완료를 뜻하지 않는다. 다른 실제 업무 Domain을
추가할 때 공통 Runner·Context Engine 수정 없이 handler를 연결할 수 있는지
검증하고, 그때 확인된 재사용만 공통 계약에 반영한다.

### 2. 검증된 Capability와 사용자 평가

대표 질문에 필요한 소수 Capability의 Ontology, OpenMetadata, Binding, Mapping과
provenance를 끝까지 완성하고 실제 사용자 평가로 가치를 검증한다. 검증되지 않은
Capability는 운영 준비 상태와 명확히 구분한다.

대표 질문의 종단 검증 결과와 당시 metadata 결손은
[Context vertical 검증 보고서](verification/vertical_slice_verification.md)와
[Bid notice vertical 검증 보고서](verification/bid_notice_vertical_verification.md)에
기록한다. 현재 준비도는 배포된 계약·실행 결과·근거의 최신 상태를 대조해 평가한다.

### 3. 필요한 Admin 관리 UX

Context vertical에서 반복적으로 확인된 병목만 기존 관리 surface에 추가한다.
Workspace를 별도 권위 lifecycle로 만들지 않고 Capability, Suggestion, Binding,
Ontology와 OpenMetadata의 권위 상태를 직접 보여준다. Authoring Workspace를 사용할
경우에도 이는 이 상태들을 조율하는 작업 단위일 뿐 release readiness나 승인 상태의
권위가 아니다. 범용 Mapping builder나 Source editor를 제품 가치 검증보다 먼저
만들지 않는다.

Suggestion 적용은 자동 승인이 아니다. 사람이 최소 변경 단위로 승인한 뒤 대상
version을 재검증하고, OpenMetadata 변경 또는 Teoria Draft 생성을 수행하며 결과를
`applied` 또는 `failed` 이력으로 남긴다. Ontology 변경은 게시가 아닌 Draft 생성까지만
자동화한다.
데이터 자산 상세의 수동 description 편집도 같은 Suggestion 경로를 사용한다. 제출자는
인증 principal로 남기고, 원천의 현재 값과 version을 근거로 고정해 승인 전 변경과의
충돌을 차단한다. owner·domain·classification·Glossary 편집 UI는 각 OpenMetadata
참조 선택과 제거 의미, stale evidence 계약을 갖춘 뒤 이 흐름으로 확장한다.

메타데이터 인텔리전스의 사용자 작업명은 `자산 진단`이다. 개발 단계에서는
Data Catalog에서 대상 FQN을 포함한 세 Skill 요청을 복사한다.

- 메타데이터 정비 (`metadata_enrichment`, `$enrich-metadata-asset`): 설명·Glossary 제안
- 업무 의미 연결 (`semantic_alignment`, `$align-metadata-semantics`): 기존 Published Concept Binding 제안
- 개방 적합성 진단 (`disclosure_assessment`, `$assess-data-disclosure`): 정보 유형·법령 근거·개방 상태·보호조치 검토 초안

정비와 의미 연결은 기존 Suggestion→Review→Application 경로를 사용한다.
새 분석 유형 ID는 설계 용어이며 저장된 Suggestion enum과 API를 변경하지 않는다.
신규 업무 Ontology 제안은 보류한다. 비동기 첫 구현은
`intelligence.asset_assessments`와 `metadata-assessment-worker`를 사용한다.
수동 시작·상태 조회·설명 및 기존 Concept 직접 Binding 제안 등록·법령 검토 findings를
제공한다. 모델 gateway 설정 후 실행할 수 있으며 실제 모델 품질 평가는 별도다.
법령 진단의 구조화된 Suggestion 계약·태그 적용기, 원천 문서 자동 검색,
자동 Glossary 연결·주기 진단·재분석·품질 지표는 후속 범위다.

### 4. Semantic MCP/SDK

Capability 목록을 그대로 노출하는 수준을 넘어 semantic discovery와 provenance를
안정된 client 계약으로 제공한다.

완료 조건:

- MCP와 SDK가 같은 Runtime API 계약을 사용한다.
- schema를 client 코드에 복제하지 않고 discovery로 협상한다.
- pagination, timeout, retry와 오류 의미가 문서화되고 회귀 테스트된다.

### 5. Production identity and scale

- Admin OIDC와 세분화된 role을 OPA principal 계약에 연결
- Runtime service identity, token rotation, quota와 영속 decision/execution audit
- Data/Control plane의 독립 backup·restore 검증
- Kubernetes workload와 secret 계약 완성
- suggestion 품질 평가셋과 승인 성과 측정
- 수집 처리량과 데이터 완전성을 분리한 운영 지표, 개찰 보강 잔량·부분완료·
  조회 실패 및 계약 미해결 구간의 복구. 현재 잔량은 날짜별 검증 기록으로 관리한다.

## 의도적으로 미루는 항목

Ontology canvas, 범용 graph editor, 자동 승인, OpenMetadata entity 복제, Airflow
추가, 다중 workflow engine은 위 vertical slice의 운영 가치가 검증되기 전에는
구축하지 않는다.

공공조달의 버전형 분야 분류체계는 별도 Domain 기능으로 구축한다. 그 전까지 물품과
공사는 원천 공식 분류번호·분류명의 단일 단계를 사용하고, 코드 접두어로 상위 계층을
추정하지 않는다. 수집원, 기간 유효 분류와 최신 체계 재분류의 완료 조건은
[공공조달 분야 분류 기준과 확장 계획](platform/domains/public_procurement/procurement_classification.md)을
따른다.

### 조달 규격 인텔리전스 서비스 설계 제안

[설계 초안](procurement_specification_intelligence/overview.md)은 첨부 규격서에서
품목별 요구조건을 추출해 검색·비교하는 조달 Domain 기능을 제안한다. 현재 첨부 처리
보류 정책을 해제하지 않으며 운영 제공 기능이나 확정된 개발 일정으로 간주하지 않는다.
초기 대상은 서버이며, 평가 corpus·원문 근거·다품목 배정과 검토된 스냅샷 검색을 먼저
검증한다. 두 번째 검증 품목은 아직 확정하지 않으며 제품 구성 평가는 후속 단계다.

[도메인 모델 검토안](procurement_specification_intelligence/domain_model.md)을 바탕으로
현재는 [구성품·세부 규격 연결](procurement_specification_intelligence/composition_analysis.md)을
검증한다. Codex가 저장된 파싱 결과에서 주요 구성·하위 대상·외부 참조를 구별하고
대표 규격을 연결한다. 네 개발 표본의 주요 목록 28개·대표 규격 27개를 검토했으며
전체 속성 추출·새 문서 정확도·자동 의미 검증은 미완료다.

예전 단계별 품목·구성요소·요구조건·통합·사전 구축 코드는 제거했다.
현재 독립 실행 경로는 분석 입력 준비 → Codex 제안 → 코드 검사 → 원문 재검토·목록 대조다.
원본·파싱·과거 결과는 보존하며 예전 속성 52개는 현재 사전으로 사용하지 않는다.
다음은 전체 요구조건 추출·귀속 확인 → 의미 정리 → 기존 승인 사전 대조 → 제안·승인·
버전 갱신이다. [초기 사전 구축](procurement_specification_intelligence/dictionary_building_pipeline.md)은
10건씩 100건을 점진 검토하는 목표다. 새 생성·최종 검토·수정·로컬 승인 CLI를 구현했으며
입력 10건 고정·해시·단위 차원·의미 범위·이전 지적사항·재검증을 확인한다.
[보존 서버 공고 10건으로 초기 구축](procurement_specification_intelligence/verification/server_dictionary_bootstrap_2026_10_20.md)을
실행해 원문 관찰 385개·정의 후보 152개를 만들고 수정·재검증했다.
미해결 문제 19개와 단일 공고 정의 107개의 추가 검토가 남아 미승인 상태다.
후속 [속성 단위 감사](procurement_specification_intelligence/attribute_registry.md#현재-초안의-과분리와-재검토)는
과분리·복합 정의·요구조건 혼입을 확인했다. 기존 152개와 보완안 189개를 표준 속성 수로
집계하지 않으며, 원문 관찰·값 해석·표준 정의·요구조건의 경계를 먼저 수정한다.
독립 의미 정확도 평가는 아직 수행하지 않았다.

각 단계의 상세 설계는 입력·대안·처리 순서·결과·실패·자원·버전·검증 기준을 문서로
정한 뒤 검토한다. 이전 메타데이터 식별기·평가 코드와 전용 테스트는 사용자 요청으로
삭제했다. [규격서 후보 식별 재설계](procurement_specification_intelligence/document_identification.md)는
컴퓨터서버(4321150102)를 첫 검증 품목으로 삼고 모든 물품에 적용할 처리 계약을
검토한다. 이후 사용자 요청으로 공통 확인 우선순위 함수를 구현했다. 기존 문서 5개와
추가 2개 공고의 전체 첨부 7개에서 kordoc 최소 파싱을 실행하고
[관측과 한계](procurement_specification_intelligence/computer_server_validation.md)를 기록했다.
메타데이터는 확인 우선순위를 정하고 실제 규격 포함·품목 귀속은 원문 검수 또는
파싱·문서 이해로 확인한다. 선별 평가는 kordoc을 고정하고 선정·미선정 첨부의 내용 검수로
규격서 선별의 정밀도·회수율·비용을 측정했다. 새 20개 공고를 개발·평가 10개씩
고정해 첨부 68개를 확인했고 공통 문서명 규칙 v2를 검증했다.
[첫 선별 평가](procurement_specification_intelligence/selection_evaluation_2026_10_20.md)에서
평가 집단의 공고 회수율 8/9·선정 파일 정밀도 10/11을 관측했으며 미확인과 작은 표본의
한계를 별도로 보고한다. 평가 표본을 재사용해 새 규칙의 독립 성능을 주장하지 않는다.
현재는 Precision 우선 v3 정책을 적용하고 선정 후보 8개·한계 확인 PDF 2개로
[OCR 제외 파서 비교](procurement_specification_intelligence/parser_evaluation_2026_10_20.md)를 수행했다.
6개 도구·추가 설정을 비교해 kordoc 기본 구조 출력과 형식별 원본 검사·근거 연결을
권장한다. [모듈 설계](procurement_specification_intelligence/document_parsing.md)의 공통 JSON은
최소 계약 초안이며 전체 문서 품질 승인·운영 연결은 후속 작업이다. 독립 실행과
중간 결과 재사용 원칙을 따르며 OCR은 사용하지 않는다.
[과거 평가 기록](procurement_specification_intelligence/evaluation_2026_10_20.md)은
삭제한 구현의 실험 기록으로만 보존하며 현재 성능이나 새 구현의 근거로 사용하지 않는다.

### 법령 기반 데이터 거버넌스

법령 근거 저장소는 Pipeline의 시행일별 원문 수집·구조화·재가공 기능을 사용한다.
다음 결과는 승인된 법령-정보 유형 매핑 규칙, 내부 처리와 외부 개방의 분리 평가,
법령 변경 영향 검토 및 Suggestion→Review→Application을 통한 OpenMetadata 반영이다.
업무 Ontology는 실제로 사용하는 보호대상 유형·처리 목적·개방 시나리오부터
정의하며 조문 원문이나 개별 평가 응답을 Business Object로 만들지 않는다.

현재 Admin 진단 기반은 OpenMetadata 저장 샘플·프로파일의 제한된 조회와 법령의
키워드 검색·snapshot 원문 조회를 제공한다. 기본 메타데이터 ingestion은 샘플과
프로파일을 자동 수집하지 않는다. 다음 검증 범위는 대상 테이블을 명시한 관측
수집 workflow, AI 의미 분석·근거 생성과 태그 제안 및 검색 평가다.
배포 호환성 결과는 [OpenMetadata 검증 기록](verification/openmetadata_upgrade_2026_10_13.md),
현재 제안 비교·적용 이력과 화면 사용법은 [Admin UI](platform/admin_ui.md)를 따른다.

조달 탐색의 고정 snapshot·과거 시점 재현·관계 확장과 성능 검증의 후속 범위는
[조달 탐색 연동 계약](integration/procurement_exploration_contract.md#후속-요구사항과-성능-평가)을 따른다.

EC2 1대의 K3s 배포와 GitHub CD 경로는 [배포 안내](deployment/k3s.md)에 구현되어 있다.
실제 EC2 연결·배포 검증은 서버·도메인·Secret 설정 후 수행한다.
