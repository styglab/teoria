# 정규화 프로파일

프로파일은 **게시된 Ontology 개념을 규격서에 적용하는 규칙**이다.
원문 표현·대상·역할·범위·단위 정책을 고정하고, 승인한 패키지를 Pipeline에 전달한다.

## 사전과 무엇이 다른가

| 구분 | 역할 |
|---|---|
| [사전](../platform/goods_dictionary.md) | 원문 표현·로컬 표준 정의·승인 매핑 관리 |
| 프로파일 | 특정 Published Ontology를 참조하는 문서 적용 규칙 |
| 추출 결과 | 특정 규격서의 대상·관계·값·조건·근거 |

사전의 승인 개념 ID, 프로파일이 참조하는 Ontology Stable Concept ID, 문서 내 로컬 ID는 다르다.
현재 goods 모델은 Draft이므로 이 문서의 프로파일 기반을 현재 물품 모델에 이미 게시·적용했다고 해석하지 않는다.

## 작성과 사용

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
형식 예시인 [서버 메모리 템플릿](examples/server_memory_profile.json)은 계약 테스트에서도 사용하는 입력이다.
현재 운영 서버 모델이나 사용 가능한 물품 프로파일을 뜻하지 않는다.

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
