# Legacy Runtime Registry migration

기존 YAML Registry는 현재 Runtime의 운영 계약이다. Business Ontology v2가
생겼다는 이유로 삭제하거나 자동 변환하지 않는다.

## 분류

`platform/ontology-migrations/ontology-v2.yaml`은 기존 44개 Object를 모두
다음 중 하나로 분류한다.

| 분류 | 의미 | 처리 |
|---|---|---|
| `BUSINESS_CONCEPT` | 지속 가능한 업무 의미 | Ontology v2 Stable Concept으로 승격 |
| `RUNTIME_PROJECTION` | Capability 전용 입출력 구조 | Runtime Contract로 유지 |
| `ASSESSMENT_RESULT` | 판단·관찰·근거 결과 | 결과 모델로 유지하고 Ontology와 연결 |
| `DEPRECATED` | 더 이상 사용하지 않는 계약 | 참조 제거 후 폐기 |

현재 분류 결과:

- Business Concept: 23
- Runtime Projection: 12
- Assessment Result: 9
- 즉시 Deprecated: 0

2026-10-05 기준 23개 Business Concept 전체가 Ontology v2 Stable Concept에
매핑됐다. 기존 5개 Organization, Company, BidNotice, Award, Contract에 더해
`company` 0.1.0의 9개 객체와 `procurement` 0.4.0의 9개 객체를 Authoring
Lifecycle로 게시했다.

업무 의미를 DB schema migration에 하드코딩하지 않는다. 아래 검토 가능한
manifest와 authoring 명령을 사용한다.

```bash
teoria promote-business-concepts \
  --manifest platform/ontology-migrations/business-concepts-v1.yaml \
  --publish

teoria bind-capabilities \
  --manifest platform/ontology-migrations/capability-bindings-v1.yaml \
  --approve
```

Capability 바인딩은 현재 Registry release에 실제로 존재하는 Capability,
input, output만 허용한다. 최초 8개 승인 바인딩은 회사 기본정보, 계약 조회,
공고 조회의 정확히 일치하는 계약만 포함한다.

초기 identity-only 승격 이후 `business-ontology-enrichment-v1.yaml`을 통해
업무 속성 23개와 관계 14개를 추가했고, `company` 0.2.0과 `procurement`
0.5.0으로 게시했다. 이 enrichment 역시 schema migration이 아니라 검토 가능한
Ontology authoring content다.

## 검증

```bash
uv run --locked --package teoria-platform teoria ontology-migration-report \
  --manifest platform/ontology-migrations/ontology-v2.yaml
```

검증기는 다음을 확인한다.

- 기존 Registry Object 44개의 완전한 분류
- 존재하지 않는 legacy object 참조
- mapped target Stable Concept 존재 여부
- Capability와 Runtime Mapping의 Object 사용 건수

Application DB 연결이 설정되면 `target_stable_key`도 실제 Published/active
Concept 집합과 대조한다.

## 전환 원칙

1. Capability와 Mapping은 전환 완료 전까지 그대로 실행한다.
2. Business Concept만 Ontology v2로 옮긴다.
3. Capability response projection을 Business Object로 재생성하지 않는다.
4. Runtime Mapping은 Source record 변환 계약으로 유지한다.
5. Capability input/output은 별도 Semantic Binding으로 Stable Concept에 연결한다.
6. Published Artifact와 기존 Registry의 parity를 확인한 뒤 Runtime을 전환한다.
7. 참조가 0이 된 legacy Object만 deprecated한다.

Admin UI의 `Runtime Registry`는 기존 YAML Runtime 계약을 보여주고,
`Bindings`는 새 Business Ontology Stable Concept을 사용한다.
