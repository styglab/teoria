# 물품 원문 표현·표준 정의·의미 매핑

원문 표현을 등록하는 것과 표준 의미를 정의하는 것은 별개다. 현재 세 층은 모두 Application DB에
별도 저장하며 문서별 관찰·수량·관계·규격 값·근거 본문은 파일/S3에 보존한다.
Published Ontology나 OpenMetadata를 이 API로 게시·수정하지 않는다.

| 층 | 저장소 | 의미 |
|---|---|---|
| 원문 표현 | goods.dictionary_entries | 원문 명칭·소유 유형·값 종류의 근거 기반 등록 |
| 표준 정의 | goods.concept_revisions | 안정적인 concept_id와 개정별 revision_id, 정의·자료형·적용 유형·단위 정책 |
| 의미 매핑 | goods.concept_mappings | 원문 등록과 특정 정의 개정 사이의 동등/관련 판정·범위·근거·생명주기 |

초기 원문 등록은 45개이며 네 규격서 전체 실행 후 현재 319개다. 이를 표준 개념으로 일괄 승격하지 않았다. 최초 로컬 표준 정의는 인버터 유형과
인버터 정격출력 두 개다. 국가 표준 인증 또는 Published Ontology라는 의미가 아니다.
작성 입력은 `backend/authoring/goods_dictionary/inverter_seed.json`이다.
인버터 정의는 미국 에너지부의 DC→AC 변환 설명을 참고했고, 전력 단위는 BIPM SI 문서를 참고했다.
정격출력은 샘플 차량 규격서의 해당 특성을 모델링한 로컬 업무 정의다. 원문에 없는 운전 조건이나
제품의 실제 성능을 추정하지 않는다. 다른 장치의 소비 전력·최대 출력과 자동 병합하지 않는다.

## 작성·승인 API

모든 경로는 `/v1/admin/goods/dictionary` 아래다. bearer 인증과 ontology_owner 역할이 필요하다.
변경 주체는 인증 principal에서 가져온다. 요청 본문 actor/reviewer를 받지 않는다.

| 동작 | 경로 |
|---|---|
| 불변 정의 개정 제안 / 조회 | POST /concepts · GET /concepts |
| 원문-정의 매핑 제안 / 조회 | POST /mappings · GET /mappings |
| 정의 판정 | POST /concept/{revision_id}/decisions |
| 매핑 판정 | POST /mapping/{mapping_id}/decisions |
| 판정 감사 | GET /concept/{revision_id}/audit · GET /mapping/{mapping_id}/audit |
| 승인 매핑 해석 | POST /resolve |

판정 본문은 `action: approve|reject|deprecate`, `rationale`이다. draft에서 승인/거절할 수 있고,
승인 후에는 폐기할 수 있다. 거절·폐기한 개정은 재승인하지 않고 새 제안을 작성한다.
동일 정의의 재요청은 최신 draft/approved 개정을 재사용한다. 내용 변경은 새 개정을 생성한다.
새 개정 승인 시 기존 승인 개정은 deprecated가 되며, 이전 개정을 가리킨 매핑은 자동 적용에서 제외된다.
해당 매핑을 새 개정에 다시 제안·승인해야 한다. 승인 판정을 사람 검토라고 가정하지 않는다.
최초 입력의 rationale에는 inverter_seed_v1 자동 정책 판정임을 명시했다.

매핑은 원문 등록의 실제 저장 근거를 복사하며 사용자가 새 근거를 주장하는 입력은 받지 않는다.
유형끼리, 특성끼리 연결한다. 특성에는 승인된 적용 물품 유형과 owner_concept_id가 필요하다.
분류 범위를 지정하면 10자리 분류값이 일치할 때만 재사용한다. null은 해당 매핑이 분류에 제한되지
않는다는 명시적 정책이므로, 문맥이 다양한 표현에는 분류 범위와 서로 다른 정의를 사용해야 한다.

## 기존 처리 단계에서 사용

별도 모드나 Flow는 없다. 기존 06 단계는 원문을 등록한 뒤 인증된 Admin HTTP /resolve를 호출한다.
07 표준 적용 결과에는 `dictionary_meanings`로 승인 매핑 결과를 함께 보관한다.
기존 Published 프로파일 적용과 이 사전의 ID는 서로 대체하지 않는다.

- `source_term_ref: source_term:<uuid>`: 원문 표현 등록 ID.
- `dictionary_concept_ref: dictionary_concept:<uuid>`: 안정적인 로컬 표준 개념 ID.
- `definition_revision_id`, `meaning_mapping_ids`: 적용한 불변 정의 개정과 판정 추적.
- `meaning_status`: resolved / unresolved / held. 복수 승인 대상은 held다.
- `value_validation`: number 특성의 유한 Decimal 값과 허용 단위를 검사한다. 원문 값은 유지한다.

자동 재사용은 승인된 equivalent 매핑과 승인된 정의에 한정한다. related는 자동 동등 처리하지 않는다.
특성은 소유 원문 유형도 하나의 표준 유형으로 해석되고 그 유형이 특성의 적용 범위와 일치해야 한다.
이름 유사도나 원문 존재만으로 표준 의미를 승인하지 않는다.

현재 수치 검증은 단일 number 값에 한정한다. 범위·허용차 등은 unchecked로 남긴다.
W와 kW는 허용 여부만 검사하고 환산하지 않는다. canonical_unit은 정의의 기준 단위이며,
`typed_value`는 원문 단위를 유지한다. `3 kW 이상`은 숫자 3·단위 kW·원문 연산자 이상을 보존한다.
이 결과는 실제 성능 입증·제품 식별 병합·물품 Ontology 게시를 뜻하지 않는다.

확인용 결과는 실행 산출물 `source_term_alignment.json`의 concept_alignment와
`normalized.json`의 dictionary_meanings에 있다. 전용 사전 편집 화면은 아직 없다.

전체 샘플 처리에서 원문 속성명이 없는 관찰의 내부 영문 후보명을 등록 대상으로 보내지 않도록 수정했다. 관찰 자체는 보존한다. 물품 표현의 근거는 해당 엔티티의 원문 위치를 사용한다. [실제 실행·품질 점검](../verification/goods_four_sample_pipeline_2026_10_27.md)을 참고한다.
