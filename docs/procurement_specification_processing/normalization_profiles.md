# 물품 정규화 프로파일과 실행 패키지

공통 의미는 Platform의 Published Ontology가 소유한다. 프로파일은 그 Stable Concept ID에
원문 표현·추출 속성 키·역할·적용 범위·단위 정책을 연결한다. 표준 적용 모듈은 내보낸 패키지만 읽으며
Platform Runtime이나 authoring DB를 호출하지 않는다. 상위 Workflow는 작성 API로 제안·승인 상태를 연결한다.
Semantic Binding을 문서별 관찰 저장소로 사용하지 않는다.

## 소유권

| 위치 | 책임 |
|---|---|
| `backend/src/teoria/features/goods_normalization/` | 프로파일 작성·검토·승인 이력과 패키지 발행 |
| `backend/src/teoria/features/goods_normalization/contracts/` | 발행과 적용이 공유하는 계약·checksum·지원 단위 정책 |
| `backend/src/teoria/features/specification_processing/normalization/profile_application.py` | 원문 대조와 고정 패키지 적용 |
| Application DB `goods.normalization_profile_revisions`, `normalization_profile_events` | revision과 변경·승인 기록 |

```text
원문 → 공통 추출 → extracted.json
                       ↓
고정 normalization package → 엔티티·관계·요구조건 매핑
                       ↓
normalized.json + 미해결 후보 → 새 프로파일 Draft 작성·검토·승인
                                        ↓
                              변경되지 않는 새 패키지
```

새 개념은 기존 Ontology 작성·승인·게시 API로 관리한다. 프로파일 승인은 Ontology를 게시하지 않는다.
후보의 문맥별 묶기·기존 개념 검색·선택 결과의 Draft 변환을 지원한다.
기본 검색은 이름·Stable Key·기존 별칭의 문자열 유사도와 문맥 필터를 사용한다.
별도 Codex 의미 판정 경로는 기존 개념 연결·신규 개념 Draft·보류를 제안한다.
이미 승인된 프로파일의 문서 적용에는 사람 검토가 필요하지 않다.

## 작성과 사용

API를 실행하기 전에 `TEORIA_APP_DATABASE_URL`을 설정한 배포 절차에서 Application DB migration을
적용한다. 새 테이블은 `017_goods_normalization_profiles.sql`에서 추가한다.
`018_ontology_relationship_descriptions.sql`은 관계의 의미 설명을 작성·Draft 복제·게시 과정에서
보존하도록 추가한다. 기존 게시 JSON artifact는 변경하지 않는다.

```bash
uv run --locked --project backend --extra api teoria migrate-app
```

1. 적용할 Published Ontology version을 선택한다. 초기 `goods.yaml`은 Draft 모델이다.
   `goods_requirement_enrichment.yaml`은 기존 Published goods에서 `0.2.0` Draft를 만들고 요구조건의
   개념 참조·수치·단위·역할·범위 속성을 추가한다. 이어서 `goods_memory_extension.yaml`을 같은 Draft에
   적용한다. 두 파일은 `backend/authoring/ontology_blueprints/`에 있다. 기존 작성 API/CLI로 적용하고
   검토·승인·게시는 별도로 수행한다. 이미 게시한 `0.2.0`이 있으면 새 Draft version을 사용한다.
   기존 게시 버전은 수정하지 않는다. 이 구현 작업은 실제 goods 게시를 실행하지 않는다.
2. [서버 메모리 템플릿](examples/server_memory_profile.json)을 준비한다. 템플릿의 `concept_id` 필드는
   이 입력 방식에서 Stable Key다. UUID를 임의로 생성하지 않는다.
3. 인증된 Admin API `POST /v1/admin/goods/normalization-profiles/from-template`에 다음을 제출한다.
   body의 `ontology_version_id`는 선택한 게시 version UUID, `profile_template`은 템플릿 전체 JSON이다.
   서버가 게시 artifact의 namespace·버전·checksum과 Stable Key→Stable Concept ID를 해석해 Draft를 만든다.
4. 응답의 `revision_id`로 `POST /v1/admin/goods/normalization-profiles/{revision_id}/transitions`에
   `{"action":"submit"}`, 검토 후 `{"action":"approve"}`를 순서대로 제출한다.
   게시 상태·artifact checksum·개념 종류·속성 소속·자료형·단위를 검사한다. actor는 인증 principal이다.
5. `GET /v1/admin/goods/normalization-profiles/{revision_id}/package` 결과를 파일/S3에 보관한다.
   **JSON 전체 바이트의 SHA-256**을 구해 Pipeline manifest의 `standard.uri`, `standard.sha256`에 넣는다.
   패키지 내부 checksum과 파일 전체 SHA-256은 다르다.
6. 기존 명령으로 실행한다.

   ```bash
   uv run --locked --project backend teoria-pipelines specification run --manifest /data/run.json
   ```

`standard_management`는 같은 고정 패키지를 적용하고 `meaning_candidates.json`에 미해결 관찰을 모은다.
패키지를 직접 수정하거나 새 의미를 승인하지 않는다. `document_processing`도 같은 패키지를 적용하며
미해결 내용은 `normalized.json` 안에 보존한다.

Draft 수정은 `PUT /v1/admin/goods/normalization-profiles/{revision_id}`, 검토 회수는
`request_changes`, 거절은 `reject`, 승인 프로파일 중단은 `deprecate`다. 승인 후 내용 변경은
새 version으로 만든다. `GET /{revision_id}/audit`에서 이력을 읽는다. deprecate는 새 export를 막으며
이미 배포된 고정 패키지를 원격으로 수정하지 않는다.

## 후보 수집에서 새 Draft까지

승인 패키지를 사용하는 `standard_management` 실행의 기존 `meaning_candidates.json`에
`bundle`을 추가한다. 별도 추적 파일은 만들지 않는다. 엔티티·관계·요구조건별 원문 표현,
문서 checksum·로컬 ID·원문 위치·해당 원문 텍스트와 추출기의 근거 검사 결과를 보존한다.
Platform은 이 bundle을 입력받으며 Pipeline에서 Platform API를 호출하지 않는다.

묶기 키는 분류와 고정 Ontology 버전 아래의 항목 종류·표현·대상 개념·역할·범위·자료형·단위다.
공백·유니코드 표기만 정리하며 유사한 표현을 동의어로 확정하여 합치지 않는다.
동일 원문 checksum·관찰 종류·로컬 ID는 여러 실행에서 중복 집계하지 않는다.
같은 관찰의 원문·문맥이 서로 다르면 입력을 거절한다. 문서 빈도는 서로 다른 원문 checksum 수다.

1. `POST /v1/admin/goods/normalization-profiles/candidate-proposals`에
   `base_revision_id`와 `bundles` 배열을 제출한다. 각 배열 원소는 산출물의 `bundle` 전체다.
   기준 프로파일은 승인 상태여야 하고 모든 입력의 분류·Ontology 참조가 같아야 한다.
2. 결과의 `groups`마다 원문 관찰과 `matches`를 확인한다. 기존 개념 후보는 속성 소속·자료형과
   관계 endpoint로 제한한 뒤 문자열 유사도로 최대 5개를 제시한다.
   `existing_concept_proposal`은 의미 동등성의 확정이 아니다.
   `new_concept_review`는 검색에서 연결하지 못했다는 뜻이며 신규 개념이 필요하다는 증명도 아니다.
   근거·대상·역할·범위가 불명확한 항목은 `hold`로 둔다.
3. `POST /v1/admin/goods/normalization-profiles/from-candidates`에 같은 입력과 새 `version`,
   `selections`를 제출한다. 예를 들어 수치 속성은 다음처럼 선택한다.

   ```json
   {
     "group_id": "<결과의 group_id>",
     "concept_id": "<선택한 Published Stable Concept UUID>",
     "units": [{"source_unit": "GB", "canonical_unit": "GB", "multiplier": "1"}]
   }
   ```

   `selections`는 위 객체의 배열이다. 관계는 `reverse`를 명시하며 endpoint 방향과 대조한다.
   숫자 단위는 관찰된 단위와 Published 속성 단위에 맞는 정책을 명시해야 한다.
   잘못된 소속·자료형·단위·방향·중복 규칙은 Draft 생성 전에 거절한다.
4. 새 Draft의 생성 이력에 입력 checksum·제안 checksum·기준 revision·선택 내용·인증된 actor를
   기록한다. 원문 본문은 Application DB에 복제하지 않는다. 기존 프로파일과 Published Ontology는
   변경하지 않으며 새 Draft는 기존 submit·approve·export 절차를 따른다.

자동 검색의 문자열 점수는 확률이나 정확도가 아니다. 수신 bundle의 checksum은 전달 무결성만
검사하며 원문 파일의 진위·독립적 의미 검증을 대신하지 않는다. 추출 위치에서의 근거 검사와
함께 통제된 산출물 경로를 사용한다. 대상 엔티티 자체가 미해결이면 그 속성은 보류한다.
엔티티 별칭을 먼저 반영한 새 패키지를 적용한 후 속성 후보를 다시 수집한다.
기존 규칙에 새 단위를 추가하는 등 겹치는 정책 수정은 이 추가형 API가 자동 수행하지 않으며
Draft 편집에서 적용 범위를 명시적으로 조정한다. 신규 개념은 별도 Ontology Draft로 관리한다.

## Codex 의미 판정과 자동 승인 평가

`semantic_resolution.py`는 동일 bundle과 Published 개념의 이름·설명·소속·자료형을
Codex에 제공한다. 기본 문자열 검색의 점수 문턱으로 의미 판정 후보를 제거하지 않는다.
그룹별로 `existing`, `new`, `hold` 중 하나를 받고, 적용 제안에는 관찰 인덱스와 원문 그대로의
인용을 요구한다. 원문은 지시문으로 실행하지 않는다. 응답은 JSON Schema와 Pydantic으로 검증하고,
원문 인용·속성 소속·단위·관계 방향이 맞지 않는 제안은 보류한다.
이 검사는 의미적 정확성의 증명이 아니며 실제 평가와 구분한다.

인증된 Admin의 `/v1/admin/goods/normalization-profiles` 아래에서 다음을 사용한다.

| 경로 | 입력·동작 |
|---|---|
| `POST /semantic-proposals` | `base_revision_id`, `bundles`, 명시적 `model`, 선택적 `timeout`. Codex 제안 반환 |
| `POST /semantic-ontology-drafts` | 기준 revision·bundle·`semantic_report`·새 `version`. 신규 개념만 Ontology Draft로 작성 |
| `POST /semantic-profile-drafts` | 같은 입력과 `published_version_id`. 신규 개념이 게시된 것을 확인한 뒤 프로파일 Draft 생성 |
| `POST /semantic-cycles` | 기준 revision·bundle·`model`·새 `version`. 의미 판정부터 Draft 생성까지 순서대로 실행 |

일반 cycle은 새 Ontology Draft가 있으면 그 상태에서 반환한다. 검토·게시 후
`semantic-profile-drafts`로 이어간다. 기존 개념 매핑만 있으면 프로파일 Draft를 바로 만든다.
신규 엔티티는 문서 관찰 식별자를 identity로 사용하고, 새 속성은 기존 대상에 귀속시키며,
새 관계는 원문에서 해석된 endpoint와 방향을 유지한다. 개념 UUID는 기존 작성 저장소가 부여한다.

`semantic-cycles`의 `auto_approve: true`는 `goods_eval_`로 시작하는 **평가용 Ontology**에서만
허용한다. 별도 임시 Application DB와 함께 사용하여 기존 submit·approve·publish·export 검사를
생략하지 않고 순서대로 실행한다. actor는 인증 principal이며 자동 승인 사실을 감사 이력에 남긴다.
자동 승인으로 의미 품질이 검증되는 것은 아니다. 운영의 승인 정책을 자동 승인으로 바꾸지 않는다.

Codex 실행은 의미 판정과 규격서 추출이 함께 사용하는 `backend/src/teoria/integrations/codex/`에서 수행한다.
모델을 고정하고 동시 실행·시간 제한을 두며 실패 시 다른 모델로 대체하지 않는다.
[OpenAI Docs의 비대화형 실행](https://learn.chatgpt.com/docs/non-interactive-mode)에 따라
`codex exec --output-schema`를 사용한다. Provider가 지원하지 않는 Decimal 스키마 표현은
전달용 스키마에서 조정하며 실제 수치·단위 검증은 로컬 Pydantic 계약으로 유지한다.
일반 API의 임시 프롬프트·응답은 호출 종료 시 삭제한다. Codex 호출은 기본 2개이며 평가 실행에서는
명시적으로 최대 4개까지 제한하여 동시에 수행할 수 있다. 평가 소유의 임시 작업 폴더에서는 같은
모델·프롬프트 지문의 응답만 재사용할 수 있으며, 평가 종료 시 이 캐시도 삭제한다.
모델 입력에는 게시 snapshot의 의미 필드만 투영하며 내부 작성 행의 `draft` 상태나 작성자·시간을
전달하지 않는다. 응답에서 누락된 그룹이나 구조 검증에 실패한 batch는 명시적으로 보류하여
분모에서 제외하거나 성공으로 집계하지 않는다. 서로 충돌하는 신규 정의·속성 정책도 보류한다.

관계 규칙은 원문 관계 종류와 양쪽 엔티티의 개념을 함께 비교한다. 같은 `component_of` 표현도
CPU→서버와 메모리→서버의 Published 관계에 각각 연결할 수 있으며, 동일 endpoint에 겹치는 규칙은 거절한다.

Platform authoring 이미지에도 CLI를 포함한다. Compose Admin은 기존
`specification-model-auth` volume을 사용하므로 해당 인증을 별도로 준비해야 한다.
이 코드 변경은 이미지 배포나 운영 Ontology 게시를 자동 수행하지 않는다.

## 의미 보존

| 원문 | 결과 |
|---|---|
| RAM 64GB 이상 | 용량 `>= 64 GB`, 납품 요구 역할 유지 |
| 모듈당 32GB, 4개 | `32 GB / per_module`와 `4개`를 따로 유지. 128GB 자동 생성 없음 |
| 최대 1TB 지원 | `1000 GB / supported_capability / support_limit`. 실제 장착 용량으로 변경 없음 |

role·scope를 추측하여 덮어쓰지 않는다. 예외는 추출기가 원문으로 검증하고 `explicit inventory target only`로
표시한 목록 수량이다. 역할·범위 필드가 생략된 이 수량은 그 대상 자체의 요구 수량으로 해석한다.
명시적으로 unknown인 해석은 바꾸지 않는다. 알려지지 않은 역할·범위·동의어·단위, 중복 일치 규칙,
원문에 없는 값은 자동 보류한다. 수치 비교는 단일 수치와 eq/gte/lte/gt/lt를 지원한다.
정보 용량은 SI와 이진 단위를 구분하여 승인한 비율만 적용한다. 개/EA/ea는 같은 개수 표기로 처리한다.
그 외 단위는 동일 표기 정책만
지원하며 `G`를 `GB`로 추정하지 않는다. 범위·공차·모델 성능 서열 해석은 보류한다.

관계는 원문 종류·방향과 Ontology endpoint가 맞아야 적용한다. `in_procurement_scope`를
`has_component`로 자동 변환하지 않는다. 예제의 `has_memory_target`은 문서의 규격 대상 관계이며
실제 설치 자산의 구성 확정을 뜻하지 않는다.

관찰 ID는 원문 checksum·문서 ID·처리 실행 ID·관찰 종류·로컬 ID를 함께 사용한다. 같은 이름이나
다른 실행을 임의로 병합하지 않는다. 로컬 ID와 추출 artifact URI·checksum도 보존한다.
이 ID는 실물 자산의 업무 식별자가 아니다.

## 호환과 검증

schema v1 `standard.json`은 과거 실험용 draft의 호환 경로다. 그 로컬 속성 ID는 Platform의
Stable Concept ID가 아니다. 새 의미 연결에는 schema v2 package를 사용한다. 초기 표준이 없는
실행은 기존 후보 수집까지 진행할 수 있으며 승인 프로파일 생성과 구분한다.

checksum은 내용 일치를 검사한다. 승인 권위는 인증된 Admin과 통제된 artifact 배포 경로에서
확보하며 임의 파일의 `approval_actor` 문자열만으로 권위를 증명하지 않는다.

```bash
uv run --locked --project backend pytest backend/tests/features/goods_normalization/contracts
uv run --locked --project backend --all-extras --all-groups pytest backend/tests
uv run --locked --project backend --all-extras --all-groups pytest backend/tests
uv run --project backend --locked --all-extras pytest backend/tests/integration/test_goods_normalization_contract.py
```

프로젝트별 검사와 프로젝트 간 계약 검사는 각각 실행한다. 실제 SQL 검사는
`backend/tests/integration/application/test_goods_normalization.py`이며 운영과 분리된
`TEORIA_TEST_APP_DATABASE_URL`만 사용한다. 통제된 사례 검증은 실제 규격서의 LLM 추출 정확도 평가가 아니다.

## 전체 표준관리 Flow 실행

유지되는 진입점은 `standard_workflow.py:standard_workflow_flow`이며 Prefect deployment는
`specification-standard-workflow`다. 실행 순서는 다음과 같다.

```text
승인 기준 프로파일의 패키지 확보
 → 원본·파싱·공통 추출(extracted.json)
 → 엔티티 후보 → Platform 의미 판정·작성·승인
 → 새 패키지 확보
 → 관계·요구조건 후보 → Platform 의미 판정·작성·승인
 → 최종 패키지로 같은 추출 결과 재적용 → normalized.json·index.md
```

초기 표준과 새 개념의 bootstrap을 혼동하지 않는다. 입력에는 이미 승인된 기준 프로파일 revision이
필요하다. 신규 Ontology 생성 자체는 기존 작성 절차로 수행한다. 문서 분류는 입력 전에 확인한다.
상위 Flow가 의미를 정의하지 않으며 HTTP 작성 API와 파일/S3 저장소의 참조만 연결한다.

먼저 Application DB migration `019_goods_semantic_operations.sql`과 Data DB migration
`092_specification_standard_workflows.sql`까지 각각 소유 프로젝트의 migration 절차로 적용한다.
Worker에 다음 환경변수를 설정한다. token은 manifest·산출물·로그에 넣지 않는다.

```text
TEORIA_PIPELINE_DATA_DATABASE_URL
TEORIA_SPECIFICATION_AUTHORING_API_URL
TEORIA_SPECIFICATION_AUTHORING_API_TOKEN
```

Compose Worker는 내부 `http://admin-api:8001` 작성 API와 설정된 Admin token을 사용한다.
다른 배포는 인증 principal에 `ontology_owner` 권한을 부여한 작성 API credential을 별도 설정한다.
Worker와 Admin이 공유하는 것은 credential과 HTTP 계약이며 Python import나 DB 연결이 아니다.
규격서 원본과 산출물 저장소 접근 권한, Parser·Codex 인증도 기존처럼 필요하다.

실행 manifest 예시에서 UUID·원본 경로를 실제 값으로 바꾼다.

```json
{
  "workflow_id": "server_standard_01",
  "base_profile_revision_id": "<승인된 기준 프로파일 UUID>",
  "auto_approve": false,
  "extraction": {
    "run_id": "server_input_01",
    "mode": "standard_management",
    "classification_code": "4321150102",
    "model": "gpt-6.1-sol",
    "artifact_root": "file:///app/specification_artifacts",
    "documents": [
      {
        "document_id": "server_01",
        "source_uri": "file:///app/specification_inputs/server.hwpx",
        "filename": "server.hwpx"
      }
    ]
  }
}
```

```bash
uv run --locked --project backend teoria-pipelines specification standard-workflow --manifest /data/workflow.json
```

Prefect에 제출할 때는 같은 JSON을 `manifest` parameter로 제공한다. 이 명령은 실제 Prefect Flow를
실행한다. 자동 스케줄이나 첨부파일 수집은 추가하지 않는다. 평가용 자동 승인은 별도 임시 DB의
`goods_eval_` 기준 프로파일을 선택하고 `auto_approve: true`로 명시한다.

일반 실행은 승인 대기 시 `status: awaiting_approval`, `phase`, `operation_id`와 Draft ID를 반환하고
실행 lease를 해제한다. 기존 작성 API로 검토·승인·게시한 후 **같은 manifest와 workflow_id**로
다시 실행하면 이어간다. 승인 대기는 오류나 완료로 기록하지 않는다.

### 저장·중단·재시도

- 원문·추출·후보·고정 패키지·최종 결과 본문은 기존 파일/S3에 저장한다. 패키지는
  `packages/<revision>/<전체 바이트 SHA-256>.json`으로 저장하고 원본 응답 바이트를 변경하지 않는다.
- 상위 실행 상태·산출물 참조·두 의미 판정 operation ID·최종 실행 참조는 Data DB가 소유한다.
  모델·프롬프트 원문과 추출 본문을 이 체크포인트에 복제하지 않는다.
- Platform `goods.semantic_operations`에는 입력 checksum·인증 actor·AI 의미 제안·작성 단계 checkpoint를
  보관한다. 원본 문서 bundle은 복제하지 않으며 재요청한 입력 checksum을 대조한다.
- `POST /semantic-operations/{operation_id}`는 같은 입력·principal에서 재개한다. 같은 ID에 다른 입력은
  거절한다. `GET`은 상태 조회다. 프로세스 간 advisory lock으로 같은 operation의 작성을 직렬화하며,
  생성 직후 응답이 유실되어도 기존 version·Stable Key·프로파일 내용과 대조해 중복 작성하지 않는다.
- Data DB lease와 heartbeat가 상위 실행의 동시 수행을 막는다. 작업자가 종료되면 lease 만료 후
  이어갈 수 있고 이전 lease의 쓰기는 거절한다. 재시도는 이미 저장한 추출 결과를 재사용한다.
- 최종 문서 처리의 기존 Data DB 완료 transaction은 모든 최종 산출물 저장 성공 후에만 기록한다.
  같은 workflow_id의 완료 재실행은 저장된 결과를 반환한다. 입력·처리 코드·작성 API 경로가 바뀌면
  새 workflow_id를 사용한다. 다른 표준의 결과로 같은 immutable 경로를 덮어쓰지 않는다.

선택적 SQL 회귀는 운영과 분리한 `TEORIA_TEST_APP_DATABASE_URL`과
`TEORIA_TEST_PIPELINE_DATABASE_URL`을 사용한다. 프로젝트 간 HTTP 계약 검사는 루트
`backend/tests/integration/test_goods_normalization_contract.py`가 소유한다. 통제된 모델 응답·체크포인트를
사용하는 통합 테스트와 실제 문서의 Codex 품질 평가·운영 배포 성공은 구분한다.

프로파일의 공개 작성 경계는 `NormalizationProfileService`, 의미 판정의 내구성 실행은
`SemanticOperationService`다. 저장소의 내부 context·DB URL에 의존하는 대신 공개 서비스 메서드를 사용한다.
승인 시 Ontology 서비스의 게시 artifact 조회와 version 잠금을 같은 transaction에 연결한다.
