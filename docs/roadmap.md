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
- OpenMetadata integration과 Admin UI
- Runtime API만 호출하는 MCP gateway

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

### 2. Semantic MCP/SDK

Capability 목록을 그대로 노출하는 수준을 넘어 semantic discovery와 provenance를
안정된 client 계약으로 제공한다.

완료 조건:

- MCP와 SDK가 같은 Runtime API 계약을 사용한다.
- schema를 client 코드에 복제하지 않고 discovery로 협상한다.
- pagination, timeout, retry와 오류 의미가 문서화되고 회귀 테스트된다.

### 3. Production identity and scale

- Admin OIDC와 세분화된 role
- Runtime service identity, token rotation, quota와 audit
- Data/Control plane의 독립 backup·restore 검증
- Kubernetes workload와 secret 계약 완성
- suggestion 품질 평가셋과 승인 성과 측정

## 의도적으로 미루는 항목

Ontology canvas, 범용 graph editor, 자동 승인, OpenMetadata entity 복제, Airflow
추가, 다중 workflow engine은 위 vertical slice의 운영 가치가 검증되기 전에는
구축하지 않는다.
