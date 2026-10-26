# PDFium 대체 후보 개선 — 2026-10-26

**기본 PyMuPDF 엔진은 유지했다.** 지난 pdfplumber 후보를 개선해 PDFium 네이티브 API로
문자·도형·이미지를 읽도록 바꿨다. 처리시간과 일부 기능은 개선됐지만 고정한 기준 엔진 대비
속도·출력 보존 조건을 충족하지 못해 미채택했다.

## 변경과 근거

지난 후보를 프로파일링한 12쪽 실문서에서 전체 profile 12.815초 중 pdfminer page
interpreter가 10.094초였다. 이는 프로파일링 결과이며 실제 지연 비교는 아래 반복 측정을
사용한다. 후보의 페이지 문자·도형 해석을 PDFium으로 옮겼다. pdfminer는 typed Info와
원본 stream·Form 접근에 사용하며 page interpreter와 glyph layout은 실행하지 않는다.

PDFium이 비제한적 clip을 생략하는 사례를 자체 작성 원문에서 확인했다. 표 복원에 필요한
명시적 직사각형 clip은 별도 stream reader로 보존했다. 이 reader는 문자열·주석·배열과
q/Q·cm·Form 변환을 구분하며 원문 clipping만 수집한다. 새 검사에 빈 테두리 없는 clip,
Form 변환, 문자열 안 가짜 연산자를 포함했다.

회전 문자 각도 방향을 보정했고, 이미지 요청에는 복원 가능한 PNG·MIME·픽셀을 반환한다.
최초 탐색 71개에서 PDFium 문자 API의 surrogate 반환값 때문에 JSON 저장이 실패한 문서 4개가 나왔다.
수정은 기존 고정 회귀 문서 `corpus_004`와 자체 작성 ToUnicode 원문을 근거로 했다.
유효하지 않은 surrogate 값은 `�`와 `UNRESOLVED_PDF_GLYPH` 경고로 반환한다.
원래 글자의 의미 복원은 검증되지 않았다. 수정 전후 테스트와 탐색 측정을 보존했고,
최종 소스를 모든 문서에서 다시 측정했다.

실험 snapshot의 의존성·잠금·옵션·원래 테스트·평가 기준은 유지했다.
마무리 감사에서 작업 트리의 `src/kory_parser/pdf.py`와
`tests/test_pdf_image_only_tables.py`가 실험 시작 후 변경된 것을 확인했다.
이번 작업은 그 변경을 보존했다. 아래 수치는 **시작 시 고정한 소스** 간 비교이며,
동시에 갱신된 현재 작업 트리 전체와의 최신 비교는 아니다.
동시 변경 파일과 양쪽 hash는 `concurrent_worktree_changes.json`에 기록했다. 시험 snapshot 안에서만
기존 옵션 표기를 유지한 채 PDF 기초 추출기를 교체했다. MuPDF fallback은 사용하지 않는다.
기본 API를 교체하거나 활성 서비스·Registry·배포에 연결하지 않았다.

## 반복 측정

이전 후보와 같은 의존성의 격리 환경을 사용했다. Kory 0.9.15 / PyMuPDF 1.27.2.3,
pypdfium2 5.14.0, pdfminer.six 20260107이며 reference는 kordoc 4.22.15다.
문서별 warm-up 1회 후 3회 중앙값, 시작·파일 읽기 제외, 문서별 실행 순서 교대다.
OCR·이미지 본문 추출은 끄고 번호 구조 복원은 켰다.

이전 PDF 59개와 신규 PDF 12개를 합친 **71개**를 비교했다. 신규 표본은 공통 이력에서
기존 공고·SHA-256을 제외했고 새 seed를 기록했다. 개발 8개·미사용 family 검증 4개다.
검증 원문을 보고 수정하지 않았다. 탐색 이후 재측정한 검증을 독립적인 비밀 holdout으로
해석하지 않는다. 원문 시각 검사는 신규 개발 PDF 2개에 한정했다.

| 공통 성공 문서 중앙값 합 | 기준 | 개선 후보 |
|---|---:|---:|
| 이전 대체 후보와 직접 비교한 5개 | 8.991초 | 3.864초 |
| 고정 PyMuPDF와 이전 PDF 집합 비교 | 32.279초 | 52.035초 |
| 고정 PyMuPDF와 전체 71개 비교 | 37.862초 | 61.965초 |

직접 비교 5개에서 이전 pdfplumber 후보 대비 처리시간이 **57.03% 감소**했다.
같은 이전 PDF 집합의 공통 성공 56개에서는 고정 PyMuPDF의 **1.61배**,
전체 공통 성공 68개에서는 **1.64배**였다.
전체 처리 성공은 기준 68/71·후보 68/71이다.
신규 12개는 이전 실험에 없으므로 기존 59개 수치와 구분했다.

지연 경고 64개를 같은 최종 snapshot으로 5회 재측정했고,
64개에서 15%와 10 ms를 모두 초과한 지연이 재현됐다. 첫 측정과 확인 측정은
각각 보존했다. 메모리·실서비스 동시 요청 처리량·OCR 추론 정확도는 측정하지 않았다.
공유 호스트의 warm parse 결과다.

## 기능과 원문 검사

동결한 원래 테스트는 기준 엔진에서 **314개 통과**했다. 최종 후보는 동결 테스트
**299개 통과·15개 실패**, 추가·보존한 후보 전용 검사 **8개 통과**다.
새 Unicode 회귀 검사는 수정 전 실패·수정 후 통과를 확인했다.
15개 실패 중 10개는 MuPDF 연결·설치 방식에 의존하는 검사이고,
나머지는 여러 줄 제목의 병합 1개와 기존 좌표 계약 4개다.
기존 회전 여백 텍스트의 문자열 보존은 통과하지만 같은 테스트의 제목 병합 검사는 남아 있다.
마지막 gate는 동시에 추가된 이미지 표 테스트까지 실행해 **301개 통과·22개 실패**였다.
위 299/15는 동결 테스트 기준이며 이 gate 결과와 구분한다. 동시 변경의 소스·테스트도
`concurrent_worktree_snapshot/`에 별도 보존했다.

고정 회귀 원문 160개를 모두 재실행해 전체 JSON 일치는 106/160개였다.
비PDF 103개 중 103개가 동일했다.
전체 공통 성공 문서에서 정규화 본문 일치는 33/68,
표 격자 일치는 58/68,
표 격자·셀 내용 일치는 50/68다.
평균 문자 multiset F1은 0.992277다.
문자 일치도가 낮은 고정 회귀 문서 3개에서는 문자 multiset 기준 기존 문자의 누락은 없었고
후보에 `�`가 각각 4283·3305·3320개 추가됐다. 이들은 PDFium에서 유효한 Unicode scalar를 얻지 못한 glyph를 보수적으로
대체 문자로 표현한 결과이며, 공백·의도된 글리프 여부를 원문과 font outline에서 검증해야 한다.
`character_agreement_diagnostics.json`과 해당 사례를 보존했다.
이 지표는 기존 출력과의 일치도이며 원문 정확도가 아니다.

원본 PDF를 시각 확인한 부분 검사는 5개 문서다.

| 부분 검사 | 기존 엔진 | 후보 |
|---|---:|---:|
| source_fragment_presence | 10/13 | 11/13 |
| reviewed_pdf_page_table_count | 1/2 | 1/2 |
| reviewed_pdf_page_grid | 1/2 | 1/2 |

원문 검사 개선 1개·퇴행 0개였다.
단편 문자 점수로 표·읽기 순서·전체 JSON 변화를 상쇄하지 않았다.
판정과 불일치 목록은 `acceptance/acceptance.json`, `next_issues.json`에 남겼다.

`evaluations.improve`는 1회·120초 예산으로 자체 작성 orientation 계약을 실행했고
`all_checks_passed`로 종료했다. 이것은 합성 계약 smoke이며 실제 문서 품질의 근거와 구분한다.
후보 자체는 수동 작성했고 이 실행에서 추가 Codex subprocess는 호출하지 않았다.
기존 gate는 실제 문서·회귀·테스트·시간 조건에 따라 미채택이며 `applied=false`다.

## 재현 자료와 정리

로컬 `.artifacts/pdf_engine_trial_2026_10_26_002/`에 다음을 보존했다.

- `baseline/`, `previous/`, `candidate_before_unicode/`, `candidate/`, `candidate.patch`: 고정 소스.
- `protocol.json`, `environment.json`, `engine_requirements.txt`, `prepare_environment.py`: 환경과 구현.
- `comparison_manifest.json`, `sample/cycle_manifest.json`: 입력 hash와 신규 표본 provenance.
- `discovery_benchmark.json`, `discovery_failures/`: Unicode 수정 전 탐색 결과와 오류 근거.
- `benchmark/benchmark.json`, `controlled_previous/benchmark.json`, `timing_confirmation/benchmark.json`: 측정.
- `quality.json`, `source_labels.json`, `regression/report.json`, `report/summary.json`: 품질·회귀·요약.
- `unicode_before.log`, `unicode_fix_tests.log`, `unicode_real_document_smoke.json`: Unicode 수정 검증.

원문과 상세 실행 출력은 Git에 넣지 않았다. 재실행은 새 output 경로를 사용하고
기존 측정·원문·정답·공통 사용 이력을 덮어쓰지 않는다. 정리한 일반 표본은 공고 프레임에서
동일 SHA-256의 원문 바이트를 다시 확보해야 전체 비교를 재실행할 수 있다. 격리 설치 환경은
`prepare_environment.py`로 복원할 수 있다.

기본 report cleanup과 추가 정리로 **285,741,056 bytes 제거**,
이 실험 안의 **15,814,656 bytes 보존**을 기록했다.
고정 회귀 원문·선택한 원문 근거·사용 이력·고정 소스·측정값은 유지했다.
