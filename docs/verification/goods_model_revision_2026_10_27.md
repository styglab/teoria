# 물품 분류·유형·구성 모델 Draft 보완 검증

일자: 2026-10-27. 기존 초기화 이후 `goods` 1.0.0 Draft를 수정했다.
Published version·Runtime bundle·원본 문서·이전 applied 이력은 변경하지 않았다.

## 변경

- 분류체계 판본·분류항목·출처별 분류 판정을 추가했다. 원문 코드 하나를 물품의 확정 분류로 저장하던 필드를 제거했다.
- 물품 유형·표준 특성의 업무 사전 항목을 정의하고 명세와 관계로 연결했다.
- 물품과 구성품은 동일한 규격 물품 항목으로 표현한다. 구성 명세의 상위·하위 대상은 각각 하나이며 수량·단위·조건·범위·근거를 보존한다.
- 서비스 항목·대상·조건·근거를 추가해 설정·연동시험을 물리 구성품과 구별했다.
- 문자열 `item_type_concept_id`·`property_concept_id`를 사전 항목과의 명시적 관계로 교체했다.
- 원문 2건의 분류 표제 불일치·구성 범위·전체/개별 메모리·서비스 사례를 설계 문서에 기록했다.

## 실제 반영

- Draft ID: `6bf176a6-913a-4b05-9a95-b8bbf6ba7866`.
- 인증된 Admin HTTP API로 기존 Draft를 수정했다. 기존 객체·관계와 유지한 속성의 Stable Concept ID를 보존했다.
- 수정 전 schema snapshot: `.artifacts/specification_goods_model_revision_20261027/draft_before.json`.
- 요청별 변경 내역: 같은 디렉터리의 `result.json`. 인증정보는 포함하지 않는다.
- 최종 객체 12개·속성 72개·관계 27개. API 조회 결과를 작성 입력과 대조했다.
- API validation: `valid`, diagnostics 0, incompatible bindings 0.
- nginx를 통한 관리 화면 HTTP 200, 인증된 Draft 조회 HTTP 200. 브라우저 시각 검증은 수행하지 않았다.
- 관리 화면: `http://localhost:8081/admin/semantic-model/ontology?version=6bf176a6-913a-4b05-9a95-b8bbf6ba7866`.

## 검사

```bash
uv run --project backend --locked --all-extras --group orchestration pytest backend/tests tests/documentation -q
uv run --project backend --locked --extra api teoria validate backend/contracts/runtime
uv run --project backend --locked --extra api teoria ontology-migration-report \
  --registries backend/contracts/runtime \
  --manifest backend/authoring/ontology_migrations/pending/2026_10_goods_classification_composition/ontology_v2.yaml
docker compose -f deploy/compose/compose.yaml config --quiet
```

- 전체 테스트: 601 passed, 45 skipped, Starlette deprecation warning 1.
- Registry validation: Source·Runtime contract·Mapping·Capability 각 0, data types 11, value sets 15.
- migration report: valid. 현재 legacy Runtime YAML Object가 없어 이관 대상 0개, Published target 검증은 해당 없음.
- Compose config와 이번 변경 파일의 `git diff --check` 통과.
- 저장소 전체 diff 검사는 다른 동시 작업의 `metadata_management/intelligence/asset_assessment/prompts.py` 공백을 보고했다. 해당 파일은 수정하지 않았다.

## 검증 범위

현재 결과는 의미 schema의 Draft 보완이다. 물품 유형·특성·공식 분류의 실제 사전 데이터 적재,
문서 인스턴스의 참조·순환·단위 검사, 승인 API 연결, 새 프로파일·재추출·조회는 후속 구현이다.
작성 입력의 구조 검증과 실제 인스턴스 검증을 혼용하지 않는다. 승인·게시나 새 Runtime 배포는 수행하지 않았다.

## 샘플 4개 재제안 구현

같은 날 후속 요청에 따라 동일 Draft를 객체 17개·속성 93개·관계 50개로 보완했다.
납품 범위·범위 항목 역할·규격 적용 문맥·제출자료·물품 연계 명세를 추가하고,
구조화한 값·조건·기준 사건·표준 참조·검수 대상 관계를 정의했다.
기존 객체·속성·관계의 식별자를 유지했으며 이번 보완에서 삭제한 개념은 없다.

- 인증된 Admin API 반영·작성 입력 대조·validation valid, diagnostics 0.
- nginx 관리 화면과 Draft 조회 HTTP 200. 상태 draft, Published 모델·Runtime bundle 변경 없음.
- 작업 전 snapshot과 반영 결과: `.artifacts/goods_four_sample_implementation_20261027/`의 `draft_before.json`, `result.json`.
- 순수 문서 그래프 계약: `goods_normalization/contracts/specification_graph.py`.
- 대표 제안 그래프: `backend/authoring/specification_examples/four_sample_graphs.yaml`.
- 원본 4개 해시 유지, 예시에 포함한 텍스트 근거 58개 모두 해당 native_ref의 원문 부분문자열과 일치.
- 네 그래프 모두 분류 주장 0개. 외부 분류 metadata를 생성하지 않았다.
- 구성 순환·자기 포함·누락 대상·근거 참조·잘못된 대상 종류·공급 제외와의 충돌·검수 참조·수치/조건 형식·JSON 왕복을 검사했다.
- 전체 backend·문서 검사: 633 passed, 45 skipped, 기존 Starlette deprecation warning 1.
- Registry validate·명시적 migration report·Compose config·이번 변경 파일의 diff 공백 검사 통과.

```bash
uv run --project backend --locked --extra api teoria-pipelines specification validate-graph \
  --manifest backend/authoring/specification_examples/four_sample_graphs.yaml
uv run --project backend --locked --extra api teoria ontology-migration-report \
  --registries backend/contracts/runtime \
  --manifest backend/authoring/ontology_migrations/pending/2026_10_goods_document_graph/ontology_v2.yaml
```

CLI는 구조·참조 검사만 수행한다. 네 예시는 원문을 읽어 작성한 부분 그래프이고 자동 추출 결과나
승인된 정답이 아니다. 새 계약의 자동 추출·프로파일 적용·DB·Runtime 연결은 구현하지 않았다.
기존 Flow와 NormalizationProfile의 분류 필수 계약은 유지한다. 분류 없는 새 그래프 검증과 혼용하지 않는다.
