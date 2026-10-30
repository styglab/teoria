# 물품 표준 정의·매핑 적용 검증

2026-10-27 원문 표현 등록과 표준 정의·범위별 의미 매핑을 별도 구현했다.
원문 등록 45개는 유지하고, 인버터 유형과 인버터 정격출력의 로컬 정의 2개 및 매핑 2개를 추가했다.
정의 작성 입력은 backend/authoring/goods_dictionary/inverter_seed.json이다.
인증된 Admin API에서 draft 생성 후 inverter_seed_v1 자동 정책 판정을 기록해 승인했다.
사람 검토나 국가 표준 인증으로 표시하지 않는다. Published Ontology·Runtime artifact는 변경하지 않았다.

Application migration 021_goods_meaning_dictionary.sql을 실제 적용했다.
작성·조회·판정·감사·해석 API와 처리 Worker를 로컬 Compose 환경에 반영했다.
별도 Flow는 추가하지 않았다. 기존 standard_management에서 06 등록·해석, 07 적용을 사용한다.

실행 run_id: goods_meaning_dictionary_20261027_01
Prefect run: 8461a8b5-5961-476a-8d78-18f54db4fef8

- 기존 원문 표현 2개 재사용. 표준 개념 매핑 resolved 2개.
- 실제 동물 차량 원문에 근거를 둔 인버터·정격출력 관찰 checkpoint를 사용했다.
- 수동 작성된 일부 관찰을 이용한 통합 검증이며 새 LLM 추출이나 전체 규격서 정확도 평가는 아니다.
- normalized.json의 dictionary_meanings에 로컬 개념 ID·정의 개정 ID·매핑 ID가 저장됐다.
- 값 3·단위 kW·연산 gte·문서 proposed 유지, number 및 허용 단위 검증 valid.
- W로 환산하지 않았으며 기존 Ontology characteristic_ref/type_ref를 채우지 않았다.
- 원문 기반 기존 표준 경로의 미정렬 항목 때문에 실행 결과는 partial이다. Prefect 실행 자체는 Completed다.

전체 backend·documentation 테스트: 671 passed, 45 skipped. Compose config 및 diff 공백 검사 통과.
테스트에는 승인 전 미적용, 분류 범위 불일치, 소유 유형 미해석, 관련 관계 미적용,
동등 매핑 충돌 보류, 정의 개정 후 이전 매핑 미적용, 인증 actor 및 숫자·단위 검증을 포함한다.

로컬 결과:
.artifacts/goods_meaning_dictionary_20261027/normalized.json
.artifacts/goods_meaning_dictionary_20261027/source_term_alignment.json
.artifacts/goods_meaning_dictionary_20261027/seed_result.json
.artifacts/goods_meaning_dictionary_20261027/live_run.log
.artifacts/goods_meaning_dictionary_20261027/tests.log

나머지 원문 표현 43개에 대한 표준 의미 확정·동의어 정렬은 완료하지 않았다.
다른 물품군·범위/허용차 값·단위 환산·제품 식별·검색 색인 검증은 후속 범위다.
