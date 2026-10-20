# 조달 규격 인텔리전스

구성 분석은 [구성품·세부 규격 연결](composition_analysis.md), 초기 사전 구축은
[새 구축 파이프라인](dictionary_building_pipeline.md)을 실행 기준으로 사용한다.
저장된 kordoc 결과를 Codex가 읽고 주요 구성품·하위 대상·외부 참조를 구분한다.
코드는 인용·관계·값의 원문 존재를 검사한다. 외부 모델 API·OCR·운영 Flow는 사용하지 않는다.

예전 품목 → 구성요소 → 추출 → 통합의 단계별 코드와 사전 구축 코드는 삭제했다.
원본·파싱 결과·과거 JSON/CSV 결과는 보존했다. 이전 사전 52개는 과거 참고 초안이며
현재 입력 사전이 아니다. 새 파이프라인은 사전 없는 관찰·의미 통합·초안·최종 검토·수정·
재검증·로컬 승인·다음 배치 재사용을 지원한다. 의미 제안은 Codex가 작성하며
실제 컴퓨터서버 공고 10건에서 원문 관찰 385개·속성 정의 후보 152개를 만들었다.
미해결 문제 19개가 남아 승인하지 않았다. 단일 공고에서만 관찰된 정의는 107개다.
후속 [속성 단위 감사](attribute_registry.md#현재-초안의-과분리와-재검토)에서 중복·표현 차이·
복합 원문·요구조건 혼입을 확인했다. 152개·189개는 정제된 표준 속성 수로 사용하지 않는다.

## 지금 볼 문서

| 문서 | 내용 | 상태 |
|---|---|---|
| [구성품·세부 규격 연결](composition_analysis.md) | 판단 로직·분석 지시문·현재 CLI | 현재 실행 기준 |
| [네 표본 검증](verification/composition_review_2026_10_20.md) | 주요 목록 28개·대표 규격 27개·오류 주입 | 개발 표본 자기검토 |
| [초기 사전 구축](dictionary_building_pipeline.md) | 모듈 재사용·초안·최종 검증·수정·로컬 승인 | 독립 CLI 구현 |
| [새 구축 파이프라인 검증](verification/dictionary_bootstrap_2026_10_20.md) | 합성 10건 배치·수정·재검증·다음 배치 | 계약 검증·실제 정확도 미측정 |
| [서버 실제 10건 구축 결과](verification/server_dictionary_bootstrap_2026_10_20.md) | 사전 없는 추출·통합·수정·최종 검사·파일 위치 | 152개 정의 후보·미승인 |
| [속성 사전의 구조](attribute_registry.md) | 속성·요구값·구성요소 유형의 차이 | 설계 |
| [검색 평가·개선 자동화](search_evaluation_pipeline.md) | 80/20 분리·Codex 질문 정답·Harness2·개발 관찰 통합 | 독립 실험 CLI |
| [Codex 분석 방식](codex_analysis.md) | 현재 분석·저장·검증 순서 | 현재 방식 |
| [코드 정리 내역](verification/pipeline_cleanup_2026_10_20.md) | 삭제·유지 범위와 과거 자료 취급 | 정리 기록 |

네 표본의 주요 목록은 환경감시 4개·액체크로마토그래프 9개·농기계 시험장치 10개·
특수차량 5개다. 사용자 검토안을 이미 본 개발 표본이므로 신규 문서 정확도가 아니다.
모든 속성이나 공통 조건의 귀속을 완료했다는 뜻도 아니다.

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
