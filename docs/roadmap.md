# Teoria product roadmap

이 문서는 Teoria의 구현 순서와 각 단계의 완료 조건을 정의한다. 기능 수를
늘리는 것보다 하나의 검증 가능한 AI-Native loop를 먼저 완성한다.

## 제품 목표

```text
OpenMetadata asset
  → deterministic candidate retrieval
  → governed AI suggestion with evidence
  → human review
  → Binding draft
  → Binding approval
  → Context resolution
  → API / MCP / Agent
```

첫 reference slice는 OpenMetadata Column
`public_procurement.contracts.current_contract_amount`와 Stable Concept
`procurement.Contract.amount`다.

## 현재 상태

| 영역 | 상태 | 비고 |
|---|---|---|
| Prefect/Data Operations | 운영 중 | 수집, backfill, normalization, checkpoint |
| OpenMetadata Foundation | 구현 | PostgreSQL ingestion과 REST gateway |
| Business Ontology v2 | 구현 | 23개 legacy Business Concept 매핑, company 0.1.0 / procurement 0.4.0 게시 |
| Ontology Authoring API | 구현 | validation, diff, audit, publish artifact |
| Semantic Binding | 구현 | Stable Concept 중심 |
| Binding Governance/UI | 구현 | draft, approve, reject, deprecate |
| Capability Runtime | 운영 중 | Registry 기반 실행, 검증된 Capability target 8개 연결 |
| Ontology Authoring UI | 최소 UI 구현 | 버전 조회, Draft 생성, submit/approve/publish |
| Metadata Intelligence | 첫 vertical slice 구현 | Column 후보 생성, evidence/version 검증, 승인 시 Binding Draft |
| Runtime Artifact consumption | 전환 필요 | artifact 생성은 구현됨 |
| Context Engine | 미구현 | Contract.amount로 시작 |
| Semantic MCP | 미구현 | Context Engine 이후 |
| OIDC | 운영 전 필요 | 현재 Bearer/role 경계 사용 |

## Milestone 1 — Minimal Ontology Authoring UI

상태: **첫 운영 가능 버전 구현**. 고급 Object/Property 편집기와 semantic
diff 시각화는 다음 반복에서 보강한다.

목표는 Ontology Studio가 아니라 AI가 만든 Ontology Suggestion을 사람이
검토할 수 있는 최소 authoring surface다.

범위:

- version history와 Published 상태
- Published에서 Draft 생성
- Object, Property, Relationship의 기본 편집
- validation, semantic diff, Binding impact
- submit, approve, publish
- audit history

Rule/Metric 고급 편집기, 시각적 graph authoring, 협업 댓글은 후순위다.

완료 조건:

- UI에서 Published revision을 직접 수정할 수 없다.
- Draft 변경과 diff가 Stable Concept 기준으로 표시된다.
- validation 또는 Binding compatibility 실패 시 publish가 차단된다.
- 게시 결과의 artifact checksum을 확인할 수 있다.

## Milestone 2 — Binding Intelligence vertical slice

상태: **deterministic vertical slice 구현**.

- Metadata 화면에서 OpenMetadata Table/Column을 열어 후보 생성을 요청한다.
- 이름·설명 token, datatype, Glossary evidence로 Published Property 후보를 정렬한다.
- Suggestion에는 OpenMetadata source version과 대안 후보를 저장한다.
- 승인 직전 source version을 다시 확인하며 변경됐으면 `STALE_EVIDENCE`로 차단한다.
- 승인 결과는 확정 Binding이 아니라 별도 검토가 필요한 Binding Draft다.

### Candidate retrieval

초기에는 별도 Vector DB나 Graph DB를 도입하지 않는다.

1. Glossary exact/synonym match
2. normalized column/property name
3. description token similarity
4. datatype와 unit compatibility
5. parent table/object context
6. PK/FK와 relationship context
7. 필요하면 PostgreSQL `pg_trgm`

Top 5~10 후보만 LLM에 전달한다. LLM은 전체 Ontology 검색이 아니라 후보의
재정렬과 설명 생성을 담당한다.

현재 구현은 결정론적 후보 검색까지만 사용한다. LLM reranking은 평가셋과
provider 정책이 준비된 뒤 추가한다.

### Suggestion contract

```json
{
  "suggestion_type": "binding",
  "source": {
    "system": "openmetadata",
    "entity_id": "...",
    "entity_version": "1.4",
    "fqn": "teoria_postgresql.teoria_data.public_procurement.contracts.current_contract_amount"
  },
  "candidate": {
    "ontology_concept_id": "...",
    "stable_key": "procurement.Contract.amount",
    "ontology_version": "0.3.0"
  },
  "confidence": 0.97,
  "evidence": [
    {"type": "glossary_exact_match", "score": 1.0},
    {"type": "name_similarity", "score": 0.93},
    {"type": "datatype_compatibility", "score": 1.0},
    {"type": "table_context", "score": 0.91}
  ],
  "policy_version": "binding-suggestion-v1"
}
```

승인 결과는 Approved Binding이 아니라 Binding Draft다. Binding reviewer가
다시 의미 연결을 승인한다. 원천 entity version 또는 Ontology version이
변경되면 `stale_evidence`로 전환하고 재평가한다.

완료 조건:

- reference column에서 `Contract.amount`가 설명 가능한 후보로 생성된다.
- evidence, provenance, model/prompt/policy version이 보존된다.
- 중복되거나 충돌하는 Approved Binding을 생성하지 않는다.
- 승인 전에는 authoritative state를 변경하지 않는다.

## Milestone 3 — Suggestion framework generalization

| 종류 | 적용 대상 | 승인 결과 |
|---|---|---|
| Metadata Suggestion | Description, Tag, Glossary, Domain, Owner 후보 | OpenMetadata REST write-back |
| Binding Suggestion | Term/Asset/API/Capability ↔ Concept | Teoria Binding Draft |
| Ontology Suggestion | Object, Property, Relationship, Rule, Metric | Teoria Ontology Draft |

공통 필드:

- target and candidate references
- confidence and scored evidence
- source/ontology/capability contract versions
- provenance, model, prompt, policy version
- risk level, status, reviewer, review timestamps
- stale evidence state and re-evaluation history

## Milestone 4 — Published Artifact Runtime

- Published Artifact loader와 checksum 검증
- 마지막 정상 Artifact fallback
- 기존 Registry와 parity report
- shadow mode에서 결과 비교
- Runtime의 단계적 artifact 전환

기존 Registry를 바로 제거하지 않는다. Context Engine을 시작하기 전까지
동일한 Concept/Relationship 결과가 나오는지 검증한다.

## Milestone 5 — Context Engine vertical slice

입력 `계약금액`을 다음 Context Package로 해석한다.

- Stable Concept `Contract.amount`
- OpenMetadata Glossary Term과 Column
- description, quality, lineage, freshness
- 승인된 Capability와 API field binding
- evidence와 provenance

Context Engine은 OpenMetadata JSON이나 전체 Ontology를 Agent에게 그대로
전달하지 않는다. 요청에 필요한 최소 context만 조합한다.

## Milestone 6 — Semantic MCP / SDK

첫 MCP 도구:

- `resolve_business_term`
- `get_business_object`
- `resolve_binding`
- `resolve_capability`
- `build_context`

OpenMetadata MCP가 asset exploration을 담당하고 Teoria MCP는 Business
Ontology, Binding, Capability와 Context resolution을 담당한다.

## Milestone 7 — Production identity and scale

- OIDC/SSO와 organization role mapping
- service account와 human principal 분리
- approval separation-of-duties
- suggestion generation batch를 Prefect로 orchestration
- performance, retention, audit export, disaster recovery

## 의도적으로 미루는 항목

- 별도 Vector DB
- Neo4j 또는 다른 Graph DB
- OpenMetadata UI 복제
- Business Ontology의 OpenMetadata Custom Property 저장
- 과도한 microservice 분리
- 자동 승인되는 중·고위험 AI 변경
