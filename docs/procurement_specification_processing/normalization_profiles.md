# 정규화 프로파일

프로파일은 **게시된 Ontology 개념을 규격서에 적용하는 규칙**이다.
원문 표현·대상·역할·범위·단위 정책을 고정하고, 승인한 패키지를 Pipeline에 전달한다.

## 사전과 무엇이 다른가

| 구분 | 역할 |
|---|---|
| [사전](../platform/goods_dictionary.md) | 원문 표현·근거와 게시 Ontology Stable Concept ID 연결 |
| 프로파일 | 특정 Published Ontology를 참조하는 문서 적용 규칙 |
| 추출 결과 | 특정 규격서의 대상·관계·값·조건·근거 |

새 사전 연결과 프로파일은 같은 Ontology Stable Concept ID와 게시 버전을 참조한다. 문서 내 로컬 ID와 과거 v1 사전 ID는 별도다.
v2 표현 연결은 프로파일의 별칭을 우회 경로로 사용하지 않으며 역할·범위·값·단위 변환은 프로파일이 검사한다.
현재 goods 모델은 Draft이므로 이 문서의 프로파일 기반을 현재 물품 모델에 이미 게시·적용했다고 해석하지 않는다.

## 작성과 사용

### 소유 대상·범위의 해석 제안

기존 추출의 소유 대상이나 scope를 재검토할 때는 원문 관찰을 덮어쓰지 않는다.
`review-meanings`는 기존 문서 결과와 Ontology 작성 버전을 고정하고, 별도 해석 제안을 검사·저장한다.
Draft도 참고할 수 있지만 출력은 항상 `specification_meaning_review`, `authority: suggestion`,
`mode: review_only`다. 게시 개념 연결이나 승인 프로파일을 대신하지 않는다.

```bash
uv run --project backend --locked teoria-pipelines specification review-meanings \
  --manifest /data/meaning_review.json \
  --output-root s3://teoria-artifacts/specification_processing/meaning_reviews
```

실행 역할에는 원본 산출물 읽기, 지정 prefix의 쓰기 권한과
`TEORIA_SPECIFICATION_AUTHORING_API_URL`, `TEORIA_SPECIFICATION_AUTHORING_API_TOKEN`이 필요하다.
기존 규격서 Worker 역할로 실행하며 Admin API용 S3 권한을 확대하지 않는다.

입력 계약은 `MeaningReviewInput`이다.

| 입력 | 내용 |
|---|---|
| `review_id` | 새 검토 산출물의 고유 ID |
| `result` | 기존 `specification_document_result`의 URI와 전체 바이트 SHA-256 |
| `document_id`, `source_sha256` | 검토할 문서와 원본 식별자 |
| `ontology` | 작성 버전의 `version_id`, `namespace`, `version`, `status`, `content_checksum` |
| `entities` | 로컬 `subject_id`, 후보 Stable Concept ID, 문서/node/인용 근거, 제안 사유 |
| `properties` | 로컬 `observation_id`, 후보 Property Concept ID, 제안 `subject_id`·`semantic_scope`, 근거·사유 |

작성 버전 전체 조회 결과의 canonical checksum을 고정하고 실행 시 Admin HTTP API로 다시 확인한다.
게시 artifact의 checksum·참조 계약과 구별하며 Draft를 Runtime에 전달하지 않는다.
원문 관찰의 값·단위·연산자·역할·조건은 수정 입력으로 받지 않는다.
제안 scope·소유 대상은 `interpretation`에, 원래 관찰은 `source`에 보관하고 차이를 `changes`에 표시한다.
출처 인용, 대상 존재 여부, Property 소유 유형, 자료형·단위가 맞지 않으면 `held`로 남긴다.
검사를 통과해도 `requires_review`이며 인용의 존재만으로 의미 동등성을 확정하지 않는다.
특히 한 셀에 있는 수치의 정확한 귀속과 scope 해석은 별도 검토가 필요하다.

`request.json`, `review.json`을 불변 산출물로 저장한다. 같은 입력의 재실행은 같은 바이트를
재사용하며 다른 입력은 새 `review_id`를 요구한다. 출력의 선택 건수와 문서 전체 관찰 수를 구분한다.
CLI 성공은 근거·구조 검사 통과이며 사람의 승인이나 추출 정확도 판정이 아니다.
프로파일 적용에 이 제안 또는 연결 비교 산출물을 승인 근거로 전달하면 거절한다.
현재 이 경로는 CLI 산출물 검토이며 FormatID의 승인 UI·자동 적용 경로는 제공하지 않는다.
실제 서버 문서 대조 결과는 [검증 기록](../verification/goods_native_draft_preparation_2026_11_09.md)을 따른다.

### 게시 의미의 연결과 적용

게시 정의는 사전 없이 `GET /v1/admin/ontology-authoring/versions/{version_id}/publication`으로
조회한다. 반환한 `ontology` 참조를 규격서 입력의 `ontology_alignment.publications` 목록에,
검토할 Stable Concept ID를 `ontology_alignment.concept_ids`에 지정하면 고정 추출 관찰의
연결 후보를 생성한다. 하나의 version에 다른 checksum·namespace·version을 지정하면 거부한다.
이 비교는 프로파일 적용이나 의미 승인을 수행하지 않는다.

`ontology_alignment.snapshot`은 파일/S3 URI·SHA256으로 고정한 `published_ontology_context`를
입력하는 대안이다. 기존 v2 사전 snapshot도 호환 입력으로 읽으며 그 경우 표현 예시·승인 상태를
사전 API에서 추가 검증한다. `publications`와 `snapshot`은 동시에 지정하지 않는다.
어느 입력이든 게시 권위는 Ontology publication API로 확인하고 실행에 사용한 문맥을
`ontology_context.json`으로 저장한다. 사전은 정의 원장이 아닌 선택적인 표현 예시 제공자다.

명시적 규격서 실행에 `use_expression_dictionary: false`를 지정하면 06 단계의 표현 등록·사전 조회를
건너뛴다. 추출·원본·산출물과 게시 정의를 사용한 연결 비교는 유지한다. 기존 입력의 기본값은 true다.
사전 snapshot·재구축·대량 사전관리·사전 기반 처리 기준 승인 입력과는 함께 사용할 수 없다.
사전을 끄더라도 미승인 표현을 프로파일 별칭으로 우회하지 않는다. 게시 의미 패키지의 적용은
승인된 연결이 없는 관찰을 보류하며, 연결 비교 결과는 계속 Suggestion이다.

```text
Published Ontology 선택 → 프로파일 Draft → 검토·승인 → 고정 패키지
                                                      ↓
규격서 → extracted.json ─────────────────────────→ 규칙 적용
                                                      ↓
                                           normalized.json + 보류
```

1. 실제 Published version과 적용할 개념을 선택한다. 임의 UUID나 삭제한 서버 모델을 사용하지 않는다.
2. `POST /v1/admin/goods/normalization-profiles/from-template`에 `ontology_version_id`와 `profile_template`을 제출한다.
   템플릿의 concept_id 입력은 Stable Key이며 서버가 게시 artifact에서 실제 Stable Concept ID로 해석한다.
3. 생성한 revision의 `/transitions`에 `submit`, 검토 후 `approve`를 제출한다.
4. `GET /{revision_id}/package`의 원본 바이트를 파일/S3에 저장한다.
5. 파일 **전체 바이트의 SHA-256**과 URI를 Pipeline의 `standard`에 지정한다.

```json
"standard": {
  "uri": "file:///app/specification_inputs/approved_package.json",
  "sha256": "<파일 전체의 SHA-256>"
}
```

패키지 내부 checksum과 파일 전체 SHA-256은 다르다. actor는 인증 principal에서 기록한다.
이름·소속·관계 endpoint·자료형·단위·게시 artifact가 맞는지 승인·내보내기 때 검사한다.
형식 예시인 [서버 메모리 템플릿](examples/server_memory_profile.json)은 goods 2.0.0 Draft의 native
Stable Key를 사용하며 실제 게시 후에만 실행 가능한 ID로 해석할 수 있다. 모듈당 용량·서버 전체
용량·CPU 소켓당 지원 상한·슬롯 수의 소유 유형·범위·역할을 별도 규칙으로 관리한다.
공급 모듈 수는 구성 명세의 수량이며 모듈 자체의 용량이나 전체 슬롯 수가 아니다.
템플릿은 문자열 별칭으로 승인 표현 연결을 우회하지 않는다. 현재 운영 서버 모델이나 승인 프로파일이 아니다.

프로파일과 후보 묶음의 `classification_code: null`은 미분류 문맥이다. 분류가 알려진 문서와
자동 호환되는 wildcard가 아니며 코드가 다르거나 null 여부가 다른 입력은 계속 거절한다.
규격서 이름으로 분류코드를 추정하여 넣지 않는다. 과거 0.2.0 메모리 확장과 예전 템플릿은
호환 검사 자료로 보존하며 현재 작성 예제로 사용하지 않는다.

## 후보 수집에서 새 Draft까지

고정 패키지를 적용한 표준관리 실행은 미해결 관찰을 `meaning_candidates.json`에 모은다.
bundle에는 원문 checksum·관찰 ID·위치·인용·대상·역할·범위가 포함된다.
이름이 비슷하다는 이유로 동의어로 합치지 않고, 같은 원문 관찰의 중복 집계도 막는다.

| API | 하는 일 |
|---|---|
| `POST /candidate-proposals` | 승인 기준 revision과 bundles에서 후보 묶음·기존 개념 후보 생성 |
| `POST /from-candidates` | 선택한 개념·단위·관계 방향으로 새 프로파일 Draft 작성 |
| `PUT /{revision_id}` | 편집 가능한 Draft 수정 |
| `POST /{revision_id}/transitions` | submit·approve·request_changes·reject·deprecate |
| `GET /{revision_id}/audit` | 판정·변경 이력 조회 |

위 경로의 공통 prefix는 `/v1/admin/goods/normalization-profiles`다.
기존 개념 후보의 문자열 점수는 정확도나 동등성 확정이 아니다.
대상·근거·자료형·단위·방향이 불명확하면 보류한다. 새 개념은 별도 Ontology Draft에서 관리한다.

FormatID는 규격서별 엔티티·관계·속성의 결과 탐색을 맡으며 프로파일 검토·승인 화면을 제공하지 않는다.
프로파일 작성·승인은 위 인증된 Admin API를 사용하는 별도 의미 관리 절차다. 기준 프로파일 revision과
검증된 bundle, `ontology_owner` 역할이 필요하다. 숫자 속성은 단위 변환을, 관계는 방향을 명시한다.
상태 전이 요청에는 확인한 `expected_content_checksum`과 `expected_status`를 함께 보낼 수 있다.
서버는 row lock 안에서 대조하고 다른 내용·상태라면 409로 거절한다.
승인된 고정 패키지는 후속 실행의 표준 입력으로 사용할 수 있다.

승인한 프로파일을 수정하려면 새 version을 만든다. deprecate는 새 export를 막으며 이미 전달한
패키지를 원격 수정하지 않는다. checksum은 내용 일치를 검사하며 승인 권위를 대신하지 않는다.

## Codex 의미 판정과 자동 승인 평가

선택적인 의미 작성 API는 원문 bundle과 게시 개념을 Codex에 제공해 `existing/new/hold`를 제안받는다.
인용·소속·자료형·단위·관계 방향을 검증한다. 모델 응답이 정확한 업무 의미라는 증명은 아니다.

| API | 역할 |
|---|---|
| `POST /semantic-proposals` | Codex 의미 제안 |
| `POST /semantic-ontology-drafts` | 신규 개념을 Ontology Draft로 작성 |
| `POST /semantic-profile-drafts` | 게시된 개념을 확인하고 프로파일 Draft 작성 |
| `POST /semantic-cycles` | 의미 제안과 작성 순서를 연결 |
| `POST/GET /semantic-operations/{operation_id}` | 내구성 있는 실행·상태 조회·재개 |

일반 cycle은 승인·게시가 필요한 곳에서 대기한다. 새 의미를 자동 게시하지 않는다.
`auto_approve: true`는 별도 임시 DB의 `goods_eval_` 평가용 Ontology에서만 허용하고 기존 승인 검사를 수행한다.
원문 등록의 `dictionary_auto_approve`와 다른 정책이다.

## 전체 표준관리 Flow 실행

상위 `procurement-standard-workflow`는 두 처리 방식을 재사용하는 선택적인 조립이다.
**승인된 기준 프로파일 revision이 이미 있어야 한다.**

```text
기준 패키지 확보 → 원본 추출
 → 엔티티 후보의 의미 작성·승인
 → 새 패키지 확보 → 관계·요구조건 후보의 의미 작성·승인
 → 같은 추출에 최종 패키지 재적용
```

입력은 `workflow_id`, `base_profile_revision_id`, `auto_approve`, `extraction`이다.
extraction은 model을 명시한 standard_management 입력이며 별도 standard를 중복 지정하지 않는다.

```bash
uv run --project backend --locked --group orchestration \
  teoria-pipelines specification standard-workflow --manifest /data/workflow.json
```

승인 대기는 awaiting_approval과 phase·operation·Draft ID로 반환한다.
검토·게시 후 같은 입력과 workflow_id로 다시 실행하면 재개한다.
lease·heartbeat로 동시 실행을 막고, 같은 ID에 다른 입력·코드·작성 API를 사용하면 거부한다.

## 저장·중단·재시도

| 위치 | 저장 내용 |
|---|---|
| Application DB | 프로파일 개정·판정 이력·의미 작성 operation |
| Data DB | 상위 Flow 상태·lease·단계별 operation·산출물 참조 |
| 파일/S3 | 원문·추출·후보·고정 패키지·최종 결과 본문 |

Pipeline은 인증된 Admin HTTP API만 사용하며 작성 DB·Runtime을 직접 호출하지 않는다.
Worker의 작성 API URL·token·Data DB·Parser·모델 설정은 [환경 설정](../deployment/configuration.md)을 따른다.
전체 산출물 저장이 성공한 뒤 완료 checkpoint를 기록한다. 기존 패키지·게시 의미를 덮어쓰지 않는다.

## 호환과 검증

schema v1 `standard.json`은 로컬 추출 초안의 호환 경로다. 그 ID는 Published Concept ID가 아니다.
schema v2 package는 게시 의미와 승인 프로파일을 참조한다. 입력이 없는 원문 처리를 프로파일 승인과 혼동하지 않는다.

프로파일 계약은 `features/goods_normalization/contracts/`, 승인 정책은 `profiles/`,
적용은 `specification_processing/normalization/profile_application.py`가 소유한다.

```bash
uv run --project backend --locked --all-extras --group orchestration pytest backend/tests
```

SQL 통합 검사는 운영과 분리한 `TEORIA_TEST_APP_DATABASE_URL`·`TEORIA_TEST_PIPELINE_DATABASE_URL`을 사용한다.
통제된 응답 검사, 실제 모델 추출, 운영 배포는 각각 구분한다.

[DocumentGoodsGraph 대표 예시](../../backend/authoring/specification_examples/four_sample_graphs.yaml)는
분류 없이 구조·참조를 검사하는 제안 계약이다. 프로파일 게시·적용·전체 자동 그래프 생성의 성공 사례는 아니다.

`teoria-pipelines specification validate-graph --manifest <문서_그래프.yaml>`는 기존 구조 검사를
유지한다. 선택적인 `--ontology-context <고정_게시_문맥.json>`을 지정하면 명시적인
`type_concept_ref`·`property_concept_ref`의 버전·종류·owner도 검사한다. 미연결 관찰은 그대로
보존한다. 이 로컬 검사는 게시 권위·원문 의미의 정확성·검토 승인을 확정하지 않는다.

## API 값과 문서 요구조건의 대조

프로파일의 수치 정규화와 의미를 선언한 Runtime Mapping은 Ontology 소유의 같은 단위 변환·
유한 수치·정수 검증을 사용한다. 문서 결과의 `requirements[].semantic_observation`은
Runtime의 `semantic_observations[]`와 같은 값 계약을 사용한다. Pipeline이 Runtime을 호출하는 것은 아니다.

역할을 `requirement`·`capability`·`reference`·`recommendation`·`option`으로 구분하고
원문 조건·범위·값/단위·문서 해시·원문 위치·프로파일 개정·rule ID를 함께 보존한다.
API의 `declared_value`·`measurement`와 표현이 같다는 이유로 합치지 않는다.

물품 기능의 `compare_property_observations`는 같은 게시 개념·단위·범위의 단일 대상에 대해,
명시적으로 확인한 대상 연결이 있을 때만 숫자 요구조건을 대조한다. 미검토 조건, 미확정 대상,
서로 다른 버전, 지원 한도를 제품 명시값으로 사용하는 경우는 보류한다. 이 결과는 개별 속성의
수치 대조이며 전체 조달 적합성·참가자격 판정이나 제품 자동 채택을 의미하지 않는다.
