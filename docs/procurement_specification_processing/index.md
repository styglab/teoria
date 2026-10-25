# 조달 규격서 처리

현재 실행 코드는 Pipelines의 `public_procurement/specification_processing/`가 소유한다.
[파이프라인 계약](pipeline.md)과 [개선 평가 사용법](evaluation.md)을 현재 기준으로 읽는다.
기존 로컬 표준은 미게시 초안이다. 새 프로파일은 별도 승인·내보내기를 거치며 문서 처리로 Ontology를 게시하지 않는다.
자동 공고 첨부 수집·참가자격 판단은 연결하지 않는다.

## 사용 시작하기

- 일반 문서 처리·표준 관리: [pipeline.md](pipeline.md)
- Ontology 기반 프로파일 작성·승인·적용: [normalization_profiles.md](normalization_profiles.md)
- 스킬을 통한 추출 개선·평가: [evaluation.md](evaluation.md)
- 실행 스킬: [improve-specification-processing](../../.agents/skills/improve_specification_processing/SKILL.md)

스킬은 원문 분석·오류 진단·코드 수정을 담당하고, 평가 CLI는 샘플링·실행·채점·비교·정리를 담당한다.
스킬을 계속 사용하며, 사용자가 매번 평가 명령을 순서대로 입력할 필요는 없다.

문서 경로는 `procurement_specification_intelligence/`에서 `procurement_specification_processing/`로
옮겼다. 기존 `extraction_pipeline.md`의 현재 계약은 `pipeline.md`와 `evaluation.md`로 나눴다.
폐기한 배치·검색 평가 안내는 `verification/retired_*.md`에 두며 현재 실행 절차로 사용하지 않는다.

## 이전 설계와 실험 기록

아래는 당시 관측과 설계이며 현재 구현의 품질을 입증하는 결과가 아니다. 과거 산출물의 존재·보관 상태는 개별 기록과 현재 파일을 구분한다.

| 문서 | 내용 | 상태 |
|---|---|---|
| [재귀 구성 트리 v3 검증](verification/composition_tree_pipeline_2026_10_22.md) | 계층 계약·구성 검토·네 샘플 재실행 | 실행 기록과 한계 |
| [품목 중심 v2 교체 검증](verification/item_first_pipeline_2026_10_22.md) | 교체 범위·테스트·실제 문서 실행 | 206개 테스트 통과, 서버 1건 needs_review 저장 |
| [서버 한 건 최소 추출](verification/server_single_extraction_2026_10_21.md) | 추론 1회로 대상·관계·규격 JSON 추출 후 원문 대조 | 52.802초 완료, 독립 정확도 평가 아님 |
| [다른 서버 규격서 3건 적용](verification/server_extraction_replication_2026_10_21.md) | 같은 지시·형식으로 HWPX·PDF·HWP 처리 및 원문 대조 | 2건 완료·1건 시간 초과, 과분리·범위 미해결 확인 |
| [재귀 구성 트리 분석 배치](verification/retired_semantic_batch.md) | v3 단계·부모 관계·속성 귀속·검토·실행 명령 | 이전 기록, 코드 삭제 |
| [서버 10건 사전 구축](verification/server_dictionary_build_2026_10_21.md) | 문서별 의미 구조·공통 사전·매핑·보류·실제 결과 검증 | r2: 원자 속성 145개·속성 후보 25개, 미승인 |
| [고정 사전의 다른 문서 4건 적용](verification/server_dictionary_reuse_2026_10_21.md) | 기존 의미 재사용·적용 대상 누락·신규 후보 분리 | 대표 속성 84건 검토, 독립 정확도 평가 아님 |
| [확대 전 자동 처리·의미 평가 검증](verification/semantic_readiness_2026_10_21.md) | 자동 재사용·의미 사례 평가·구간별 추출과 실제 실패 기록 | 단위 검사 통과, 실제 자동 실행 시간 초과로 확대 보류 |
| [새 배치 검증](verification/semantic_batch_2026_10_21.md) | 정리 범위·실행 결과·검증 한계 | 실행 기록 |
| [속성 사전의 구조](attribute_registry.md) | 속성·대상 범위·상태·조건의 분리 | 이전 설계 |
| [삭제한 검색 평가 실험](verification/retired_search_evaluation.md) | 과거 실험 삭제 안내 | 코드·테스트·의존성 삭제 |
| [80/20 자동 평가 결과](verification/search_experiment_2026_10_20.md) | 20건·120문항·후보 비교·실패 분석 | 검증 20/24 → 13/24, 변경안 승격 안 함 |

## 서비스 확장과 파싱 설계 자료

- [서비스 전체 설계](overview.md)
- [도메인 모델](domain_model.md)
- [첨부 후보 선정](document_identification.md)
- [문서 파서 평가 기준](parser_evaluation_criteria.md)
- [문서 파싱](document_parsing.md)
- [문서 적합성 판정](document_qualification.md)

## 과거 실험 기록과 폐기한 계약

아래 결과는 당시 관측이며 현재 실행 코드의 기능·성능을 뜻하지 않는다.
과거 명령·재현 스크립트는 실행 기준으로 사용하지 않는다.

- [과거 산출물 정리 기록](verification/artifact_cleanup_2026_10_24.md)

- [폐기한 사전 bootstrap 기록](verification/dictionary_bootstrap_2026_10_20.md)
- [폐기한 서버 사전 구축 기록](verification/server_dictionary_bootstrap_2026_10_20.md)

- [서버 첫 검증](computer_server_validation.md)
- [첨부 선별 평가](selection_evaluation_2026_10_20.md)
- [메타데이터 평가](evaluation_2026_10_20.md)
- [OCR 제외 파서 비교](parser_evaluation_2026_10_20.md)
- [Codex 다품목 분석](codex_analysis_2026_10_20.md)
- [구성요소 원문 대조](component_review_2026_10_20.md)
- [요구조건 추출 시험](requirement_extraction_2026_10_20.md)
- [귀속·통합 시험](requirement_consolidation_2026_10_20.md)
- [폐기한 품목 식별 계약](line_item_identification.md)
- [폐기한 구성요소 식별 계약](component_identification.md)
- [폐기한 요구조건 추출 계약](requirement_extraction.md)
- [폐기한 귀속·통합 계약](requirement_consolidation.md)

문서는 이 폴더에 모으되 실행 코드는 [소유권 기준](../architecture/repository-structure.md)에 따른다.
실행 코드는 Pipelines가 소유하고 `.artifacts`에는 보존 결과와 로컬 객체 저장소 데이터만 둔다.
