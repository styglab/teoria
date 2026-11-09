# 메타데이터 조회·진단·검토

OpenMetadata가 자산·스키마·설명·소유자·태그·Glossary·품질·계보의 기준이다.
Teoria는 외부 자산을 `MetadataTargetRef`로 참조하고 진단·제안·검토·적용 이력을 관리한다.
자산 본문과 원본 샘플을 Application DB에 복제하지 않는다.

## 자산 조회

**데이터 → 데이터 자산**에서 테이블을 열면 기술·운영·업무·거버넌스 정보를 확인한다.
`GET /v1/admin/metadata/asset-context/{table_id}`는 OpenMetadata와 명시적으로 연결된
수집 audit를 조합한다. 이름 유사성으로 Pipeline을 추정하지 않는다.
원천 조회 실패, 미연결, 미수집과 빈 결과를 구분한다. 일부 저장소 장애는 해당 영역에 표시한다.

`TEORIA_ADMIN_METADATA_PUBLIC_READ=true`인 경우 카탈로그·상세·계보·프로파일을 공개 조회할 수 있다.
기본값은 false이며 샘플·변경·진단에는 관리자 인증을 유지한다.

| API | 반환 내용 |
|---|---|
| `GET /v1/admin/metadata/tables/{id}/sample-data?limit=10` | OpenMetadata에 이미 수집된 샘플; 비NULL 값은 기본 마스킹 |
| `GET /v1/admin/metadata/tables/{id}/profile` | 행·컬럼 수, null·distinct·unique·길이 지표 |

`include_values=true`는 `metadata_sample_reader` 역할이 있어야 한다. 샘플은 최대 50행·100컬럼·문자열 500자이며
중첩 값은 제외한다. 원천 PII masking을 해제하지 않는다. 응답은 no-store다.
프로파일의 min/max·빈도값·값 목록·custom SQL metric은 반환하지 않는다.
미수집(`available=false`)과 수집된 빈 샘플(`available=true`)을 구분한다.
기본 ingestion은 schema metadata만 수집하며 이 조회가 샘플 수집·프로파일링을 실행하지 않는다.

## 자산 진단

자산 상세의 **자산 진단**에서 범위·컬럼을 선택해 요청한다. 진단은 예약 스캔이 아닌 사용자 실행이다.

| 범위 | 현재 결과 |
|---|---|
| `metadata_enrichment` | 설명 변경 Suggestion |
| `semantic_alignment` | 기존 Published Concept에 대한 직접 자산 Binding Suggestion |
| `disclosure_assessment` | 수집 법령을 근거로 한 검토 findings |

`POST /v1/admin/intelligence/asset-assessments`는 `metadata_admin` 인증을 요구한다.
입력은 `table_fqn`, `scopes`, 선택적 `column_names`·`assessment_date`·`disclosure_context`다.
컬럼은 최대 30개이며 `disclosure_context`는 `public_release` 또는 `restricted_sharing`이다.
목록과 단건 조회는 같은 prefix의 GET API이며, 자세한 schema는 Admin OpenAPI를 따른다.

Worker는 `queued → running → completed / partial / failed` 상태를 관리한다.
`SKIP LOCKED`·claim token·10분 lease로 선점하고 실행을 8분으로 제한한다.
만료 작업만 최대 3회 재선점하며 만료 Worker는 결과를 저장하지 못한다.
Codex subprocess의 schema 응답을 검증하고 선택 컬럼·게시 Concept·근거 ID와 원천 version을 재확인한다.
검증한 결과와 제안은 한 transaction으로 기록한다. 모델 원문·자산 본문·법령 본문·샘플은 저장하지 않는다.

현재 Worker는 샘플 입력, Glossary 생성·할당 추론, 신규 Ontology, 자동 태깅·승인·게시를 지원하지 않는다.
원천 업무 문서를 대조하지 않은 제안은 추정으로 표시하며 confidence를 0.69 이하로 제한한다.
직접 자산 Binding은 기본 경로 `Physical Asset → Glossary Term → Ontology`보다 우선하지 않는다.

### Worker 실행

`TEORIA_ASSESSMENT_ENABLED=true`와 선택적 `TEORIA_ASSESSMENT_CODEX_MODEL`을 설정한다.
모델이 비면 로그인한 Codex CLI 설정을 사용하며 다른 gateway로 fallback하지 않는다.
모델 요청과 실제 Worker 설정이 다르면 `assessment_model_changed`로 실패한다.
규격서와 분리된 `metadata-model-auth` 볼륨에 로그인한 뒤 동일한 배포 구성으로 반영한다.

```bash
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml \
  -f deploy/compose/compose_semantic.yaml run --rm --no-deps \
  --entrypoint codex metadata-assessment-worker login --device-auth
bash deploy/compose/deploy.sh build
bash deploy/compose/deploy.sh deploy
```

## 제안 검토·적용·복구

`pending → approved → applied / failed`로 진행하며 거절·변경 요청도 기록한다.
변경 주체는 인증 principal이다. 요청 body의 actor·reviewer를 신뢰하지 않는다.

1. 원천의 현재 값·version과 제안 당시 근거를 비교한다.
2. 권한 있는 검토자가 승인·거절·변경 요청한다.
3. 서비스가 원천과 참조를 재검증한 후 적용하고 결과·시도를 기록한다.

| 대상 | 승인 후 효과 |
|---|---|
| 설명·Glossary·quality test | OpenMetadata API에 적용하고 결과 확인 |
| Semantic Binding | Binding Draft 생성; 별도 승인 필요 |
| Ontology | 새 Draft에 적용; 별도 검토·승인·게시 필요 |
| 공개 진단 findings | 검토 보고서; 자동 태깅·공개 승인 없음 |

생성은 `metadata_admin`, 검토·복구는 허용된 `metadata_reviewer`·`metadata_admin`·`ontology_owner`가 수행한다.
Ontology 변경 검토에는 `ontology_owner`가 추가로 필요하다. 승인과 적용 성공은 구분한다.
`intelligence.application_attempts`의 실행권·효과 기록으로 중복 적용을 막는다.
변경 전 실패는 기존 승인으로 재시도하고, 결과가 불확실하면 외부 변경을 재실행하기 전에 결과를 확인한다.
`stale_evidence`는 재분석한다. 실행 중 작업을 중복 호출하지 않는다.

공통 prefix `/v1/admin/intelligence`:

| 경로 | 용도 |
|---|---|
| `GET /suggestions?status=pending&table_id=<uuid>` | 상태·자산별 목록; `after` cursor |
| `GET /suggestions/{id}/target` | 현재 대상과 제안 비교 |
| `POST /suggestions/{id}/reviews` | 승인·거절·변경 요청·대체 |
| `GET /suggestions/{id}/applications/attempts` | 적용 시도 이력 |
| `POST /suggestions/{id}/applications/retry` | 기존 승인으로 재시도 |
| `POST /suggestions/{id}/applications/reconcile` | 기존 효과 확인 |

## Codex Skills

| Skill | 범위 |
|---|---|
| [enrich-metadata-asset](../../.agents/skills/enrich-metadata-asset/SKILL.md) | 설명·Glossary 정비 제안 |
| [align-metadata-semantics](../../.agents/skills/align-metadata-semantics/SKILL.md) | 기존 Published Concept와 연결; 미대응 의미는 공백으로 보고 |
| [assess-data-disclosure](../../.agents/skills/assess-data-disclosure/SKILL.md) | 정보 유형·법령·보호조치 검토 초안 |

자산 상세에서 요청을 복사하거나 FQN을 지정한다. 세 Skill은 제안·초안까지만 작성한다.
검토 대기열 제출 요청이 있으면 검증 후 pending Suggestion으로 제출하고 직접 승인·적용하지 않는다.
API 주소는 CLI 인자 → `TEORIA_ADMIN_BASE_URL` → Compose 기본값 순이며 bearer는 환경변수로 전달한다.
제안 bundle은 [공통 schema](../../.agents/skills/enrich-metadata-asset/references/proposal_bundle.schema.json)를 따른다.

## 법령 근거

`POST /v1/admin/legal-information/search`에 `query`, `assessment_date`, `version_scope`를 전달한다.
키워드는 최대 8개·200자이며 `match=any/all`로 OR/AND를 선택한다. 의미 검색은 아니다.
`as_of`는 공포·시행일 기준의 후보를 고른다. 최신 후보 본문이 없으면 과거 버전으로 대체하지 않고
`unavailable_versions`로 표시한다. 개별 적용례·예외를 자동 판단하지 않으며
`legal_applicability_confirmed=false`를 반환한다.

`GET /v1/admin/legal-information/documents/{snapshot_id}?path=...`로 같은 근거를 조회한다.
근거에는 snapshot·조항 path·hash·버전·평가일을 남긴다. 법령 근거가 없으면 `review_required`로 보류한다.
법령 검색은 Admin 진단 API이며 Runtime Capability나 MCP Tool은 아니다.
본문은 [법령 수집](../pipelines/domains/legal_information.md)의 Data DB read view에서 조회한다.

구현: `platform/data/metadata/catalog/`, `platform/data/metadata/intelligence/`,
`domains/legal_information/`. 연결·권한은 [환경 설정](../deployment/configuration.md),
수집은 [OpenMetadata](../deployment/openmetadata.md)를 따른다.
