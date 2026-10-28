> **과거 자료·비활성**: 아래 설계·명령·건수는 작성 당시의 기록이다. 현재 사용 안내는 [문서 목차](../../../docs/index.md)를 따른다.

# OCR 제외 문서 파서 비교 결과

평가일은 **2026-10-20**이다. 기존 첨부 선별 후보 8개와 한계 확인용 후보 PDF 2개,
총 **10개 파일**에 대해 기본 6개 도구를 로컬에서 실행했다. 이후 별도 도구인
`hwp-hwpx-parser`를 같은 HWP·HWPX 4개에 추가 실행해 **총 7개 도구**를 비교했다. OCR·수식 OCR·외부 문서
전송은 사용하지 않았다. 기준은 [파서 평가 기준서](parser_evaluation_criteria.md)다.

## 결론과 현재 권장 구성

현재 표본에서는 **kordoc 4.22.15를 기본 구조 파서로 사용하고, 원본 형식별 검사와
근거 연결을 추가하는 구성**을 권장한다. 특히 중첩 표 사례에서 내부 11행·3열,
디스크 2행 병합과 보조장치 4행 병합을 함께 보존했다. 다른 PDF 도구와 설정도
비교했지만 이 사례를 더 잘 보존하는 대체 조합은 확인하지 못했다.

파서 하나의 `success` 또는 품질 점수만으로 자동 분석에 통과시키지 않는다.
현재 표본·확인 구간의 권장안이며 전체 형식·문서의 최적성이 입증됐다는 뜻은 아니다.
공통 Document JSON과 운영 모듈의 최종 승인은 후속 검토다.

| 형식 | 기본 처리 | 추가 검사·근거 | 현재 제한 |
|---|---|---|---|
| 텍스트 PDF | kordoc 구조 출력 | PyMuPDF로 내장 텍스트·이미지·도형·페이지·위치 검사, 필요 시 다른 파서와 차이 비교 | 제목 계층·페이지 경계 표 연결은 별도 검증 |
| HWP | kordoc 구조 출력 | 원본 BodyText 레코드와 연결, pyhwp XML로 표·구성 관계 교차 점검 | 원본 화면의 전체 표 배치 대조가 끝나지 않아 전체 구조 통과 보류 |
| HWPX | kordoc 구조 출력 | 원본 ZIP/XML의 현재 본문·표 ID·행·열·셀·변경 추적 대조 | 삭제된 표와 현재 표를 구분해야 함 |
| DOCX | kordoc 구조 출력 | python-docx 및 원본 XML로 표·셀·순서·원본 anchor 대조 | 한 문서의 결과, 제목 계층 자동 보존은 미확정 |
| 텍스트 없는 PDF·이미지 규격 | 원본·영역만 보존 | 읽지 못한 영역을 표시하고 보류 | OCR 없이 실제 요구규격을 복원하지 않음 |

Docling은 PDF의 제목 후보·표 영역을 비교하는 보조 후보로 남긴다. 두 결과가
다르다고 다수결로 값을 확정하거나 셀을 임의로 합성하지 않는다. 다른 파서로 다시
실행해도 기존 원본 출력·오류를 보존하고 새 결과를 같은 기준으로 검증한다.

## 표본과 원문 기준

원본은 기존 다운로드를 재사용하고 SHA-256을 검증했다. 새 다운로드는 하지 않았다.
첫 8개는 v3 `first_review` 후보이고, 뒤 2개도 같은 규칙으로 선정됐지만 이전 내용
평가에서 미확인이었던 문서다. 파일명만으로 규격 포함을 정답 처리하지 않았다.

| 문서 ID | 공고번호 / 슬롯 | 형식 | 확인 구간·특성 |
|---|---|---|---|
| doc_01 | R26BK01347519 / 2 | PDF | 17쪽 문서의 4쪽 목표시스템 표. 실제 내용은 GPU 카드 증설 |
| doc_02 | R26BK01481989 / 3 | PDF | 1쪽 물품 표와 메모리 조건·장별 제목 |
| doc_03 | R26BK01501837 / 3 | HWP | CPU 구성 행, BodyText/Section0 레코드 근거 |
| doc_04 | R26BK01550024 / 2 | PDF | 외부 표 안의 규격 표·수량 열·병합 셀 |
| doc_05 | R26BK01624782 / 3 | HWP | CPU·RAM 구성과 중첩 표, 원문의 `2-core` 표현 보존 |
| doc_06 | R26BK01720586 / 3 | HWPX | 서버·스토리지·랙, 변경 추적의 삭제 표·삽입 문구 |
| doc_07 | R26BK01744837 / 3 | HWPX | 2행·5열 표와 AMD EPYC 규격 문단 |
| doc_08 | R26BK01773827 / 2 | DOCX | 16행·5열 규격 표와 CPU 조건 |
| doc_09 | R26BK01266210 / 3 | PDF | 화면에는 규격이 보이지만 내장 텍스트 0자인 1쪽 문서 |
| doc_10 | R26BK01701988 / 2 | PDF | 5쪽 문서의 3쪽 이미지 기반 규격 영역 |

PDF는 원본 렌더를 시각 검토했고, HWPX·DOCX는 원본 XML·표 속성·셀 텍스트를
조사했다. HWP는 원본 바이너리 텍스트 레코드와 독립 파서 XML을 대조했으며 원본
화면 전체의 시각 대조를 완료하지 않았다. 검토자는 assistant 1명이며 전문가 이중
검수가 아니다. 중요한 구간의 진단이므로 전체 문서 통과 수나 모집단 정확도를 주장하지 않는다.
XLSX 표본, 정상 추출 가능한 페이지 간 연속 표, 활성 병합 셀이 있는 HWPX는 추가 검증 대상이다.

## 도구와 실행 조건

지원 형식은 설치한 버전과 이번 파일의 실제 실행 범위로 구분했다. 최신 공식 문서의
지원 목록만으로 HWP·HWPX 지원을 추정하지 않았다. 총 60개 도구–문서 조합 중
**29개를 실행했고 31개는 해당 도구의 이번 비교 범위 밖**으로 기록했다.
29개 모두 실행상 성공을 반환했지만 내용·구조 품질 통과와는 별개다.

| 도구·버전 | 실제 기본 실행 수 | 출력과 OCR 조건 |
|---|---:|---|
| kordoc 4.22.15 | 10 | IRBlock·표·outline·품질 진단, `ocr: false`, `images: false` |
| Docling 2.140.0 | 6 | native JSON·Markdown, PDF `do_ocr=False`, 원격 서비스·시각/코드/수식 설명 비활성화 |
| PyMuPDF 2.0 | 5 | 텍스트·단어·좌표·표·이미지·도형 정보, OCR 메서드 미호출 |
| pdfplumber 0.11.10 | 5 | 문자·선·사각형·이미지·표·셀 좌표, OCR 미사용 |
| python-docx 1.2.0 | 1 | 문서 순서의 문단·표·원본 table XML, OCR 미사용 |
| pyhwp 0.1b15 | 2 | `hwp5proc xml`의 표·셀·문단 구조, OCR 미사용 |
| hwp-hwpx-parser 1.0.0, 추가 비교 | 4 | native binary/XML Reader·TableData, OCR 미사용. 기본 60개 조합과는 별도 기록 |

Docling은 CPU 2 threads로 실행했다. 첫 실행에는 모델 확보·초기화가 포함됐다.
기본 실행 1회의 시간은 진단 기록이며 도구 간 성능 순위로 사용하지 않는다.
kordoc 보존 설정은 별도로 3회 반복해 재현성을 확인했다. 문서 내용은 로컬에서만
처리했으며 의존성과 모델은 별도 `.artifacts` 환경에 설치했다. 저장소 lockfile·운영
의존성·Flow·Registry·DB migration은 바꾸지 않았다.

공식 근거 확인일도 2026-10-20이다.

- [kordoc 공식 저장소](https://github.com/chrisryugj/kordoc): 설치 버전의 타입 선언에서 OCR·표·위치·보존 옵션을 추가 확인했다.
- [Docling 지원 형식](https://docling-project.github.io/docling/usage/supported_formats/), [실행 옵션](https://docling-project.github.io/docling/usage/advanced_options/): PDF·DOCX 실행과 OCR 비활성 옵션을 확인했다.
- [PyMuPDF 텍스트 API](https://pymupdf.readthedocs.io/en/latest/recipes-text.html), [표 API](https://pymupdf.readthedocs.io/en/latest/page.html): native text와 표·위치 출력을 사용했다.
- [pdfplumber 공식 저장소](https://github.com/jsvine/pdfplumber): 표 전략·선 연결·셀 좌표 옵션을 확인했다.
- [python-docx 표 문서](https://python-docx.readthedocs.io/en/latest/user/tables.html), [pyhwp 공식 저장소](https://github.com/mete0r/pyhwp): 각 원본 형식의 구조 비교에 사용했다.
- [hwp-hwpx-parser 공식 저장소](https://github.com/KimDaehyeon6873/hwp-hwpx-parser), [배포 패키지](https://pypi.org/project/hwp-hwpx-parser/): pyhwp와 별도 도구이며 HWP·HWPX 통합 Reader를 실제 실행했다.

## 구조·근거 비교 결과

기본 실행 29개 결과와 권장 보존 설정 10개 결과에 대해 중요 구간별 7항목을
분리한 진단 기록 39개를 남겼다. HWP의 미완료 시각 구조 검토는 보류로 표시했다.
아래 표는 주요 차이이며 전체 판정은 실험 자료의 `manual_region_reviews.json`에 있다.

| 확인 대상 | 관측 결과 | 판단 |
|---|---|---|
| PDF 단순 표, doc_01 4쪽 | kordoc·pdfplumber가 3행·3열과 원문 셀 순서를 유지 | 해당 표의 유효 후보 |
| PDF 텍스트 읽기 순서 | PyMuPDF 기본 텍스트에서 어순·기호 위치가 달랐고 `sort=True`로 선택한 핵심 문자열은 복구 | 정렬 옵션의 영향 기록. 표 구조 문제와는 별개 |
| PDF 중첩 표, doc_04 | kordoc이 내부 11행·3열과 2행·4행 병합을 유지 | 이 사례의 기본 파서 우선 근거 |
| 같은 표의 PyMuPDF 기본 추출 | 외부 7행·7열에 내부 내용이 평탄화되고 셀 텍스트 소수점이 줄 뒤로 분리 | 원문 추적·텍스트 보조 용도. 이 설정의 표 결과는 그대로 채택하지 않음 |
| 같은 표의 pdfplumber 기본 추출 | 내부 표를 찾지만 7행·3열로 일부 세부 행을 합침 | 수량·상세 행의 관계 재검토 필요 |
| 같은 표의 Docling | 내부 11행·3열은 보존, 외부 표는 6행·8열로 달라짐 | 내부 표와 문서 전체 구조 품질을 구분 |
| 제목 계층 | kordoc에서 제목이 목록·문단으로 남고 HWPX·DOCX의 outline이 없는 사례, Docling에서도 일부 장 제목 분류 누락 | 문구·스타일·순서와 추정 계층을 구분해야 함 |
| HWP 구성 표 | kordoc·pyhwp가 확인한 CPU·RAM 문구와 표 차원을 함께 보존 | 원본 시각 배치 검증은 보류 |
| HWPX 현재 표·셀 | 변경 추적을 반영한 활성 셀 31개가 kordoc 셀과 일치 | 원본 ID·행·열로 근거 연결 가능 |
| DOCX 표·셀 | 두 표의 활성 셀 90개가 kordoc 셀과 일치 | 동일 문서의 내용·셀 순서 대조 통과 |

셀 일치는 공백·줄바꿈, Markdown 링크·서식 표기, 표시용 escape를 구분해 현재
본문과 비교했다. 표 121개나 문서 121개의 평가가 아니라 **세 문서의 121개 셀**이다.
활성 셀 텍스트가 일치해도 문서 제목 계층·모든 위치·전체 문서의 의미 해석이 검증된
것은 아니다. 원문과 출력 셀의 crosswalk를 별도로 보관했다.

### 변경 추적으로 인한 원문 기준 수정

doc_06의 XML에는 표가 3개 있지만 첫 표 `1965472050`은 `deleteBegin Id=3`과
`deleteEnd Id=3` 사이의 삭제 내용이다. 현재 표는 2개이며 kordoc도 2개를 반환한다.
원문 조사에서 삭제 문구와 삽입 문구를 단순 연결한 부분도 현재 본문 기준으로 수정했다.

따라서 첫 조사에서 누락처럼 보였던 표는 **현재 본문 누락 오류가 아니다.** 기준서
1.1에 변경 추적 정책을 추가하고 모든 후보에 같은 기준을 재적용했다. 최초 원문 기준,
수정 기준·사유·hash를 남겼으며 삭제된 원문을 제거하거나 과거 조사 결과를 덮어
감추지 않았다. 링크 필드 내부 명령 문자열도 표시 본문과 구분했다.

### OCR 제외 조건의 두 한계 사례

doc_09는 원본 화면에서 성능 조건을 확인할 수 있지만 native text가 0자다.
이미지 객체 수 역시 0일 수 있으므로 이미지 개수만으로 스캔·비텍스트 여부를
판정하면 안 된다. kordoc은 `NEEDS_OCR`를 반환했다. OCR을 켜지 않고 보류한다.

doc_10은 실제 규격 영역이 다수 이미지로 구성돼 있어 모든 도구에서 선택한 CPU·
메모리 요구문을 복원하지 못했다. kordoc은 이미지 블록을 남겼으나 실행 성공과
`needsOcr: false`를 반환했다. **이 플래그를 분석 가능 판정으로 사용하면 안 된다.**
이미지·영역 위치와 파싱된 텍스트 범위를 확인해 미확인으로 보존해야 한다.
Docling의 성공·빈 표 출력도 규격 추출 성공이 아니다.

## 설정을 바꾼 추가 검증

| 변경 | 결과 | 채택 여부 |
|---|---|---|
| kordoc 구조 보존 옵션을 모든 형식에 동일 적용 | 원문 단서가 늘지만 PDF의 비규격 틀 표가 1행·50열로 커지는 사례 | 모든 형식에 일괄 적용하지 않음 |
| kordoc 형식별 보존 설정 | 원문 필터 제거를 줄이고 HWP/HWPX의 원본 구조 보존 옵션 적용, 핵심 내용 유지 | 현재 권장 기본 후보 |
| PyMuPDF `sort=True`와 스타일 span 보존 | 정상 텍스트 PDF 3개의 확인 문자열 유지, 이미지 규격은 복구 불가 | 사전검사·근거 비교에 사용 |
| PyMuPDF의 수동 구간 crop | 중첩 표를 18행·7열로 잘못 나눔 | 자동 대체 경로로 채택하지 않음 |
| pdfplumber 짧은 선·join 허용값 및 strict line 전략 변경 | 중첩 표의 7행·3열 문제가 남음 | 이 사례의 개선 근거 없음 |
| Docling PDFium backend·backend text·cell matching 두 설정 | 일부 어순은 개선되지만 셀 합침·순서 문제가 남음 | 기본 파서 대체 근거 없음 |

수동 crop은 원문 정답 위치를 입력한 진단이므로 자동 탐지 성능으로 집계하지 않았다.
원문 값을 알고 표를 강제로 맞추거나 결과를 LLM으로 조용히 수정하지 않았다.

### 권장 kordoc 설정과 재현성

공통으로 `ocr: false`, `formulaOcr: false`, `images: false`,
`removeHeaderFooter: false`, `dedupeRunningHeaders: false`를 명시한다.
이미지 바이트를 싣지 않아도 그림 위치 표시는 보존되는지 검증한다.
HWP/HWPX에는 `layoutTables: "keep"`, `keepTrailingEmptyCols: true`,
`keepEmptyParagraphs: true`를 적용한다. PDF에는 후행 빈 열 보존을 일괄 적용하지 않는다.

10개 파일을 각각 3회 반복했다. 텍스트·표·좌표·배열 순서는 동일했고, PDF 4개는
내부 글꼴 토큰 `g_dN_fM`이 실행마다 달랐다. 원본 JSON의 완전 동일은 6/10개,
차이가 내부 글꼴 토큰에 한정되는 것은 4/10개였다. 해당 차이의 경로를 모두 기록했다.
내부 글꼴 토큰을 원문 요소의 Stable ID나 실제 글꼴 가족명으로 사용하지 않는다.

PDF `bbox`는 좌표계를 명시해야 한다. 확인한 kordoc PDF 표는 하단 기준 y 좌표였고
원본 렌더와 대조해 `top = page_height - y - height`로 상단 좌표에 대응했다.
숫자 네 개만 저장하거나 다른 도구 좌표와 그대로 비교하지 않는다.

## 자동 분석 통과와 남은 검증

이 결과는 파서 선택을 위한 개발 진단이다. 원문 화면 전체·모든 구간을 평가한
문서는 없으므로 전체 문서 자동 분석 통과를 선언하지 않는다. 다음 항목을 실제
어댑터 구현과 추가 표본에서 확인해야 한다.

- 원본 anchor와 native 출력 참조를 연결하고 각 좌표계·페이지 근거를 명시한다.
- 제목·section 관계가 native에 없는 경우 추론 여부와 근거를 구분한다.
- 이미지·비텍스트·빈 표·낮은 텍스트·입력 문제를 독립적으로 감지한다.
- HWP 원본 화면, 활성 병합 HWPX, DOCX의 더 복잡한 표, XLSX, 정상 추출 가능한 연속 표를 추가 검증한다.
- 공통 JSON 변환 후에도 원본 출력에서 보존되던 셀·숫자·단위·근거가 남는지 별도 평가한다.

검수 결과가 부족한 영역을 자동으로 비규격으로 분류하지 않는다. 파싱 품질과
`document_qualification`의 실제 요구규격 포함 판단, 첨부 선별 Precision은 별도 지표다.

## hwp-hwpx-parser 추가 비교

`pyhwp`와 `hwp-hwpx-parser`는 다른 도구다. 앞서 비교한 pyhwp는 HWP v5의
XML 교차 확인에 사용했고, 후자는 HWP·HWPX 통합 Reader다. 설치한 버전 1.0.0을
doc_03·05·06·07에 실행했으며 4개 모두 실행상 성공했다. 원본·현재 본문·변경 추적
기준은 앞선 비교와 동일하다. Python 격리 환경에만 의존성을 추가했다.

| 항목 | 실제 관측 |
|---|---|
| HWP 텍스트 | 확인한 CPU·RAM 문구를 보존 |
| 표 구조 출력 | 공개 `TableData`에 2차원 문자열 `rows`만 있고 rowSpan·colSpan·원본 좌표·table ID가 없음 |
| HWP 병합 표 | doc_05의 논리 6열 외부 표가 첫 행 4개 셀로 표현돼 `col_count=4`. 병합 범위 없이 원래 논리 격자를 확정할 수 없음 |
| 변경 추적 HWPX | doc_06에서 삭제된 표까지 3개를 반환. 현재 표는 2개 |
| 현재 품목명 | 원본의 삽입 문구 `고성능 GPU 서버`가 해당 표의 1행·2열(0-based)에서 빈 문자열로 출력 |
| HWPX 활성 셀 대조 | doc_06은 17/21개 일치, doc_07은 10/10개 일치. 원본 현재 본문과 4개 셀 불일치 |

핵심 문자열이 몇 개 존재하는지와 실행 성공만 확인하면 이 오류를 놓친다. 변경 추적과
원본 셀을 대조해야 한다. 설치 버전의 공개 출력과 이 표본에 한정한 관측이며, 별도
adapter·후처리나 향후 버전의 개선 가능성을 부정하는 것은 아니다. 현재는 이 도구로
기본 파서를 교체할 근거가 없으며 **kordoc + 형식별 원본 검사** 권장안을 유지한다.

추가 결과는 `hwp_hwpx_parser_runs.json`, `hwp_hwpx_parser_cell_checks.json`,
`hwp_hwpx_parser_verification.json`과 `outputs/hwp_hwpx_parser/`에 보관했다.
추가 회귀·설정 확인 4개를 통과했다. 이것은 도구 품질이 통과했다는 뜻이 아니라
위 오류와 제한이 동일 원본에서 재현됐다는 뜻이다.

## 재현 자료

실험 루트는 `.artifacts/procurement_specifications/parser_evaluation_2026_10_20/`다.
원본 본문·개인 연락처를 저장소 문서나 테스트 fixture에 복제하지 않는다.

| 자료 | 내용 |
|---|---|
| `sample_manifest.json`, `protocol.json` | 원본 참조·hash·선정 근거·기본 평가 조건 |
| `reference/` | PDF 렌더, 원본 XML, HWP 레코드 조사 |
| `reference_regions_v1.json`, `reference_regions_v2.json`, `reference_correction.json` | 중요 구간·원문 기준 수정과 사유 |
| `outputs/`, `*_runs.json` | 도구별 원본 출력·설정·실행 상태·시간 |
| `native_audit/`, `revision_aware_audit.json` | 원본 anchor와 변경 추적 검사 |
| `native_cell_crosswalk.json`, `native_cell_summary.json` | 현재 셀 121개와 출력 셀 연결·텍스트 비교 |
| `pdf_tuning.json`, `docling_tuning.json`, `pymupdf_sorted_checks.json` | 추가 설정별 비교 |
| `reproducibility.json` | 3회 반복의 전체 차이 경로 |
| `manual_region_reviews.json`, `verification.json` | 39개 구간 진단과 hash·설정·원문 셀·재현성 등 무결성 확인 12개 |
| `python_environment.txt`, `environment.json`, 실행 스크립트·로그 | 격리 환경·버전·재실행 근거 |
