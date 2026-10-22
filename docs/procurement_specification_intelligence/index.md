# 조달 규격 인텔리전스

현재 실행 기준은 **공고 이해·재귀 구성 트리 기반 오프라인 분석 배치 v3**다.
[단계·계약·실행 방법](semantic_batch.md)은 입력 고정 → 공고 이해 → 재귀 구성 트리 식별·검토 → 대상별 규격
추출 → 동일 대상·관계 정리 → 원문 검증 → 문서 간 의미 통합 → 결과 저장 순서다.
공고의 구매 목적과 통합 납품 범위에서 시작해 상위 대상 → 구성품 → 하위 구성품을 식별한다.
서버·랙·CPU도 문맥에 따라 독립 납품 대상 또는 하위 구성품이 된다. 원본 관찰·근거와 미확정 해석을 보존한다.

2026-10-22 사용자 요청으로 기존 일괄 추출·link·문자 수 분할 로직과 전용 테스트를
교체했다. 새 단계의 검증 오류는 사전 통합을 차단한다. 결과는 미승인 제안이며
게시 사전 승인·운영 처리 흐름·첨부 자동 처리·API·배포에는 연결하지 않는다.
고정 사전 재사용과 의미 사례 평가는 `semantic_evaluation`의 오프라인 실험이다.
원본·파싱 입력과 Harness2·검색 평가 경로는 보존했다. 아래 과거 실행 결과는
v3의 정확도나 성능을 뜻하지 않는다.

## 지금 볼 문서

| 문서 | 내용 | 상태 |
|---|---|---|
| [재귀 구성 트리 v3 검증](verification/composition_tree_pipeline_2026_10_22.md) | 계층 계약·구성 검토·네 샘플 재실행 | 실행 기록과 한계 |
| [품목 중심 v2 교체 검증](verification/item_first_pipeline_2026_10_22.md) | 교체 범위·테스트·실제 문서 실행 | 206개 테스트 통과, 서버 1건 needs_review 저장 |
| [서버 한 건 최소 추출](verification/server_single_extraction_2026_10_21.md) | 추론 1회로 대상·관계·규격 JSON 추출 후 원문 대조 | 52.802초 완료, 독립 정확도 평가 아님 |
| [다른 서버 규격서 3건 적용](verification/server_extraction_replication_2026_10_21.md) | 같은 지시·형식으로 HWPX·PDF·HWP 처리 및 원문 대조 | 2건 완료·1건 시간 초과, 과분리·범위 미해결 확인 |
| [재귀 구성 트리 분석 배치](semantic_batch.md) | v3 단계·부모 관계·속성 귀속·검토·실행 명령 | 오프라인 구현, 운영 미연결 |
| [서버 10건 사전 구축](verification/server_dictionary_build_2026_10_21.md) | 문서별 의미 구조·공통 사전·매핑·보류·실제 결과 검증 | r2: 원자 속성 145개·속성 후보 25개, 미승인 |
| [고정 사전의 다른 문서 4건 적용](verification/server_dictionary_reuse_2026_10_21.md) | 기존 의미 재사용·적용 대상 누락·신규 후보 분리 | 대표 속성 84건 검토, 독립 정확도 평가 아님 |
| [확대 전 자동 처리·의미 평가 검증](verification/semantic_readiness_2026_10_21.md) | 자동 재사용·의미 사례 평가·구간별 추출과 실제 실패 기록 | 단위 검사 통과, 실제 자동 실행 시간 초과로 확대 보류 |
| [새 배치 검증](verification/semantic_batch_2026_10_21.md) | 정리 범위·실행 결과·검증 한계 | 실행 기록 |
| [속성 사전의 구조](attribute_registry.md) | 속성·대상 범위·상태·조건의 분리 | 현재 모델 |
| [검색 평가·개선 자동화](search_evaluation_pipeline.md) | 80/20 분리·Codex 질문 정답·Harness2·개발 관찰 통합 | 보존 |
| [80/20 자동 평가 결과](verification/search_experiment_2026_10_20.md) | 20건·120문항·후보 비교·실패 분석 | 검증 20/24 → 13/24, 변경안 승격 안 함 |

## 서비스와 파싱 설계

- [서비스 전체 설계](overview.md)
- [도메인 모델](domain_model.md)
- [첨부 후보 선정](document_identification.md)
- [문서 파서 평가 기준](parser_evaluation_criteria.md)
- [문서 파싱](document_parsing.md)
- [문서 적합성 판정](document_qualification.md)

## 과거 실험 기록과 폐기한 계약

아래 결과는 당시 관측이며 현재 실행 코드의 기능·성능을 뜻하지 않는다.
과거 명령·재현 스크립트는 실행 기준으로 사용하지 않는다.

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
현재 실행 코드는 Pipelines의 이름 있는 조달 기능에만 있으며 API·Registry·배포에 연결하지 않는다.
