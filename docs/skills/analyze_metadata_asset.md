# Metadata Asset 분석 Skill

`analyze-metadata-asset`는 OpenMetadata의 테이블·컬럼을 Teoria Business
Ontology, Semantic Binding, Source Registry와 원문 문서에 대조하여 검토 가능한
메타데이터 제안을 만드는 개발용 Codex Skill이다.

이 Skill이 만드는 결과는 권위 메타데이터가 아니라 `pending` Suggestion이다.
Codex는 제안을 승인하거나 OpenMetadata 및 Published Ontology를 직접 변경하지
않는다. 적용 여부는 사람이 Admin UI의 Review Queue에서 결정한다.

## 언제 사용하는가

- 신규 DB 테이블이나 View가 OpenMetadata에 수집된 뒤 의미를 보강할 때
- 비어 있거나 부정확한 테이블·컬럼 Description을 검토할 때
- Glossary Term 생성·할당 후보를 찾을 때
- 기존 Ontology concept와 컬럼의 Semantic Binding 후보를 검토할 때
- 근거가 부족한 메타데이터와 품질 테스트 공백을 식별할 때

컬럼 이름이 비슷하다는 이유만으로 의미를 확정하는 용도가 아니다. Source Registry,
Ontology, 기존 Binding, 제공기관 원문과 사용자가 지정한 문서가 우선 근거다.

## 기본 사용법

저장소 루트에서 Codex에게 Skill 이름, OpenMetadata 테이블 FQN과 분석 범위를
지정한다.

```text
$analyze-metadata-asset
OpenMetadata 테이블
teoria_postgresql.teoria_data.public_procurement.runtime_contracts를 분석해줘.
컬럼 description, glossary term 할당, ontology binding과 quality test 공백을
검토하되 우선 제안만 보여주고 Review Queue에는 올리지 마.
```

제안을 확인한 뒤 Review Queue 등록까지 원하면 명시적으로 요청한다.

```text
$analyze-metadata-asset
runtime_contracts의 contract_amount, contract_date, procuring_organization_code를
분석하고 근거와 confidence를 보여준 다음, 유효한 제안을 Review Queue에 올려줘.
승인하거나 적용하지는 마.
```

원문이나 설계 문서가 있으면 함께 지정한다.

```text
$analyze-metadata-asset
OpenMetadata의 <table FQN>을 분석해줘.
의미 근거로 pipelines/references/providers/<provider>/<source>/와
docs/<document>.md를 함께 사용하고, 문서로 증명되지 않는 내용은 inference로
표시해줘.
```

테이블 FQN은 필수다. 테이블 이름이나 서비스가 불명확하면 Skill은 임의로
선택하지 않고 사용자에게 FQN을 요청한다.

## 실행 절차

1. Teoria Admin API를 통해 현재 OpenMetadata 테이블, 컬럼, 버전을 읽는다.
2. 관련 Ontology concept, 기존 Binding, 활성 Source Registry와 지정된 원문만
   선별해 대조한다.
3. 독립적으로 승인 가능한 변경 하나당 Suggestion 하나를 만든다.
4. 각 제안에 근거, confidence, 위험도, 경고와 OpenMetadata 관찰 버전을 넣는다.
5. 로컬 proposal bundle을 검증한다.
6. 사용자가 요청한 경우에만 Review Queue에 `pending` 상태로 제출한다.
7. 사람이 Admin UI에서 현재 값과 제안 값을 비교하여 승인·반려한다.
8. 승인된 유형만 application service가 OpenMetadata 또는 Ontology Draft에
   반영하고 결과를 다시 기록한다.

기본 의미 경로는 다음과 같다.

```text
Physical Asset
  -> OpenMetadata Glossary Term
  -> Teoria Ontology Stable Concept ID
```

Direct Data Asset Binding도 가능하지만 Glossary Term 경로보다 우선하지 않는다.
Runtime Mapping과 Semantic Binding은 별개의 산출물이다.

## 로컬 명령

분석 컨텍스트만 가져오는 작업은 읽기 전용이다.

```bash
python3 .agents/skills/analyze-metadata-asset/scripts/fetch_context.py \
  --table-fqn '<service.database.schema.table>' \
  --output /tmp/teoria_metadata_context.json
```

작성한 bundle은 제출 전에 검증한다.

```bash
python3 .agents/skills/analyze-metadata-asset/scripts/submit_proposals.py \
  proposal_bundle.json
```

Review Queue 등록은 사용자가 요청한 경우에만 실행한다.

```bash
python3 .agents/skills/analyze-metadata-asset/scripts/submit_proposals.py \
  proposal_bundle.json --submit
```

Bearer 인증을 사용하는 환경에서는 `TEORIA_ADMIN_API_TOKEN`을 환경변수로
제공한다. 토큰을 프롬프트, bundle, 로그에 넣지 않는다. Admin API가 기본
`http://localhost:8001`이 아니면 `--admin-base-url`을 지정한다.

## 제안과 승인 결과

| 제안 유형 | 승인 후 동작 |
|---|---|
| `description` | OpenMetadata 테이블·컬럼 Description 갱신 |
| `glossary_term` | OpenMetadata Glossary Term 생성 |
| `glossary_term_assignment` | OpenMetadata 컬럼에 Term 할당 |
| `binding` | Teoria Semantic Binding Draft 생성·승인 기록 |
| `ontology_change` | Published version을 수정하지 않고 새 Ontology Draft 변경 생성 |
| `test_suite`, `quality_test` | OpenMetadata 품질 Suite·Test 생성 |

컬럼 Description 제안에는 `table_id`, `column_name`, `column_fqn`,
`source_version`, `source_description`이 포함된다. 승인 시 대상 컬럼의 현재 값을
다시 확인한다. 같은 분석 묶음의 다른 컬럼이 먼저 적용되어 테이블 버전만 바뀐
경우에는 계속 적용할 수 있지만, 대상 컬럼 자체가 변경됐으면 `stale_evidence`
충돌로 중단하고 재분석해야 한다.

## 사람이 확인할 사항

- 제안 문장이 실제 업무 의미를 설명하며 물리 컬럼명을 단순 번역한 것이 아닌가
- Source Registry 또는 원문이 해당 필드의 의미를 실제로 증명하는가
- Ontology 연결 대상이 Published Stable Concept ID인가
- 기존 Glossary Term이나 Binding을 중복 생성하지 않는가
- confidence가 근거의 강도와 맞는가
- API field binding이라면 활성 Source Operation에서 원본 필드가 검증됐는가

Review Queue 제출은 적용이 아니다. 승인과 application 성공이 모두 끝난 뒤에만
OpenMetadata 또는 Teoria authoring state의 변경으로 간주한다.

Skill의 실행 계약은
[SKILL.md](../../.agents/skills/analyze-metadata-asset/SKILL.md), proposal 형식은
`references/proposal_bundle.schema.json`에서 확인할 수 있다.
