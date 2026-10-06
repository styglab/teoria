# Legacy Runtime Registry migration

기존 YAML Registry는 현재 Runtime의 운영 계약이다. Business Ontology v2가
생겼다는 이유로 삭제하거나 자동 변환하지 않는다. 기본 파일명과 Python 타입은
각각 `runtime_contract.yaml`, `RuntimeContractDefinition`으로 전환했다. 이전
`ontology.yaml`/`ontology:` 문서와 `OntologyDefinition` import는 Registry
`2026.10.06.2`에서 한 버전 동안 호환한 뒤 `2026.10.06.3`에서 제거했다.

```text
Source → Runtime Mapping → Runtime Contract → Capability
                              ↕
                       Semantic Binding
                              ↕
                 Published Business Ontology
```

Published Business Ontology Artifact는 Runtime Contract를 대체하지 않는다.
전자는 지속 가능한 업무 의미의 스냅샷이고 후자는 API/DB 실행 결과를 검증하는
wire/runtime schema다.

## 분류

`platform/ontology-migrations/ontology-v2.yaml`은 현재 실행 중인 41개 Object를 모두
다음 중 하나로 분류한다.

| 분류 | 의미 | 처리 |
|---|---|---|
| `BUSINESS_CONCEPT` | 지속 가능한 업무 의미 | Ontology v2 Stable Concept으로 승격 |
| `RUNTIME_PROJECTION` | Capability 전용 입출력 구조 | Runtime Contract로 유지 |
| `ASSESSMENT_RESULT` | 판단·관찰·근거 결과 | 결과 모델로 유지하고 Ontology와 연결 |
| `DEPRECATED` | 더 이상 사용하지 않는 계약 | 참조 제거 후 폐기 |

현재 분류 결과:

- Business Concept: 23
- Runtime Projection: 9
- Assessment Result: 9
- 제거 완료: 3

2026-10-06에 참조가 사라진 구형 Capability 3개와 각 Capability만 사용하던
Runtime Projection을 함께 제거했다.

| 제거 Capability | 제거 Projection | 대체 경로 |
|---|---|---|
| `find_similar_bid_notices` | `similar_bid_notice` | `get_company_similar_project_experience`, `search_bid_related_projects` |
| `find_bid_relevant_companies` | `bid_relevant_company` | `get_bid_notice_relationship_context`, `get_company_similar_project_experience` |
| `analyze_bid_organization_field_companies` | `bid_organization_field_company` | 기관 프로필, 기관×업체 관계, 공고 관계 Context |

제거된 ID는 discovery에서 숨기는 수준이 아니라 Registry와 Runtime dispatch에서
삭제됐으며 호출하면 `404 unknown_capability`를 반환한다.

2026-10-06 기준 23개 Business Concept 전체의 통합 목적지를
`ontology-unification-v1.yaml`에 명시했다. 목적지는 분리돼 있던 기존
`company`/`procurement` 온톨로지가 아니라 단일 `teoria` Business Ontology다.
단순 1:1 이름 변경만 하지 않고 다음 전환을 구분한다.

- `map`: 의미가 동일한 Stable Concept으로 이동
- `merge`: 중복되던 개념을 더 일반적인 하나의 개념으로 통합
- `rename`: 의미는 유지하고 새 명명 체계로 이동
- `generalize`: 원천별 개념을 source-neutral한 업무 개념으로 일반화

누락 방지를 위해 검증기는 기존 `BUSINESS_CONCEPT` 23개, 전환 계획 23개,
통합 Draft의 실제 target Stable Concept을 함께 대조한다. 현재 결과는
23/23이며 누락·알 수 없는 항목·존재하지 않는 target이 모두 0이다.

2026-10-06 전환 결과 `teoria` 0.1.1이 Published 상태이며 기존
`company` 0.2.0과 `procurement` 0.5.0은 deprecated 상태다. 기존 Ontology에
연결됐던 Approved Binding 13개는 동일 target을 가진 통합 Ontology Binding이
승인된 것을 확인한 뒤 deprecated 처리했다. 현재 통합 Ontology에는 Capability
Binding 11개와 OpenMetadata Binding 11개, 총 22개의 Approved Binding이 있다.

Stable Key가 우연히 같은 여러 Published Ontology가 존재하는 전환 구간에도
임의의 Concept을 선택하지 않도록 Capability Binding manifest는
`ontology_namespace`를 명시한다. namespace 없이 조회한 결과가 둘 이상이면
Binding 생성은 실패한다.

통합 Draft에는 핵심 조달 모델 외에 기존 업무 의미를 보존하는 다음 개념도
포함한다.

- 주소, 상장
- 입찰 참가요건 집합과 개별 요건
- 공식 업종, 사업자별 등록 업종
- 공식 공급품, 사업자별 등록 공급품
- 기간성 조달 제재

반대로 Runtime Projection 9개와 Assessment Result 9개는 Business Ontology로
옮기지 않는다. 전자는 Capability wire/runtime contract이고 후자는 관찰·판정
결과이므로, 새 Business Object로 복제하면 같은 혼합 문제가 반복된다.

업무 의미를 DB schema migration에 하드코딩하지 않는다. 아래 검토 가능한
manifest와 authoring 명령을 사용한다.

```bash
teoria promote-business-concepts \
  --manifest platform/ontology-migrations/business-concepts-v1.yaml \
  --publish

teoria bind-capabilities \
  --manifest platform/ontology-migrations/capability-bindings-v1.yaml \
  --approve

teoria apply-ontology-extension \
  --manifest platform/ontology-migrations/teoria-legacy-concepts-v1.yaml
```

Capability 바인딩은 현재 Registry release에 실제로 존재하는 Capability,
input, output만 허용한다. 현재 9개 승인 바인딩은 회사 기본정보, 계약 단건·검색,
공고 조회의 정확히 일치하는 계약만 포함한다.

초기 identity-only 승격 이후 `business-ontology-enrichment-v1.yaml`을 통해
업무 속성 23개와 관계 14개를 추가했고, `company` 0.2.0과 `procurement`
0.5.0으로 게시했다. 이 enrichment 역시 schema migration이 아니라 검토 가능한
Ontology authoring content다.

## 호환 API 전환

Admin의 기본 조회 경로는 다음과 같다.

- `GET /v1/admin/runtime-contracts`
- `GET /v1/admin/runtime-contracts/{id}/graph`

기존 `/v1/admin/ontologies` 경로는 2026-10-06 정리에서 제거했다. Business Ontology 작성 API는 계속
`/v1/admin/ontology-authoring` 아래에 있어 두 모델을 혼동하지 않는다.

Migration report는 Application DB가 연결된 경우 각 `BUSINESS_CONCEPT`의
`target_stable_key`가 단순 concepts 테이블에 존재하는지만 보지 않고, 현재
Published version의 immutable Runtime Artifact에 실제로 포함됐는지 검증한다.
보고서의 `runtime_contract_required=true`는 해당 실행 스키마가 Mapping 또는
Capability에서 여전히 필요하다는 뜻이지 Business Ontology 승격이 실패했다는 뜻이 아니다.

## 검증

```bash
uv run --locked --package teoria-platform teoria ontology-migration-report \
  --manifest platform/ontology-migrations/ontology-v2.yaml
```

검증기는 다음을 확인한다.

- 현재 Runtime Registry Object 41개의 완전한 분류
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
6. Published Artifact와 Runtime Contract의 semantic target 정합성을 검증한다.
7. Runtime은 의미 조회에는 Published Artifact를, 실행 검증에는 Runtime Contract를 사용한다.
8. Capability와 Mapping 참조가 0이 된 Runtime Contract만 deprecated한다.
9. 기존 Published 온톨로지는 통합 Draft가 검증·게시되고 Binding 전환이 끝난
   뒤에만 deprecated한다.

Admin UI의 `Runtime Registry`는 기존 YAML Runtime 계약을 보여주고,
`Bindings`는 새 Business Ontology Stable Concept을 사용한다.

## 제거된 명칭 호환 계층

| 기본 명칭 | 제거된 호환 명칭 | 제거 릴리스 |
|---|---|---|
| `RuntimeContractDefinition` | `OntologyDefinition` | `2026.10.06.3` |
| `RuntimeContractRegistry` | `OntologyRegistry` | `2026.10.06.3` |
| `catalog.runtime_contracts` | `catalog.ontologies` | `2026.10.06.3` |
| `catalog.runtime_contract_paths` | `catalog.ontology_paths` | `2026.10.06.3` |
| `runtime_contract.yaml` / `runtime_contract:` | `ontology.yaml` / `ontology:` | `2026.10.06.3` |

Mapping 문서의 `mapping.ontology`와 Runtime node payload의 `ontology`는 별도
wire-contract 마이그레이션 대상이다. 이 단계에서는 외부 Capability 응답을
변경하지 않기 위해 그대로 유지한다.
