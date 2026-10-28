# 물품 사전: 원문 표현·표준 정의·매핑

사전은 **원문에 나온 말**, **공통 의미의 정의**, **둘을 연결한 판정**을 따로 저장한다.
문서의 ‘정격출력 3 kW 이상’을 읽는 예시는 다음과 같다.

| 층 | 저장하는 것 | 예시 |
|---|---|---|
| 원문 표현 | 원문 명칭·소유 대상·근거 | 인버터의 ‘정격출력’ |
| 표준 정의 | 공통 명칭·정의·자료형·단위·적용 대상·개정 | `inverter_rated_output_power`, 숫자형, 전력, W·kW |
| 의미 매핑 | 원문 표현과 정의 개정의 관계·범위·근거·승인 | 이 문맥의 ‘정격출력’은 해당 표준 정의와 동등 |

**3 kW 이상이라는 개별 값과 구성 트리는 사전이 아니라 문서별 추출 결과에 저장한다.**
원문 명칭을 등록했다고 표준 의미가 확정되는 것은 아니다.

## 파이프라인에서 무엇을 조회하나

```text
원문 표현 조회·등록 → 승인 매핑 조회 → 표준 정의 연결 → 값·단위 검증
```

06 단계에서 인증된 Admin API를 사용하고 07 결과에 연결을 보존한다.
원문 표현이 없으면 근거를 검사해 등록한다. 문서처리 모드에서는 표준 매핑이 없으면 원문만 보존하고 미해결로 남긴다.
표준관리 모드에서는 미해결 표현을 Codex로 판단하고 별도 호출로 재검증한다. 기존 승인 정의에 동등 매핑하거나
새 로컬 정의를 작성한다. 물품 유형 승인 후 속성을 처리하며, 불확실·충돌·근거 부족은 보류한다.
`dictionary_meaning_auto_approve`는 기본 `true`다. 검증을 통과한 정의·매핑은 Admin API에서 자동 승인하고
같은 실행에 적용한다. `false`는 제안만 저장한다. 로컬 정의의 승인은 국가 표준 인증이나 Published Ontology 게시가 아니다.
판단과 재검증 결과는 `dictionary_semantic_decisions.json`, 인증 주체의 승인 이력은 Application DB에 남긴다.
이름 유사도·원문 존재만으로 동의어를 승인하지 않는다. 사전 전용 Flow는 없다.

## 자동 처리와 보류

| 대상 | 자동 처리 조건 | 미해결 처리 |
|---|---|---|
| 원문 등록 | `source_literal_v1`: 원본 해시·위치·인용·명칭과 최소 정의 일치 | 근거 부족·정의 충돌은 보류 |
| 표준 개념 재사용 | 승인된 `equivalent` 매핑, 승인 정의 개정, 분류·소유 유형 범위 일치 | 매핑 없음은 unresolved, 복수 대상 충돌은 held |
| 수치 검증 | 단일 number의 유한 Decimal 값·허용 단위 확인 | 다른 값 형태는 unchecked, 잘못된 값·단위는 검증 사유 표시 |

`related`는 동등 연결이 아니다. 특성은 소유 물품 유형도 해석되고 적용 범위와 일치해야 한다.
W·kW의 허용 여부를 검사하지만 현재 이 사전 경로에서 환산하지 않는다.
`canonical_unit`은 정의의 기준 단위이며 `typed_value`는 원문 단위를 유지한다.

원문 속성명이 없는 관찰을 내부 영문 후보명으로 등록하지 않는다. 물품의 등록 근거는 그 엔티티가 가리킨 원문 위치를 사용한다.
원문 등록 승인은 해당 문서의 모든 물품·구성·요구조건이나 Published Ontology의 승인이 아니다.

## 정의·매핑을 관리하는 방법

표준 정의는 불변 개정으로 제안하고 `draft → approved/rejected`, 승인 후 `deprecated`로 관리한다.
내용 변경은 새 개정이다. 새 개정을 승인하면 이전 승인 개정은 중단되고 이전 개정의 매핑은 자동 적용에서 제외된다.
새 개정에 맞춰 다시 매핑을 제안·승인한다. 판정 주체는 인증 principal이며 사람 검토로 가정하지 않는다.

매핑은 실제 저장된 원문 등록 근거를 사용한다. 유형끼리, 특성끼리 연결하고 판정 사유를 남긴다.
분류 범위가 있으면 그 값이 일치해야 한다. 범위가 null이면 분류에 제한되지 않는다는 명시적 정책이므로 신중히 승인한다.
최초 로컬 정의의 작성 예시는 [인버터 입력](../../backend/authoring/goods_dictionary/inverter_seed.json)이다.
국가 표준 인증이나 Published Ontology를 뜻하지 않는다.

## API와 저장 위치

기준 경로는 `/v1/admin/goods/dictionary`다. bearer 인증과 `ontology_owner` 역할이 필요하다.

| 작업 | 경로 |
|---|---|
| 원문 표현 조회 | `GET /entries` |
| 원문 후보 등록·결과 조회 | `POST/GET /operations/{operation_id}` |
| 정의 제안·조회 | `POST/GET /concepts` |
| 매핑 제안·조회 | `POST/GET /mappings` |
| 정의/매핑 판정 | `POST /concept/{revision_id}/decisions`, `POST /mapping/{mapping_id}/decisions` |
| 판정 이력 | `GET /concept/{revision_id}/audit`, `GET /mapping/{mapping_id}/audit` |
| 승인 매핑 해석 | `POST /resolve` |

판정은 `action: approve|reject|deprecate`와 `rationale`를 제출한다. 본문 actor/reviewer는 받지 않는다.
Application DB의 `goods.dictionary_entries`, `concept_revisions`, `concept_mappings`와 감사 테이블이 소유한다.
원문·문서별 관찰·근거 본문은 파일/S3, 실행·참조는 Data DB에 둔다.

## 결과에서 확인할 필드

| 필드 | 뜻 |
|---|---|
| `source_term_ref` | 원문 표현 등록 ID |
| `dictionary_concept_ref` | 로컬 표준 개념 ID |
| `definition_revision_id`, `meaning_mapping_ids` | 적용한 정의 개정·매핑 |
| `meaning_status` | resolved / unresolved / held |
| `value_validation` | 값·단위 검증 결과 |

`source_term_alignment.json`의 `concept_alignment`와 `normalized.json`의 `dictionary_meanings`에서 확인한다.
이 ID는 Ontology의 `type_ref`·`characteristic_ref`를 대신하지 않는다. 전용 사전 편집 화면은 아직 없다.
실제 항목·건수는 API에서 확인하고, 특정 시점의 수치는 [검증 기록](../verification/index.md)에 둔다.

## 여러 규격서로 초기 사전 구축·개정하기

`dictionary-maintain`은 기존 추출 결과에 대해 06의 사전 작성을 일괄 수행하는 관리 명령이다.
별도의 문서 처리 모드나 새 Prefect Flow가 아니다. 원문 파싱·02–05 추출을 반복하지 않는다.

```bash
uv run --project backend --locked --group orchestration \
  teoria-pipelines specification dictionary-maintain --manifest /data/dictionary_batch.json
```

입력 예시에서 URI·checksum은 실제 `extracted.json`의 값으로 바꾼다.

```json
{
  "batch_id": "goods_initial_dictionary_01",
  "artifact_root": "file:///app/specification_artifacts",
  "model": "gpt-6.1-sol",
  "auto_apply": true,
  "extractions": [
    {"uri": "file:///data/run_a/extracted.json", "sha256": "실제 파일의 SHA256"},
    {"uri": "file:///data/run_b/extracted.json", "sha256": "실제 파일의 SHA256"}
  ],
  "validation_extractions": []
}
```

- 원문 해시·분류별로 중복을 제거하고, 실행 사이에 겹치는 문서 ID를 분리한다. 분류가 없는 샘플은 null을 유지한다.
- Codex가 물품 유형 표현들을 먼저 함께 보고, 이어 승인 예정인 물품 유형을 대상으로 속성 표현들을 함께 본다.
- 같은 의미는 기존 정의와 연결하고, 정의 보완은 같은 Stable ID의 새 개정으로 작성한다.
  의미·값 유형·물리량 차원이 달라지는 경우에는 새 개념으로 분리한다.
- `retire_concept_ids`와 표현별 재매핑으로 개념의 병합·분리를 표현한다. 기존 개념이 입력에 없다는 이유로 중단하지 않는다.
- 별도 Codex 호출로 변경안을 재검증한다. 구축 문서의 검토 실패는 사유를 전달해 한 번 수정·재검증하며, 별도 검증 문서로 수정 방향을 정하지 않는다.
- 서버가 변경 영향·매핑 누락·소유 관계·충돌을 검사하고, 의미가 바뀌는 표현의 과거 원문 해시가 검토 범위에서 빠지면 보류한다.
- 영향받는 모든 기존 매핑과 소유 대상에 의존하는 매핑을 재판정해야 한다. 다른 분류의 영향 표현도 필요하면 그 추출 결과를 함께 입력한다.
- 기준 사전 checksum이 달라지면 적용을 거부한다. 검증한 정의 개정·기존 매핑 중단·새 매핑 승인·감사 이력은 한 transaction으로 반영한다.
  일부만 적용되는 중간 상태를 남기지 않으며 같은 작업 ID·같은 요청의 재전송은 결과를 재사용한다.
- `auto_apply: false`는 변경안·검증·영향 보고서만 저장한다. 이 경로에서는 표준 정의·매핑을 쓰지 않는다.
  원문 표현 등록은 수행한다. 같은 batch_id는 불변 산출물의 식별자이므로 새 분석에는 새 ID를 사용한다.

처리량은 입력 추출 파일 최대 1,000개, 원문 표현 최대 5,000개와 모델 문맥 예산으로 제한한다.
한도를 넘으면 임의로 문서를 자르지 않고 분류·물품군별 배치 분할을 요구한다.
대표 표본은 분류·공급자·양식·시기의 다양성을 고려해 선정한다. 단순 빈도를 독립 근거 수로 보지 않는다.

`validation_extractions`는 변경안이 동결된 뒤에만 검증에 사용한다. 원문 해시와 명시한 `template_family`가
구축 입력과 겹치면 거부한다. 별도 검증이 없으면 development_only로 기록한다.
이 모델 재검증을 독립 정답셋 평가나 정확도 향상의 증거로 표시하지 않는다.

## 버전 고정과 변경 영향

관리 산출물은 `<artifact_root>/specification_processing/dictionary_maintenance/<batch_id>/`에 저장한다.

| 파일 | 내용 |
|---|---|
| `manifest.json`, `baseline.json` | 입력·설정과 변경 전 사전 |
| `source_groups.json` | 문서 간 원문 표현 묶음과 등록 결과 |
| `item_type_plan.json`, `characteristic_plan.json` | 유형·속성별 정의·개정·재매핑·보류 판단 |
| `*_check.json`, `validation_check.json` | 별도 재검증·선택한 별도 문서 검증 |
| `changeset.json` | 적용 전 동결한 변경안 |
| `impact.json` | 표현·분류별 전후 해석과 관련 등록 작업·문서·원문 해시 |
| `observation_validation.json` | 구축·별도 검증 문서의 값 유형·단위 정책 검사 |
| `dictionary_standard.json` | 적용 transaction에서 확정한 사전 스냅샷 |
| `result.json`, `index.md` | 적용/제안/보류 상태와 사람이 읽는 보고서 |

문서처리 입력에서 `dictionary_standard: {"uri": "...", "sha256": "..."}`를 지정하면
해당 스냅샷의 정의·매핑으로 해석한다. 현재 사전이 개정돼도 같은 입력·같은 사전 버전을 재사용할 수 있다.
지정하지 않은 기존 입력은 기존처럼 현재 승인 매핑을 조회한다. 고정 프로파일의 `standard`와 사전 스냅샷은 별도 입력이다.
결과에는 `dictionary_standard.json` 복사본과 `dictionary_meanings.snapshot_checksum`이 남는다.

기존 보고서·normalized.json은 사전 개정으로 덮어쓰지 않는다. 영향 보고서의 원문·등록 작업을 기준으로
새 run_id에서 기존 extraction_checkpoint와 새 dictionary_standard를 지정해 재처리한다.
여기서 버전은 로컬 사전의 내용 checksum이다. Published Ontology 버전이나 국가 표준의 제정 번호가 아니다.

추가 Admin API는 `GET /snapshot`, `POST /maintenance-preview`, `POST /maintenance/{operation_id}`다.
operation_id는 `maintenance_` 접두사를 사용하며 인증 주체를 적용·감사 주체로 기록한다.

기존 표준관리 Flow의 06 단계에서 같은 기능을 실행하려면 manifest에 다음을 지정한다.

```json
{
  "dictionary_reconcile": true,
  "model_timeout_seconds": 600,
  "dictionary_corpus": [
    {"uri": "file:///data/previous_run/extracted.json", "sha256": "실제 파일의 SHA256"}
  ],
  "dictionary_validation_corpus": []
}
```

현재 실행의 extracted.json은 자동으로 포함한다. Codex 모델을 명시해야 하며,
`dictionary_meaning_auto_approve`가 일괄 적용 여부를 제어한다.
이 경로가 보류되면 문서별 단건 작성으로 우회해 자동 승인하지 않는다.
적용에 성공하면 확정한 사전 스냅샷으로 현재 문서도 해석한다.
기존 Prefect 배포에 이 manifest를 사용해 반복 실행할 수 있으며 새 별도 Flow·기본 스케줄을 추가하지 않는다.
