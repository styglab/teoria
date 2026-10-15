# 자산 진단 Skills

메타데이터 인텔리전스는 OpenMetadata 자산을 대상으로 세 작업을 제공한다.
Skill은 Admin UI의 개발용 요청을 복사해 Codex에서 실행한다. 모델 gateway를 설정한
[자동 자산 진단 Worker](../architecture/asset_assessment.md)는 별도 실행 경로이며,
첫 버전은 설명·직접 Binding 제안과 법령 검토 findings를 지원한다.

| 사용자 기능 | Skill | 현재 결과 |
|---|---|---|
| 메타데이터 정비 | `$enrich-metadata-asset` | 테이블·컬럼 설명, Glossary 생성·할당 제안 |
| 업무 의미 연결 | `$align-metadata-semantics` | 기존 Published Ontology Concept와 Binding 제안 |
| 개방 적합성 진단 | `$assess-data-disclosure` | 정보 유형·법령 근거·개방 상태·보호조치 검토 초안 |

신규 업무 Ontology 제안은 보류한다. 대응하는 Concept가 없으면 연결 공백을
보고한다. 기존 API의 `description`, `glossary_term`, `glossary_term_assignment`,
`binding` 유형은 유지한다. 기존 품질·Ontology 적용기도 유지하지만 세 Skill의
생성 범위에 포함하지 않는다.

## 사용

자산 상세의 `자산 진단`에서 항목별 요청을 복사하거나 FQN을 지정한다.

```text
$enrich-metadata-asset
OpenMetadata 테이블 teoria_postgresql.teoria_data.public_procurement.runtime_contracts의
설명과 Glossary를 검토해줘. 근거와 confidence를 보여주고 제안만 작성해줘.
```

```text
$align-metadata-semantics
OpenMetadata 테이블 teoria_postgresql.teoria_data.public_procurement.runtime_contracts를
기존 Published Concept와 대조하고 유효한 Binding 제안을 Review Queue에 올려줘.
신규 Ontology는 만들지 말고, 승인하거나 적용하지 마.
```

```text
$assess-data-disclosure
OpenMetadata 테이블 <table FQN>을 일반 공개하는 상황으로 검토해줘.
평가 기준일을 명시하고 수집된 법령의 조문·버전을 근거로 정보 유형,
내부 처리 검토 상태, 외부 개방 권고, 태그 후보와 보호조치를 보여줘.
개인정보 원본 샘플은 사용하지 말고 태그를 적용하지 마.
```

개방 진단은 현재 보고서까지만 지원한다. 법령·태그 Suggestion 유형과 적용기가
추가되기 전까지 지원하지 않는 유형을 제출하거나 설명 변경으로 우회하지 않는다.
법령 검색은 키워드 방식이며 검색 결과를 적법성 확정으로 사용하지 않는다.
법령 snapshot ID, 시행일, 조문 path, 평가 기준일과 적용 조건·예외를 기록한다.
존재하지 않는 OpenMetadata 태그는 분류체계 공백으로 보고한다.

## 연결과 검증

두 제안 Skill은 같은 도구를 사용한다. API 주소 우선순위는 CLI 인자,
`TEORIA_ADMIN_BASE_URL`, Compose 기본 주소 순이다.

```bash
export TEORIA_ADMIN_BASE_URL=http://localhost:8081/admin-api
python3 .agents/skills/enrich-metadata-asset/scripts/fetch_context.py \
  --table-fqn '<service.database.schema.table>' \
  --output /tmp/teoria_metadata_context.json
python3 .agents/skills/enrich-metadata-asset/scripts/submit_proposals.py proposal_bundle.json
```

Compose 네트워크 안에서는 `http://admin-api:8001`, 로컬 API 단독 실행에서는
`http://localhost:8001`을 지정한다. Bearer 인증은 `TEORIA_ADMIN_API_TOKEN`을
사용한다. fetch와 submit 모두 토큰을 환경변수로 받으며 출력하지 않는다.

사용자가 검토 대기열 등록을 요청했으면 검증 후 `--submit`으로 pending
Suggestion을 등록한다. 기존 `$analyze-metadata-asset`와 스크립트 경로는
호환 진입점으로 유지한다.

## 검토와 적용

| 제안 유형 | 승인 후 효과 |
|---|---|
| `description` | OpenMetadata 테이블·컬럼 설명 변경 |
| `glossary_term` | OpenMetadata Glossary Term 생성 |
| `glossary_term_assignment` | OpenMetadata 컬럼에 Term 할당 |
| `binding` | Binding Draft 생성; 별도 승인 후 활성화 |

컬럼 설명 제안은 `table_id`, `column_name`, `column_fqn`, `source_version`,
`source_description`을 포함한다. 승인 시 원천 변경을 검사하며 대상이 바뀌면
`stale_evidence`로 중단한다. 같은 분석에서 생성한 설명은 승인된 의미 근거로
취급하지 않는다. 기본 의미 경로는 `Physical Asset -> Glossary Term -> Ontology`다.

모든 Skill은 제안·초안까지만 생성하며 직접 승인·적용하지 않는다.
OpenMetadata entity 상태나 원본 샘플을 Teoria DB에 복제하지 않는다.

실행 계약:
[메타데이터 정비](../../.agents/skills/enrich-metadata-asset/SKILL.md),
[업무 의미 연결](../../.agents/skills/align-metadata-semantics/SKILL.md),
[개방 적합성 진단](../../.agents/skills/assess-data-disclosure/SKILL.md).
두 제안 Skill의 bundle 형식은
[proposal schema](../../.agents/skills/enrich-metadata-asset/references/proposal_bundle.schema.json)를 따른다.
