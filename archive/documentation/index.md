# 과거 문서 보관함

이곳은 비활성 업무·이전 설계·실험 기록이다. **현재 실행 방법은 [문서 목차](../../docs/index.md)를 따른다.**
날짜·건수·“현재”라는 표현은 작성 당시의 상태다. 보관한 명령으로 은퇴한 기능을 다시 연결하지 않는다.

## 보관 자료

### 물품 모델 설계 이력

- [규격서 물품·분류·구성·속성 모델](architecture/specification_goods_model_2026_10_27.md)

### 이전 조달 연동

- [입찰체크 서비스 연동](integration/bid-check-service.md)
- [입찰체크 조달 탐색 연동 계약](integration/procurement_exploration_contract.md)

### 이전 조달 수집

- [공공조달 데이터 수집](pipelines/domains/public_procurement.md)

### 이전 조달 분석

- [공공조달 활동·참여 집계](platform/domains/public_procurement/activity_aggregation.md)
- [공공조달 계약 집계 기준](platform/domains/public_procurement/contract_aggregation.md)
- [공공조달 시장 분석 구현](platform/domains/public_procurement/market_analysis.md)
- [입찰공고 현재 상태 기준](platform/domains/public_procurement/notice_status.md)
- [공공조달 분야 분류 기준과 확장 계획](platform/domains/public_procurement/procurement_classification.md)

### 이전 규격서 설계·실험

- [속성 사전의 구조](procurement_specification_processing/attribute_registry.md)
- [Codex 다품목 분석 시험 — 2026-10-20](procurement_specification_processing/codex_analysis_2026_10_20.md)
- [5단계 원문 대조 검증 — 2026-10-20](procurement_specification_processing/component_review_2026_10_20.md)
- [컴퓨터서버 첫 검증과 공통 선별기 구현 기록](procurement_specification_processing/computer_server_validation.md)
- [문서 파싱 모듈 설계](procurement_specification_processing/document_parsing.md)
- [조달 규격 인텔리전스 도메인 모델 검토안](procurement_specification_processing/domain_model.md)
- [2026-10-20 규격서 후보 메타데이터 평가](procurement_specification_processing/evaluation_2026_10_20.md)
- [IE 라이브러리 비교 검토](procurement_specification_processing/ie_library_comparison.md)
- [조달 규격 인텔리전스 서비스 설계 초안](procurement_specification_processing/overview.md)
- [OCR 제외 문서 파서 비교 결과](procurement_specification_processing/parser_evaluation_2026_10_20.md)
- [문서 파서 평가 기준서](procurement_specification_processing/parser_evaluation_criteria.md)
- [규격 정보 추출과 표준 관리 파이프라인](procurement_specification_processing/pipeline_2026_10_27.md)
- [7단계 귀속·통합 시험 — 2026-10-20](procurement_specification_processing/requirement_consolidation_2026_10_20.md)
- [6단계 요구조건 추출 시험 — 2026-10-20](procurement_specification_processing/requirement_extraction_2026_10_20.md)
- [실험 산출물 정리 — 2026-10-24](procurement_specification_processing/verification/artifact_cleanup_2026_10_24.md)
- [이전 실행 기록의 폐기](procurement_specification_processing/verification/composition_review_2026_10_20.md)
- [공고 이해·재귀 구성 트리 파이프라인 검증](procurement_specification_processing/verification/composition_tree_pipeline_2026_10_22.md)
- [이전 실행 기록의 폐기](procurement_specification_processing/verification/dictionary_bootstrap_2026_10_20.md)
- [납품 품목 중심 파이프라인 v2 교체 검증](procurement_specification_processing/verification/item_first_pipeline_2026_10_22.md)
- [파이프라인 코드 정리](procurement_specification_processing/verification/pipeline_cleanup_2026_10_20.md)
- [삭제한 검색 평가 실험](procurement_specification_processing/verification/retired_search_evaluation.md)
- [공고 이해와 재귀 구성 트리 기반 규격 분석](procurement_specification_processing/verification/retired_semantic_batch.md)
- [규격서 80/20 자동 평가 결과](procurement_specification_processing/verification/search_experiment_2026_10_20.md)
- [1회성 의미 분석 배치 재구축](procurement_specification_processing/verification/semantic_batch_2026_10_21.md)
- [데이터 확대 전 자동 처리·의미 평가 검증](procurement_specification_processing/verification/semantic_readiness_2026_10_21.md)
- [이전 실행 기록의 폐기](procurement_specification_processing/verification/server_dictionary_bootstrap_2026_10_20.md)
- [컴퓨터 서버 표본 10건의 사전 구축 배치](procurement_specification_processing/verification/server_dictionary_build_2026_10_21.md)
- [서버 사전 고정 후 다른 문서 4건 재사용 검증](procurement_specification_processing/verification/server_dictionary_reuse_2026_10_21.md)
- [같은 최소 추출 방식의 서버 규격서 3건 적용](procurement_specification_processing/verification/server_extraction_replication_2026_10_21.md)
- [서버 한 건 최소 추출과 원문 대조](procurement_specification_processing/verification/server_single_extraction_2026_10_21.md)

## 이동·삭제 기준

고유한 설계·실행 관측은 보존했다. 실행 코드가 삭제된 경로를 다시 안내하는 중복 문서는 제거하고 관련 내부 링크를 정리했다.
현재 Pipeline·물품 모델 경로는 유지했으며 이전 상세 설명은 날짜가 붙은 보관 기록으로 분리했다.

| 이전 위치 | 현재 위치 |
|---|---|
| `docs/architecture/specification_goods_model.md` | [specification_goods_model_2026_10_27.md](architecture/specification_goods_model_2026_10_27.md) |
| `docs/integration/bid-check-service.md` | [bid-check-service.md](integration/bid-check-service.md) |
| `docs/integration/bid_check_capabilities.yaml` | [bid_check_capabilities.yaml](integration/bid_check_capabilities.yaml) |
| `docs/integration/procurement_exploration_contract.md` | [procurement_exploration_contract.md](integration/procurement_exploration_contract.md) |
| `docs/pipelines/domains/public_procurement.md` | [public_procurement.md](pipelines/domains/public_procurement.md) |
| `docs/platform/domains/public_procurement/activity_aggregation.md` | [activity_aggregation.md](platform/domains/public_procurement/activity_aggregation.md) |
| `docs/platform/domains/public_procurement/contract_aggregation.md` | [contract_aggregation.md](platform/domains/public_procurement/contract_aggregation.md) |
| `docs/platform/domains/public_procurement/market_analysis.md` | [market_analysis.md](platform/domains/public_procurement/market_analysis.md) |
| `docs/platform/domains/public_procurement/notice_status.md` | [notice_status.md](platform/domains/public_procurement/notice_status.md) |
| `docs/platform/domains/public_procurement/procurement_classification.md` | [procurement_classification.md](platform/domains/public_procurement/procurement_classification.md) |
| `docs/procurement_specification_processing/attribute_registry.md` | [attribute_registry.md](procurement_specification_processing/attribute_registry.md) |
| `docs/procurement_specification_processing/codex_analysis_2026_10_20.md` | [codex_analysis_2026_10_20.md](procurement_specification_processing/codex_analysis_2026_10_20.md) |
| `docs/procurement_specification_processing/component_review_2026_10_20.md` | [component_review_2026_10_20.md](procurement_specification_processing/component_review_2026_10_20.md) |
| `docs/procurement_specification_processing/computer_server_validation.md` | [computer_server_validation.md](procurement_specification_processing/computer_server_validation.md) |
| `docs/procurement_specification_processing/document_parsing.md` | [document_parsing.md](procurement_specification_processing/document_parsing.md) |
| `docs/procurement_specification_processing/domain_model.md` | [domain_model.md](procurement_specification_processing/domain_model.md) |
| `docs/procurement_specification_processing/evaluation_2026_10_20.md` | [evaluation_2026_10_20.md](procurement_specification_processing/evaluation_2026_10_20.md) |
| `docs/procurement_specification_processing/ie_library_comparison.md` | [ie_library_comparison.md](procurement_specification_processing/ie_library_comparison.md) |
| `docs/procurement_specification_processing/overview.md` | [overview.md](procurement_specification_processing/overview.md) |
| `docs/procurement_specification_processing/parser_evaluation_2026_10_20.md` | [parser_evaluation_2026_10_20.md](procurement_specification_processing/parser_evaluation_2026_10_20.md) |
| `docs/procurement_specification_processing/parser_evaluation_criteria.md` | [parser_evaluation_criteria.md](procurement_specification_processing/parser_evaluation_criteria.md) |
| `docs/procurement_specification_processing/pipeline.md` | [pipeline_2026_10_27.md](procurement_specification_processing/pipeline_2026_10_27.md) |
| `docs/procurement_specification_processing/requirement_consolidation_2026_10_20.md` | [requirement_consolidation_2026_10_20.md](procurement_specification_processing/requirement_consolidation_2026_10_20.md) |
| `docs/procurement_specification_processing/requirement_extraction_2026_10_20.md` | [requirement_extraction_2026_10_20.md](procurement_specification_processing/requirement_extraction_2026_10_20.md) |
| `docs/procurement_specification_processing/verification/artifact_cleanup_2026_10_24.md` | [artifact_cleanup_2026_10_24.md](procurement_specification_processing/verification/artifact_cleanup_2026_10_24.md) |
| `docs/procurement_specification_processing/verification/composition_review_2026_10_20.md` | [composition_review_2026_10_20.md](procurement_specification_processing/verification/composition_review_2026_10_20.md) |
| `docs/procurement_specification_processing/verification/composition_tree_pipeline_2026_10_22.md` | [composition_tree_pipeline_2026_10_22.md](procurement_specification_processing/verification/composition_tree_pipeline_2026_10_22.md) |
| `docs/procurement_specification_processing/verification/dictionary_bootstrap_2026_10_20.md` | [dictionary_bootstrap_2026_10_20.md](procurement_specification_processing/verification/dictionary_bootstrap_2026_10_20.md) |
| `docs/procurement_specification_processing/verification/item_first_pipeline_2026_10_22.md` | [item_first_pipeline_2026_10_22.md](procurement_specification_processing/verification/item_first_pipeline_2026_10_22.md) |
| `docs/procurement_specification_processing/verification/pipeline_cleanup_2026_10_20.md` | [pipeline_cleanup_2026_10_20.md](procurement_specification_processing/verification/pipeline_cleanup_2026_10_20.md) |
| `docs/procurement_specification_processing/verification/retired_search_evaluation.md` | [retired_search_evaluation.md](procurement_specification_processing/verification/retired_search_evaluation.md) |
| `docs/procurement_specification_processing/verification/retired_semantic_batch.md` | [retired_semantic_batch.md](procurement_specification_processing/verification/retired_semantic_batch.md) |
| `docs/procurement_specification_processing/verification/search_experiment_2026_10_20.md` | [search_experiment_2026_10_20.md](procurement_specification_processing/verification/search_experiment_2026_10_20.md) |
| `docs/procurement_specification_processing/verification/semantic_batch_2026_10_21.md` | [semantic_batch_2026_10_21.md](procurement_specification_processing/verification/semantic_batch_2026_10_21.md) |
| `docs/procurement_specification_processing/verification/semantic_readiness_2026_10_21.md` | [semantic_readiness_2026_10_21.md](procurement_specification_processing/verification/semantic_readiness_2026_10_21.md) |
| `docs/procurement_specification_processing/verification/server_dictionary_bootstrap_2026_10_20.md` | [server_dictionary_bootstrap_2026_10_20.md](procurement_specification_processing/verification/server_dictionary_bootstrap_2026_10_20.md) |
| `docs/procurement_specification_processing/verification/server_dictionary_build_2026_10_21.md` | [server_dictionary_build_2026_10_21.md](procurement_specification_processing/verification/server_dictionary_build_2026_10_21.md) |
| `docs/procurement_specification_processing/verification/server_dictionary_reuse_2026_10_21.md` | [server_dictionary_reuse_2026_10_21.md](procurement_specification_processing/verification/server_dictionary_reuse_2026_10_21.md) |
| `docs/procurement_specification_processing/verification/server_extraction_replication_2026_10_21.md` | [server_extraction_replication_2026_10_21.md](procurement_specification_processing/verification/server_extraction_replication_2026_10_21.md) |
| `docs/procurement_specification_processing/verification/server_single_extraction_2026_10_21.md` | [server_single_extraction_2026_10_21.md](procurement_specification_processing/verification/server_single_extraction_2026_10_21.md) |

삭제한 중복 안내: `experimental_k3s.md`, `codex_analysis.md`, `component_identification.md`, `composition_analysis.md`, `dictionary_building_pipeline.md`, `document_identification.md`, `document_qualification.md`, `line_item_identification.md`, `requirement_consolidation.md`, `requirement_extraction.md`, `selection_evaluation_2026_10_20.md`, `server_capabilities.md`.

원본 규격서·객체 저장소 산출물·DB·백업·적용 migration·게시 artifact는 정리 대상이 아니다.
