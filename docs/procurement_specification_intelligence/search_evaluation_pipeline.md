# 규격서 검색 평가와 개선

저장된 실제 규격서를 공고 단위로 개발 80%·검증 20%로 분리하고, 원문 기반 질문·정답 생성,
구조화·검색 평가, Harness2 프롬프트 개선, 개발 관찰 기반 속성 사전 후보 생성을 실행한다.
소유 코드는 `pipelines/src/teoria_pipelines/domains/public_procurement/specification_intelligence/`다.
운영 Flow·Platform Ontology 게시와 연결하지 않는 독립 실험이다.

현재 우선순위는 [의미 분석 파이프라인](semantic_batch.md)의 소수 문서 자동 실행과
Semantic IR 평가를 먼저 검증하는 것이다. 기존 Harness2는 보존하며, 이 문서의 수치 QA
task를 엔티티·관계·규격 귀속 평가가 구현된 것으로 해석하지 않는다. Semantic IR 전용
task 연결은 해당 기준선을 확보한 뒤 진행한다. 목표 분할은 구축 80건·개발 검증 20건·
별도 최종 검증 20건이며, 기존 실험의 사후 80/20 분할을 새 최종 검증으로 재사용하지 않는다.

## 실행

Python 3.12와 인증된 `codex` CLI가 필요하다. 모델은 로컬 Codex 설정을 따르며
`--model`로 지정할 수 있다. Qwen이나 다른 모델로 자동 전환하지 않는다.
Harness2는 `pipelines/pyproject.toml`의 `specification-evaluation` 그룹과
`uv.lock`에 Git commit `1cfe254e8d25b15f37048c3730134686abe60335`로 고정했다.

```bash
uv run --locked --package teoria-pipelines --group specification-evaluation \
  python -m teoria_pipelines.domains.public_procurement.specification_intelligence.search_experiment \
  run \
  --manifest .artifacts/procurement_specifications/dictionary_rebuild_2026_10_20/source_manifest.json \
  --exposed .artifacts/procurement_specifications/server_dictionary_bootstrap_2026_10_20/sources.json \
  --output .artifacts/procurement_specifications/search_experiment_2026_10_20 \
  --concurrency 2 --tasks 2
```

같은 output으로 재실행하면 완료한 Codex 응답을 재사용한다. 입력·프롬프트가 달라진
캐시는 실패 처리한다. 다른 코퍼스나 실험 조건에는 새 output 경로를 사용한다.
`prepare`, `questions`, `adapt`, `evaluate`, `audit`로 단계를 개별 실행할 수도 있다.
검증을 이미 열었으면 그 결과로 같은 실험의 프롬프트를 재선정하지 않는다.

## 처리 순서와 결과

1. 원본·파싱 결과의 SHA-256을 검증한다. 동일 공고와 동일 원본 hash의 연결 그룹을
   같은 분할에 두고, 이미 검토한 원본은 개발용에 배정한다. 그룹 크기 때문에 정확한
   20%가 불가능하면 실제 비율을 기록한다. 충분한 미노출 그룹이 없으면 실패한다.
2. 분할과 원문 텍스트를 `corpus_freeze.json`으로 고정한다. 문서마다 수치 질문 5개와
   답할 수 없는 질문 1개를 Codex로 생성하고, 별도 Codex 호출로 원문과 대조한다.
   인용·수치 토큰을 코드로 검증한 뒤 `labels/`와 `freeze.json`에 고정한다.
3. 원문 전체를 구조화한 뒤 **원문 없이 추출 facts와 질문만** 주어 답하게 한다.
   질문을 보고 원문에서 다시 답을 추출하는 방식과 구분한다. 답은 추출된 fact와
   정확히 일치해야 한다. 누락·중복·잘못된 JSON도 분모에서 제외하지 않는다.
4. 개발 문서 일부에서 실제 Harness2 `run_domain(..., modes=("seq",))`을 실행한다.
   원문·실행 결과로 제안과 통합을 수행하며, 별도 `CodexProposer`가 Codex CLI를 호출한다.
   upstream의 channel 설정에는 `opencode`가 쓰이지만 실제 OpenCode 실행은 없다.
   실행 substrate는 Codex이며 응답 receipt에 실제 backend를 기록한다.
5. 각 통합 후보를 개발 전체에서 비교한다. baseline보다 통과 문항 수가 늘 때만
   선택하고 동점이면 baseline을 유지한다. `selection.json`에 프롬프트·개발 결과 hash를
   고정한다. `improvements.json`에는 개발 실패와 정답의 모호함을 구분한 수정 제안을 쓴다.
6. 선택안의 개발 facts를 원문과 다시 대조한다. 질문·정답을 주지 않는 별도 Codex 호출로
   소프트웨어·운영 수치 누락과 configuration/aggregation 혼동을 보완한다.
   `source_review/`에 원문 대조 결과와 수정 이유를 보존한다.
   이 개발 관찰만 의미 통합해 `dictionary/draft.json`에 속성 후보·원문 표현·
   관찰 그룹·보류 이유를 보존한다. 모든 그룹의 관찰 예시를 전달하며 처음 몇 개만으로
   의미를 확정하지 않는다. 사전 후보도 별도 Codex 검토를 거친다.
   검증 문서의 속성을 사전에 추가하지 않는다.
   이 후보는 승인된 표준 사전이나 완성된 Ontology가 아니며 QA 정답으로 사용하지 않는다.
   관찰 이름·단위·범위의 정확한 대응 또는 유일한 별칭만 후보 ID에 연결한다.
   값·부등호·설치/지원·전체/개별 범위는 보존하고, 모호하거나 새로 나온 이름은 원문과 함께
   미매핑 상태로 남긴다. 정규화 facts와 매핑 기록을 저장한다.
   선택 프롬프트·원문 대조·사전을 함께 적용한 개발 결과를 평가한 후 `pipeline_lock.json`으로
   프롬프트·사전·채점/정규화 코드·개발 결과를 고정한다.
   그다음 검증셋에서 baseline과 전체 선택 파이프라인을 각각 평가한다.
7. `report.json`에 개발/검증 수, 문항 수, 비교 결과와 개발 오류별 후속 수정 항목을 쓴다.
   검증 문서의 후보 속성 매핑률과 미매핑 수도 기록한다.
   선택한 프롬프트는 `selected_prompt.md`, 후보는 `harness2/candidates/`,
   원문별 응답과 사용량은 `predictions/` 및 각 `.receipt.json`에 남긴다.
   `question_answers.csv`에는 질문·정답·원문 인용과 개발 정답의 모호함/오류 의심 표시를
   함께 내보낸다. 의심 표시로 고정 정답이나 분모를 바꾸지는 않는다.

## 채점과 한계

현재 `v2_evidence_containment` 지표는 정답 원문 구간 포함·값/단위·부등호·설치/지원·
전체/개별 범위의 일치와,
별도 Codex 채점자의 장비 귀속·속성 의미 동치 판단을 모두 통과한 문항 비율이다.
동일한 source passage라도 다른 장비나 기본/부스트 속성을 답하면 의미 검토에서 실패한다.
다른 장비의 다른 원문 구간에서 같은 숫자를 찾은 답은 통과하지 않는다.
GHz/MHz와 명시적인 IEC 단위는 동치 변환하지만 TB를 임의로 1024GB로 바꾸지 않는다.
전체 속성 회수율, 관계 정확도, 공고 목록 검색의 정밀도·회수율은 이 지표로 측정하지 않는다.
귀속 이름의 동치도 모델 판단이며, 실제 장비 식별자의 결정론적 검증을 대신하지 않는다.
정답 구간을 포함하는 더 긴 원문 인용은 허용한다. 의미상 같은 다른 구간은 여전히
오답으로 셀 수 있으므로 결과를 일반적인 검색 정확도로 부르지 않는다.

정답은 Codex 생성·별도 Codex 검토를 거친 **silver label**이다. 사람 검수 완료나
모델 간 독립 정답이 아니다. 원문 인용 존재 검사는 의미 정답을 증명하지 않는다.
기존 코퍼스를 사후 분리했으므로 신규 유입 문서에 대한 전향적 평가라고 주장하지 않는다.
공고·원본 hash 중복은 차단하지만 문구가 조금 다른 동일 템플릿의 누출은 별도 감사 전이다.

Harness2에는 개발 원문과 실행 결과만 직렬화해 주고, 도구를 사용하지 않는 Codex
호출로 개선하게 한다. 검증 정답과 채점 결과는 proposer context에 전달하지 않는다.
이 실험의 편집 표면은 `AGENTS.md` 프롬프트로 제한한다. 임의 Python 코드를 자동 실행하거나
저장소에 적용하지 않는다. 코드 수정은 개발 중 확인한 실패를 회귀 테스트로 재현해 반영한다.
경험 기록이 `NO_ENTRY`이면 지속 학습이나 다음 문서 재사용이 있었다고 집계하지 않는다.

전체 설계 배경은 [초기 사전 구축](dictionary_building_pipeline.md),
기존 과분리 문제는 [속성 사전의 구조](attribute_registry.md)를 참고한다.

구현 근거: [Harness2](https://github.com/google-research/harness2),
[Codex 비대화형 실행](https://learn.chatgpt.com/docs/non-interactive-mode).
