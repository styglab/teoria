# Teoria product roadmap

로드맵은 완료된 migration 일지가 아니라 남은 제품 결과와 완료 조건만 관리한다.
현재 구현 사실은 코드, Registry와 [Architecture](architecture/overview.md)가 기준이다.

## 현재 기반

- 프로젝트와 저장소 권위 경계
- Source·Mapping·Capability Runtime과 HTTP API
- Connector·Prefect 수집 및 Data DB
- Ontology version lifecycle과 Registry·Published Ontology·Approved Binding을
  함께 고정하는 checksum 기반 Runtime bundle
- Semantic Binding review 기록과 Metadata Intelligence suggestion
- 승인된 Metadata Intelligence suggestion을 유형별 적용기로 실행하는 변경 경로
  (OpenMetadata description·Glossary·quality test, Binding Draft, Ontology Draft)
- OpenMetadata integration과 Admin UI
- Runtime API만 호출하는 MCP gateway
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
