# Teoria product roadmap

로드맵은 완료된 migration 일지가 아니라 남은 제품 결과와 완료 조건만 관리한다.
현재 구현 사실은 코드, Registry와 [Architecture](architecture/overview.md)가 기준이다.

## 현재 기반

- 프로젝트와 저장소 권위 경계
- Source·Mapping·Capability Runtime과 HTTP API
- Registry 업무 Domain 소유권과 Runtime 계약 namespace를 분리한 계약 배치
- 업무 Domain·Runtime 계약을 구분한 Admin 집계와 표시명
- Ontology 게시 트랜잭션·단일 Published version 제약 및 Application DB 동시성 검증
- 공공조달 참여 분석의 한국시간 개찰 연도·차수별 집계, 수집 상태와 상위 10위 보존 범위
- Suggestion 적용 실행권·이력·성공 기록과 외부 쓰기 없는 결과 복구
- 분석 Reader 기능별 분리와 프로필·참여 Data DB 행 타입 검증
- Connector·Prefect 수집 및 Data DB
- 개찰 응답 완전성 검증과 상위 10위·낙찰자 저장 업체 집합의 완료 판정
- 수집 기능별 Flow·Task·client·정규화 패키지와 실행 관리 분리,
  참가자격 추출의 모델 실행·근거 검증·의미 보정 분리
- Ontology version lifecycle과 Registry·Published Ontology·Approved Binding을
  함께 고정하는 checksum 기반 Runtime bundle
- Semantic Binding review 기록과 Metadata Intelligence suggestion
- 승인된 Metadata Intelligence suggestion을 유형별 적용기로 실행하는 변경 경로
  (OpenMetadata description·Glossary·quality test, Binding Draft, Ontology Draft)
- OpenMetadata integration과 Admin UI
- Data Assets의 기술·적재 운영·업무 Binding·거버넌스 통합 조회,
  명시적 Pipeline output 연결과 원천별 장애 상태
- 작업 중심 Admin 메뉴·개요, URL 기반 자산 상세와 관점별 탭, 전체 자산 검색,
  자산별 제안·직접/용어 기반 의미 연결 조회, 공통 관리자 인증과 원천별 오류 격리
- Runtime API만 호출하는 MCP gateway
- Domain별 processor 등록과 query 후처리, 공공조달 query handler를 분리한
  Runtime·Context orchestration
- 공공조달 시장 분석의 기능별 하위 폴더와 참가자격 실행·근거·캐시·결과 분리,
  Domain의 조달 데이터·참가자격 검증,
  Admin 서비스 조립과 기능별 Router 분리
- Context `plan`·`execute` 분리와 OPA 정책 결정점의 첫 vertical 계약
- 서명·versioned OPA Bundle 배포, readiness, decision/status audit 수집
- Capability input Binding의 Ontology–Runtime type·collection 호환성 검사

Runtime bundle은 독립 version 디렉터리로 compile한 뒤 atomic active pointer로
활성화한다. 실행 응답에는 Registry release와 bundle checksum이 함께 기록되며,
rollback은 검증된 이전 bundle을 다시 활성화하는 방식이다.

## 다음 결과

### 1. Context Engine vertical slice

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

현재 대표 질문의 종단 검증 결과와 남은 metadata 결손은
[Context vertical 검증 보고서](vertical_slice_verification.md)와
[Bid notice vertical 검증 보고서](bid_notice_vertical_verification.md),
[기업-공고 참가 가능성 검증 보고서](company_bid_eligibility_vertical_verification.md)에
기록한다. 참가 가능성 vertical은 Runtime 종단 실행까지 성공했으며, 현재 남은
핵심 결손은 전자입찰 등록과 기관별 명부 요건을 판정할 authoritative evidence다.

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

개발 단계 Metadata Agent는 Data Catalog에서 대상 FQN이 포함된 Codex Skill 요청을
만들고 Review Queue에 pending Suggestion을 제출하는 흐름을 사용한다. 운영형 비동기
Agent runner, 분석 실행 묶음, 재분석과 품질 지표는 별도 제품 결과로 남아 있다.

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

## 의도적으로 미루는 항목

Ontology canvas, 범용 graph editor, 자동 승인, OpenMetadata entity 복제, Airflow
추가, 다중 workflow engine은 위 vertical slice의 운영 가치가 검증되기 전에는
구축하지 않는다.

공공조달의 버전형 분야 분류체계는 별도 Domain 기능으로 구축한다. 그 전까지 물품과
공사는 원천 공식 분류번호·분류명의 단일 단계를 사용하고, 코드 접두어로 상위 계층을
추정하지 않는다. 수집원, 기간 유효 분류와 최신 체계 재분류의 완료 조건은
[공공조달 분야 분류 기준과 확장 계획](domains/public_procurement/procurement_classification.md)을
따른다.

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
OpenMetadata 2.0.5의 격리 DB 복원·migration·연계·ingestion 및 기존 버전 복구
검증과 운영 전환 후 API·검색·Prefect ingestion 재검증을 완료했다.
