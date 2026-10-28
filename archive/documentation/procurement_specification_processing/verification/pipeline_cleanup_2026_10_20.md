> **과거 자료·비활성**: 아래 설계·명령·건수는 작성 당시의 기록이다. 현재 사용 안내는 [문서 목차](../../../../docs/index.md)를 따른다.

# 파이프라인 코드 정리

사용자가 수정된 파이프라인을 기준으로 예전 코드를 삭제하도록 요청했다.
구성 분석을 현재 실행 기준으로 남기고 중복된 단계별 구현을 제거했다.

## 삭제한 코드

| 범위 | 삭제 |
|---|---|
| 모듈 5개 | `line_item_identification.py`, `component_identification.py`, `requirement_extraction.py`, `requirement_consolidation.py`, `dictionary_building.py` |
| 테스트·fixture 6개 | 위 모듈의 전용 테스트 5개와 해당 테스트 체인의 `conftest.py` |
| 실험 스크립트 11개 | 과거 구성·추출·통합·사전 구축 결과 작성 및 검증 스크립트 |

모듈·테스트·스크립트 합계 22개다. 삭제 전 파일 경로와 SHA-256은
`.artifacts/procurement_specifications/composition_review_2026_10_20/pipeline_cleanup_2026_10_20.json`에 기록했다.
예전 코드의 복사본이나 호환 실행기는 만들지 않았다.

## 유지한 코드와 자료

| 모듈 | 책임 |
|---|---|
| `attachment_selection` | 첨부 후보 선정 |
| `selection_evaluation` | 첨부 선별 평가 |
| `document_evidence` | 문서 구조·근거 참조와 인용 검사 |
| `document_qualification` | 문서 적합성 제안 검사 |
| `composition_analysis` | 구성·대표 규격 분석 입력 준비·검사·목록 대조 |

원본 규격서·저장된 파싱 결과·사용자 검토안·현재 구성 분석 결과를 보존했다.
과거 결과 JSON/CSV도 참고용으로 보존하되 예전 사전 52개를 현재 사전으로 사용하지 않는다.
해당 실험 디렉터리에 `retirement.json`으로 구분했다. 원본과 결과 파일 내용은 변경하지 않았다.

예전 안내 문서 경로는 기존 링크 호환을 위해 짧은 폐기 안내로 남겼다.
날짜가 붙은 검증 문서는 당시 결과로 표시하고 이전 명령을 현재 실행법으로 안내하지 않는다.

현재 실행은 [구성 분석](pipeline_cleanup_2026_10_20.md)을 따른다.
전체 요구조건 구조화와 사전 생성·승인은 [후속 계획](pipeline_cleanup_2026_10_20.md)이며
이번 정리만으로 해당 기능이 구현된 것은 아니다.

## 정리 후 검증

- Pipeline 전체 테스트: 225개 통과·16개 건너뜀, 기존 Prefect 경고 1개.
- 삭제한 모듈 5개의 import 경로가 존재하지 않고 실행 코드·실험 스크립트에 남은 의존성이 없음.
- 현재 네 표본에서 prepare/validate/evaluate를 재실행해 주요 목록 4·9·10·5개와 검사 결과 유지.
- 원본 규격서 4개의 SHA-256 변경 없음.
- 문서 78개·로컬 링크 441개에서 오류 없음.

과거 305개 테스트 기록과 차이가 나는 것은 삭제한 모듈의 전용 테스트를 함께 제거했기
때문이다. 현재 CLI 재검증은 실험 디렉터리의 `cleanup_cli_checks.json`에 있다.
