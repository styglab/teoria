> 초기 별도 실행 이력이다. 별도 모드·Flow는 기존 06/07 단계로 통합한다. 45개는 표준 개념이 아닌 원문 표현 등록이며 현재 연결 필드는 source_term_ref다.

# 물품 사전 자동 승인·재사용 검증

2026-10-27 사용자 요청에 따라 초기 물품 사전의 자동 승인 경로를 구현하고 실제 환경에서 실행했다.

## 구현 범위

- 작성·검토·저장·감사: `features/semantic_modeling/goods_dictionary/`.
- 공개 HTTP 계약: 같은 패키지의 `contracts.py`. Pipeline은 이 계약과 인증된 Admin HTTP API만 사용한다.
- 원문 후보 수집: `specification_processing/normalization/dictionary_candidates.py`.
- 실행: `SpecificationRun.mode = dictionary_authoring`, 기본 `dictionary_auto_approve = true`.
- 기존 파서·추출 관찰에서 시작하거나 `dictionary_graphs`로 기존 그래프를 선택한다. 기존 승인 프로파일·분류값을 요구하지 않는다.
- 그래프 입력은 원본을 다시 파싱해 SHA-256과 모든 인용 구절·위치를 대조한다.
- 승인 사전 ID를 `dictionary:<entry_id>`로 적용한 그래프를 저장한다. 문서 그래프 자체는 proposed를 유지한다.
- Application migration `020_goods_dictionary.sql`, Data migration `097_goods_dictionary_authoring.sql`을 새 파일로 추가·적용했다. 이전 migration은 수정하지 않았다.

## 자동 승인 정책

`source_literal_v1`은 원문에 실제 있는 명칭과 물품 유형별 특성의 최소 정의를 자동 승인한다.
문서 ID·SHA-256·parser snapshot 위치·구절·명칭을 확인하고, 특성의 소유 유형이 승인됐는지 검사한다.
같은 항목과 정의·값 종류는 ID를 재사용한다. 기존 정의와의 충돌·원문에 없는 이름·새 의미 해석은 보류한다.

자동 승인 단계의 `semantic_maturity`는 `source_literal`이다. 동의어·개념 동등성·외부 분류·단위 환산을
자동 확정한 완성 의미 사전이 아니다. 기본 정의는 ‘원문에서 A로 명시한 유형’, ‘A의 B에 관한 규격 특성’이다.
이름 유사도나 모델의 confidence만으로 authoritative 동등성을 만들지 않는다.

인증된 principal을 승인 주체로 기록하며, 실제 실행은 `system:admin` / `automatic_policy`로 저장됐다.
사람이 검토했다는 기록을 만들지 않았다. 요청 body의 actor 등 추가 필드는 거부한다.
후보 제안·승인·재사용·보류를 기록하고 operation ID와 입력 checksum으로 동일 요청을 재실행할 수 있다.

## 실제 실행

- 원본: `.artifacts/sample`의 기존 4개 규격서. 원본 해시를 유지했다.
- 그래프: `backend/authoring/specification_examples/four_sample_graphs.yaml`의 대표 제안 그래프.
- 유형 원문명과 특성 원문명을 별도 필드로 보존해 표시명과 구별했다.
- 실행 ID: `goods_dictionary_samples_20261027_01`.
- Prefect Flow: `procurement-goods-dictionary`.
- Flow run ID: `af025aa7-91e4-43a5-9675-8cc7973c7213`.
- [Prefect 실행 화면](http://localhost:8081/prefect/runs/flow-run/af025aa7-91e4-43a5-9675-8cc7973c7213).
- 분류정보 없이 기존 대표 그래프와 원본 재파싱으로 실행했다. **새 LLM 추출 실행은 아니다.**

| 항목 | 결과 |
|---|---:|
| 최초 후보 | 48 |
| 신규 자동 승인 | 45 |
| 같은 실행에서 재사용 | 1 |
| 보류 | 2 |
| 승인된 물품 유형 | 31 |
| 승인된 특성 | 14 |
| 적용 그래프의 유형 참조 | 32 |
| 적용 그래프의 특성 참조 | 14 |

보류는 `environment_targets`, `harmful_targets`다. 기존 그래프의 영문 특성 참조를
원문 특성명으로 확인할 수 없어 `name_not_in_source`로 남겼다. 임의 명칭을 만들어 승인하지 않았다.

같은 operation ID·같은 입력을 재호출하면 기존 결과를 반환하고 사전·이력을 중복 생성하지 않는다.
별도 operation ID `dictionary_goods_dictionary_samples_20261027_reuse`로 같은 후보를 다시 처리하면
신규 승인 0·재사용 46·보류 2이며 사전 항목 수는 45개로 유지됐다.

Prefect는 정상 완료했다. Data DB 실행 상태는 대표 제안 그래프를 사용했고 보류 2건이 있어 partial로 기록했다.
`new_extraction_performed: false`, `human_review_performed: false`를 결과에 명시했다.
실행 상태·문서별 결과·산출물 참조는 Data DB, 본문은 객체 저장소에 저장했다.

## 확인 위치

Application DB:

- `goods.dictionary_entries`: 승인 사전 45개.
- `goods.dictionary_operations`: 실행 식별·입력 checksum·결과.
- `goods.dictionary_decisions`: 후보별 판정과 근거.
- `goods.dictionary_events`: 제안·자동 승인·재사용·보류 이력.

인증된 Admin API:

```text
GET  /v1/admin/goods/dictionary/entries?kind=item_type
GET  /v1/admin/goods/dictionary/entries?kind=characteristic&query=정격출력
GET  /v1/admin/goods/dictionary/entries/{entry_id}/audit
GET  /v1/admin/goods/dictionary/operations/{operation_id}
POST /v1/admin/goods/dictionary/operations/{operation_id}
```

gateway 경유 시 `/admin-api`를 앞에 붙인다. 모든 경로는 bearer 인증과 ontology_owner 역할을 요구한다.
비인증 조회는 실제 401을 확인했다.

실제 응답의 로컬 사본은 `.artifacts/goods_dictionary_20261027/dictionary_entries.json`에 있다.
승인 ID를 적용한 그래프는 같은 폴더의 `dictionary_applied_graphs.json`이다.

영구 객체 저장 위치:

```text
/app/specification_artifacts/goods_dictionary_20261027/
  specification_processing/goods_dictionary_samples_20261027_01/
    sources/
    dictionary_candidates.json
    dictionary_bindings.json
    dictionary_applied_graphs.json
    index.md
```

## 운영 반영과 검사

- 현재 실행 중인 Admin·규격서 Worker 이미지를 기반으로 이번 변경 파일만 덧씌운 이미지를 적용했다.
- `teoria-platform-authoring:goods-dictionary-20261027`, `teoria-pipelines:goods-dictionary-20261027`.
- 기존 환경변수·볼륨·권한·pool·네트워크·resource 설정을 메모리에서 승계했다. 자격증명을 파일에 저장하지 않았다.
- 다른 작업의 latest 이미지 태그를 덮어쓰지 않았다. 다른 worker·Runtime 서비스·Published artifact는 변경하지 않았다.
- 운영 parser 패키지는 기존 worker 이미지에서 유지했다.
- Application DB 변경 전 백업: `backups/teoria/goods_dictionary_20261027/application_before.dump` 약 8.2MiB.
- 서비스 실행·실제 DB 반영·API 재사용·비인증 거부를 확인했다. 이미지 build만으로 운영 성공을 기록하지 않았다.
- 전체 검사: 655 passed, 45 skipped, 기존 Starlette deprecation warning 1. Compose config와 이번 변경 파일의 diff 공백 검사도 통과했다.

기존 goods Draft·평가 전용 의미 작성 auto-approve 제한·프로파일의 Published Ontology 조건은 유지한다.
새 사전 자동 승인과 Ontology schema의 게시·Runtime 배포를 혼용하지 않는다.

```bash
uv run --project backend --locked --all-extras --group orchestration pytest backend/tests tests/documentation -q
docker compose -f deploy/compose/compose.yaml config --quiet
```

전체 검사와 실제 실행 결과는 위 범위에 한정한다. 새 추출 품질·정식 동등성 판정·유사 검색·비교 품질을 검증한 결과는 아니다.
