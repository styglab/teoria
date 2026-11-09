# 물품 사전: 원문 표현과 Ontology 연결

사전은 문서에 나온 표현·소유 대상·원문 근거와 **게시된 Ontology 개념으로의 연결**을 관리한다.
물품 유형·속성의 업무 정의는 Ontology에서 작성·검토·게시한다. 사전에서 별도 표준 개념을 새로 만들지 않는다.

| 소유자 | 관리하는 것 | 예시 |
|---|---|---|
| Ontology | 유형·속성·관계, 자료형·물리량·기준 단위·허용 단위 | 인버터의 정격출력, decimal, power, W·kW |
| 원문 표현 사전 | 표현·문맥·근거와 승인된 개념 연결 | 인버터의 ‘정격 출력’ → 게시된 정격출력 개념 |
| 정규화 프로파일 | 대상 종류·역할·범위·관계 방향·허용 단위 변환 | 요구조건의 kW → W 변환 |
| 문서별 관찰 | 대상·값·연산자·원문 단위·위치 | 이 규격서는 3 kW 이상을 요구함 |

요구조건을 실제 장비의 실측값으로 바꾸지 않는다. 사전 연결만으로 값의 유효성·적용 범위를 확정하지 않는다.
새 표현에 대응하는 Ontology가 없어도 추출·원문 등록은 계속하고 미해결 후보를 남긴다.
게시 정의 조회는 Ontology의 공개 publication API가 소유하며 사전이 필수 관문이 아니다.
사전 snapshot은 게시 정의에 승인 표현 예시를 더한 고정 묶음이다. API·DB·파일이 공유하는
업무 의미를 사전별로 새로 정의하지 않는다.

## 파이프라인에서 무엇을 조회하나

```text
원문 표현 등록 → 승인된 Ontology 연결 조회 → 프로파일의 역할·범위·값·단위 검사
                  ↓ 연결이 없으면
             원문 근거를 포함한 검토 후보
```

기존 06 Task와 인증된 Admin HTTP API를 사용한다. 새 사전 전용 Flow나 Runtime 호출은 없다.
현재 API의 snapshot은 schema v2 `goods_expression_snapshot`이다. 표준관리에서는 실행 기준을 고정하고
`ontology_candidates.json`에 미해결 표현과 실제 원문 문맥을 저장한다. 후보는 Suggestion이며 자동 게시하지 않는다.
`dictionary_meaning_auto_approve`·`dictionary_reconcile`·재구축 옵션은 새 경로에서 독립 사전 정의의 작성·승인을 켜지 않는다.
원문 등록의 `dictionary_auto_approve`는 근거 등록 정책이며 의미 승인과 별개다.

## 정의·매핑을 관리하는 방법

1. Ontology에서 업무 의미를 Draft로 작성하고 검토·승인·게시한다.
2. **도메인 관리 → 물품 사전**에서 품목과 원문 표현을 선택한다.
3. 게시된 개념을 선택하고 분류·소유 유형·근거를 검토해 연결을 제안한다.
4. 연결을 승인한 후 해당 Ontology 버전을 참조하는 프로파일로 적용한다.

연결은 `draft → approved/rejected`, 승인 후 `deprecated` 생명주기를 따른다.
판정 주체는 인증 principal이며 요청 body의 actor는 허용하지 않는다.
새 연결·승인 시 게시 artifact의 checksum·개념 존재·종류·속성 소유자를 검증한다.
속성의 원문 소유 대상도 **같은 Ontology 버전**의 해당 유형으로 해석돼야 적용한다.
`related`는 자동 대체하지 않는다. 복수 대상·복수 버전은 보류한다.

분류 범위는 `classified`(명시 코드), `unclassified`(미분류 문맥), `independent`(명시적인 분류 독립 승인)다.
미분류는 모든 분류를 뜻하지 않는다. 문자열 유사도와 같은 단위만으로 동등성을 승인하지 않는다.

## API와 저장 위치

기준 경로는 `/v1/admin/goods/dictionary`이며 bearer 인증과 `ontology_owner` 역할이 필요하다.

| 작업 | 경로 |
|---|---|
| 품목 조회·서버 검색 | `GET /classifications`, `GET /catalog` |
| 원문 표현·근거 | `GET /entries`, `GET /entries/{entry_id}/evidence` |
| 원문 등록 | `POST/GET /operations/{operation_id}` |
| 게시된 개념 조회 | `GET /concepts`, `GET /catalog?kind=concept` |
| 연결 제안·조회 | `POST/GET /mappings` |
| 연결 판정·감사 | `POST /mapping/{mapping_id}/decisions`, `GET /mapping/{mapping_id}/audit` |
| 고정 사전·해석 | `GET /snapshot`, `POST /resolve` |
| 과거 정의·연결 | `GET /catalog?kind=concept|mapping&historical=true` |
| 과거 정의를 Draft로 제안 | `POST /ontology-draft-imports` |

새 매핑 입력은 `source_entry_id`, `ontology`(version_id·namespace·version·checksum),
`target_concept_id`(Stable Concept ID), `owner_concept_id`, 분류·범위·관계·근거다.
새 연결은 `goods.dictionary_ontology_mappings`에 참조와 판정만 저장한다.
사전 DB에 업무 정의 본문을 다시 저장하지 않는다. 원문 관찰 본문은 파일/S3에 유지한다.
`POST /concepts`, 로컬 개념 승인, `/maintenance/*`, `/reset-meanings`는 새 운영 서비스에서 거부한다.

## 버전 고정과 변경 영향

v2 snapshot에는 승인 판단에 사용한 Ontology 참조·게시 artifact 복사본·표현 연결·원문 표현 참조가 들어간다.
복사본은 실행을 위한 불변 projection이며 또 다른 작성 원장이 아니다. 외부 파일 SHA256과 내부 checksum,
중첩 Ontology checksum을 검증한다. `dictionary_standard` URI·SHA256으로 문서 재처리에 고정할 수 있다.

새 Ontology 버전을 게시해도 과거 연결을 새 버전에 자동 적용하지 않는다. 현재 조회에서는 재검토를 요구하며,
기존 고정 snapshot과 과거 문서 결과는 그대로 재현한다. 문서 관찰의 의미 참조는
`ontology_concept_ref`, `ontology`, `definition_revision_id`, `meaning_mapping_ids`로 보존한다.
값·단위 변환은 프로파일에서 수행한다. v2 경로에서는 별칭 규칙으로 미승인 표현 연결을 우회하지 않는다.

## 과거 사전 정의의 이관

과거 v1 정의·매핑·감사·산출물은 삭제하거나 ID를 바꾸지 않는다. `historical=true`로 조회한다.
웹의 **과거 사전 정의·연결 이력**에서 정의와 대상 Ontology Draft를 선택해 가져오기를 제안한다.

`POST /ontology-draft-imports`에는 `ontology_draft_id`, `revision_ids`, `rationale`을 제출한다.
선택 속성에 필요한 승인된 과거 소유 유형도 포함한다. 기존 대상 Draft의 같은 key가 다른 내용이면 거부한다.
숫자·텍스트 속성의 정의·물리량·기준/허용 단위는 보존하고, 복합 값 형태·다중 소유 유형은 수동 모델링으로 보류한다.
출처의 과거 revision·근거·인증 주체는 Ontology 작성 감사에 남긴다. 중간 중단 후 같은 Draft·같은 입력으로 재시도할 수 있다.
이 작업은 Draft 제안이며 게시·기존 개념과의 동등성 승인·표현 연결 승인을 수행하지 않는다.

기존 게시 개념과 같은 의미라면 새로 가져오기보다 해당 개념에 원문 표현을 연결한다.
v1 snapshot의 과거 해석은 호환 경로로 유지한다. 운영 데이터 일괄 이관·온톨로지 게시·배포는 별도 실행이다.

## FormatID의 규격서 처리 기준

처리 기준은 표준/프로파일과 사전 snapshot을 고정하는 실행 묶음이다. 새로운 업무 의미 원장이 아니다.
`/v1/admin/specification-processing/application-standards`에서 완료·부분 완료 실행의 등록 산출물과
현재 검토한 snapshot을 고정한다. 분류·참조·checksum을 검증하며 고정 적용에서 의미 작성은 허용하지 않는다.
추출용 초안의 고정은 Published Ontology나 독립 품질 검증을 의미하지 않는다.

## 품목별 조회와 공통 정의

품목코드는 원문 관찰과 연결의 적용 범위이며 개념의 전역 식별자가 아니다.
게시된 정의를 품목마다 복제하지 않는다. `classification=<10자리 코드|unclassified>`로 조회하고,
**온톨로지 정의 조회**에서 전체 게시 개념을 확인한다. 과거 미분류 관찰을 이름으로 역추정하지 않는다.
OpenMetadata Glossary는 자산 용어·거버넌스 의미의 기준을 유지하며 Teoria는 Semantic Binding으로 연결한다.

구조 판단의 참고는 Palantir의 [Shared Properties](https://www.palantir.com/docs/foundry/object-link-types/shared-property-overview),
[Value Types](https://www.palantir.com/docs/foundry/object-link-types/value-types-overview),
[W3C SKOS](https://www.w3.org/TR/skos-primer/)다. 표현 연결에 SKOS의 전역 동등성 추론을 자동 적용하지 않는다.
