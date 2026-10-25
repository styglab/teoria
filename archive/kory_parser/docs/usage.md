# Kory Parser 사용법과 kordoc 비교

지속 평가와 Codex 개선 작업은 [평가·개선 순환](evaluation_loop.md)과
[실제 공고 첨부문서 사이클](public_procurement_cycle.md)을 따른다.

프로젝트 이름은 **Kory Parser**이며, 기존 `teoria_docparse`에서 `kory_parser`로 변경했다. Python import는
`kory_parser`, 설치 패키지와 파싱 CLI는 `kory-parser`, 비교 CLI는
`kory-parser-compare`다. 기존 이름의 import·CLI 별칭은 제공하지 않는다.
원본 kordoc의 이름·저작권·라이선스 표기는 유지한다.

`kory-parser` 0.9.13은 kordoc 4.22.15를 기준으로 만든 **실험용 독립 Python
패키지**다. Python SDK로 JavaScript 엔진을 호출하는 방식이 아니다. 파싱은 Python과
설치된 native dependency에서 수행한다. 원본 비교 명령에서만 Node.js를 사용한다.

사용자 요청에 따라 `archive/kory_parser/`에 격리했다. 루트 uv workspace와
Platform·Pipelines의 의존성, API, Registry, Prefect 배포에 연결하지 않았다.
Git에는 이 패키지의 소스·테스트·설명 문서만 제한적으로 포함한다.
환경과 원문·검증 산출물은 [Git 보관 범위](git_storage.md)에 따라 로컬에 남긴다.

## 설치와 호출

저장소 루트에서 실행한다.

```bash
uv sync --project archive/kory_parser --locked --group dev
uv run --project archive/kory_parser --locked kory-parser document.hwpx -o parsed.json
```

일반 Python 환경에는 `pip install ./archive/kory_parser` 또는 빌드한 wheel을
설치한다. Prefect 의존성은 파서에 포함하지 않는다.

```python
from kory_parser import ParseOptions, parse

result = parse("document.hwpx", ParseOptions(ocr=False, images=False))
if not result.success:
    raise ValueError(result.error_code)

native_json = result.to_dict()
markdown = result.markdown
for block in result.blocks:
    if block.table:
        for row in block.table.cells:
            for cell in row:
                if not cell.covered:
                    print(cell.text, cell.row_span, cell.col_span)
```

`parse()`는 CPU 작업을 수행하는 동기 함수다. 향후 Prefect에서 사용할 때는 동기
Task/별도 프로세스에 넣고 동시 실행 수와 실행 시간을 제한한다. 비동기 API에서
직접 실행하거나 `async def`만 붙이지 않는다. 현재 운영 연결은 하지 않았다.

## 구현 범위와 호환성

전체 **문서 읽기 형식**을 대상으로 구현했지만, 원본의 모든 기능과 동등한 이식이
완료된 것은 아니다. 원본의 문서 생성·편집·렌더·MCP 기능은 이 패키지의 범위가 아니다.

| 형식/기능 | 현재 구현 | 검증 범위/남은 차이 |
|---|---|---|
| HWP 5.x | OLE, DEFLATE, 본문 레코드, 문단·표·병합·중첩, 문단 번호와 글머리표 | 기존 실제 HWP 문서와 비교. 21개 실제 문서의 정규화 본문·표·셀 일치. 메모 제외, 조합 번호, 머리말/꼬리말 보완. 전체 글자 서식·필드 호환 미완료 |
| HWP 3.x | 헤더, 압축, 조합형 문자, 문단·제어문자·표 기하 복원 | 합성 단위 표본만 검증. 그리기 개체·추가 이미지 정보·옛한글 전체 품질 미검증 |
| HWPX | ZIP/XML, 현재 본문 변경 추적, 표 ID·셀 주소·병합·중첩, 번호/글머리표, 기본 span | 실제 표본 대조. 물리 페이지 조판과 레이아웃 표 해체는 미이식 |
| HWPML | XML 본문·문단·표·병합·중첩 | 합성 단위 표본. 원본 전체 코퍼스 검증 없음 |
| DOCX | 문서 순서, 현재 본문, 표·병합·중첩, 기본 글자 서식·제목, 자동 번호·글머리표·스타일 상속 | 기존 문서와 W3C 공개 Word 2개, 번호 재시작·override 합성 검증. numStyleLink, 전체 번호 형식, 각주/미주·header/footer 전체 처리 미이식 |
| XLSX | workbook 관계 순서, 공유/인라인 문자열, 셀 주소·값·병합, 빈 서식 셀을 버리는 worksheet XML 순차 읽기 | 기존 2개와 새 공고의 2개 검증. 기본 compact 격자와 원본 셀 주소 보존. sheet_layout="source"로 빈 행·열 유지. 날짜/수치 표시 형식 미이식 |
| XLS | xlrd로 BIFF 값·병합·sheet 순서 | 합성 BIFF 표본. 표시 형식 전체 호환 미검증 |
| PPTX | slide 관계 순서, 문단·표·병합·그룹·이미지 자리, 숨긴 slide 제외 | 합성 단위 표본. 제목 역할·발표자 노트·이미지 바이트 추출 미이식 |
| PDF | MuPDF 문자·선·클리핑·음영 추출, 자체 Python 표·중첩·부분 격자 복원, MuPDF OCR 렌더 | 실제 문서 비교. PDF.js/OpenDataLoader 계열 로직의 완전 포팅이 아니다. 일부 무괘선 표, 페이지 간 표 연결, 한국어 줄 복원, 복잡한 읽기 순서에 차이 |
| 이미지 | PNG/JPEG/GIF/BMP/TIFF/WebP 인식, 이미지 위치/바이트, 선택 OCR | OCR 제외 시 `NEEDS_OCR`. 한국어 합성 이미지 OCR smoke 별도 실행 |
| OCR | 선택 RapidOCR/ONNX, Korean PP-OCRv5 recognition, 좌표·신뢰도 | 원본 kordoc OCR 모델/전처리와 동일하지 않음. 내장 HWP/Office 그림 OCR·수식 OCR·정확도 평가 미완료 |
| 수식 | HWP/HWPX 원본 수식 script 보존 및 진단 | LaTeX 변환과 수식 OCR 미이식 |
| 보호/손상 문서 | 암호·DRM·잘못된 구조의 명시적 실패 | password 복호, HWP 배포용 복호, 손상 ZIP/CFB 복구 미이식 |

실제 표본과 테스트가 없는 형식에 대해 원본과 같은 품질이라고 주장하지 않는다.
상태/옵션을 맞춘 최초 비교는 [0.1.0 검증 기록](comparison_2026_10_20.md), 수정 후 결과는
[0.2.0 차이 수정·검증 기록](difference_fixes_2026_10_20.md), [0.3.0 PDF 고도화 기록](pdf_upgrade_2026_10_20.md), 최신 성능 결과는
[0.4.0 최적화 기록](optimization_2026_10_20.md)을 참고한다.
원문 기준 구조 품질은 [0.5.0 개선 기록](quality_upgrade_2026_10_20.md)과
[0.6.0 새 공고 다운로드·비교 평가](../verification/results/public_samples_v0_6_0.html)에 있다.
0.6.0은 신규 공고의 문서로 XLSX 빈 서식 셀, PDF 중복 표, 반복 헤더의 번호 표 연결,
두 열 헤더 아래 보이지 않는 값·단위 분할을 개선했다. OCR은 제외했다.

## 결과 계약

- 0.9.13은 BIFF8 XLS의 외부 참조 시트명에서 잘못된 UTF-16이 발견되면 해당 이름의
  해석을 생략하고 저장된 로컬 셀 값을 읽는다. `XLS_EXTERNAL_NAMES_SKIPPED` 경고를
  남기며, 복구 중 정의 이름 평가도 생략되면 별도 경고로 알린다. 원본 바이트·xlrd 전역
  상태를 바꾸거나 수식을 재계산하지 않는다. URL·공유 문자열·실제 셀의 문자 오류와
  기존 시트 선택·셀 수 제한을 유지한다. 실제 실패 파일의 5개 시트와 숫자 캐시315개를
  대조했고 기존 고정 회귀160개 출력도 보존했다.

- 0.9.12는 이미지 OCR에서 빠진 여는 꺾쇠 따옴표와 ASCII 대괄호로 읽은 닫는 기호를
  원문 획으로 확인한다. 수평 줄의 첫 인식 문자 앞과 닫는 문자 좌표에 서로 대응하는
  L자 획이 함께 있을 때만 `「」`를 복원한다. 일반 대괄호나 불명확한 모양은 보존한다.
  밝은 바탕의 짙은 획과 정방향·180도 회전을 검증했으며 임의의 글꼴·기울기나
  어두운 바탕의 밝은 글자에 대한 일반적 우위를 보장하지 않는다.

- 0.9.11은 이미지 OCR이 ASCII 따옴표로 읽은 문자를 원문 픽셀의 획 모양으로 점검한다.
  분리된 곡선 획이 뚜렷할 때만 여는/닫는 따옴표를 복원하며 직선·불명확한 기호와
  인식 단어·공백은 보존한다. 따옴표가 있는 줄만 문자 좌표를 계산하는 RapidOCR adapter를
  사용한다. 고정 환경의 RapidOCR 3.10.0에서 검증했으며 기호 전체 복원이나 새 글꼴의
  보편적 정확도를 보장하지 않는다. PDF OCR 경로에는 이 처리를 적용하지 않는다.

- 0.9.10은 `ParseOptions(ocr=True)`의 이미지 OCR에서 한국어 인식 신뢰도로 0/180도 페이지
  방향을 선택하고 원본 픽셀 좌표로 결과를 돌려준다. 검출·인식 모델을 명시하고 엔진은
  작업 스레드마다 하나씩 재사용한다. 이미지 엔진은 intra-op 8 / inter-op 2개 thread를 쓰므로
  호출 측 동시 실행 수도 제한한다. PDF OCR 경로와 기본 OCR 비활성 계약은 유지한다.
  OCR은 `uv sync --locked --group dev --extra ocr`로 optional dependency를 설치해야 한다.
  개발용 `python -m evaluations.benchmark --ocr`는 양쪽 엔진에 OCR 활성화를 명시한다. 혼합 방향 문서·전체 레이아웃과
  메모리·CPU 비용의 우위는 검증하지 않았다.

- 0.9.9는 원본 격자가 셀 수 제한을 넘는 XLS를 `sheet_layout="compact"`에서 빈 행·열을
  압축해 읽는다. 실제 출력 격자와 저장하는 셀은 기존 `max_cells` 제한 안에 있어야 하며,
  원본 셀 주소와 병합 관계를 보존하고 `XLS_COMPACTED_GRID` 경고를 남긴다.
  제한 안의 기존 XLS 출력과 `sheet_layout="source"`의 격자 제한은 유지한다.

- 0.9.8은 BIFF8 XLS의 이름 정의 수식 해석에서 `IndexError`가 발생하면 이름 정의를
  평가하지 않는 별도 workbook으로 저장된 셀 값을 읽는다. 원본 바이트와 xlrd 전역 상태를
  바꾸지 않으며 `XLS_DEFINED_NAMES_SKIPPED` 경고로 복구 사실을 알린다.
  수식을 재계산하지 않고 기존 시트 선택·셀 수 제한을 유지한다. 정상 XLS는 기존 경로로 읽는다.
  실제 실패 문서의 4개 시트와 원본 숫자 캐시 50개를 점검했고 고정 원문 160개의 출력은 보존했다.

- 0.9.7은 DOCX의 `ganada` 자동 목록 번호 중 기본 `가`부터 `하`까지(1~14)를 복원한다.
  목록별 카운터, 하위 번호 재시작과 시작값 override를 유지하며, 확인하지 못한 범위는
  기존 placeholder와 `UNSUPPORTED_DOCX_NUMBER_FORMAT` 경고를 남긴다.
  공통 표 생성 단계는 배치할 셀을 먼저 채우고 실제 빈 위치에만 빈 셀을 만든다.
  병합·겹침 검증, 빈 셀의 독립성과 기존 출력 계약은 유지한다.
  실제 DOCX의 원문 번호 포함 문장 33개와 고정 원문 160개를 재검증했다.

- 0.9.2는 실제 공고 첨부문서에서 확인한 PDF clipping frame의 표·본문 중복을 제거했다.
  [30개 실문서의 기존 버전·kordoc 비교](public_procurement_cycle_2026_10_23.md)에서
  품질·회귀·시간 기준을 확인한 뒤 반영했다.

- 0.9.1은 선택한 형식의 파서만 로딩한다. 손상된 파일은 `INVALID_FILE`, 예상치 못한
  내부 조회·인덱스 오류는 `INTERNAL_ERROR`로 구분한다. 후자는 파서 점검이 필요한 결과다.
  제안서 작성 서식 아래의 목차 후보는 쪽 번호나 본문 연결 근거가 있을 때 유지한다.
  목차 옵션은 계속 기본 꺼짐이며, 기존 문단·표·Markdown 구조는 보존한다.
  변경과 회귀·시간 측정 범위는 [0.9.1 개선 기록](refinement_2026_10_22.md)에 있다.
- 0.9.0은 `ParseOptions(extract_contents=True)` 또는 CLI `--contents`를 지정하면
  명시적인 목차 구간에서 실험용 `ParseResult.contents`를 제공한다. 기본값은 꺼짐이다.
  제안서 작성 양식의 목차 오인과 일부 시간 지연이 확인되어 기본 실행에는 추가하지 않았다.
  각 항목은
  `number`, `title`, `level`, `parent_id`, `printed_page_label`, 원문 `source`/`regions`와
  본문 `target`/`target_status`를 갖는다. 목차를 찾지 못하면 JSON에서 `contents`를 생략한다.
  기존 `blocks`·표·Markdown과 별도로 제공하는 구조이며 제목 번호에서 계층을 읽고,
  PDF는 문단 결합 전 물리 줄과 쪽 번호의 점선/열 간격을 사용한다.
  참조 쪽 번호만으로 물리 쪽을 추측하지 않는다. 같은 번호·제목의 본문 후보가 유일하면
  `resolved`, 여러 곳이면 `ambiguous`, 근거가 없으면 `unresolved`다.
  명시적인 목차 제목이 없는 개요, 누락된 이미지 글자와 모든 Word TOC field 형식의
  완전한 지원을 뜻하지 않는다. `level=None`은 계층 미확정이다.
  비교 수치와 오탐·시간 제한은 [0.9.0 목차 검증 보고서](toc_upgrade_2026_10_22.md)에 있다.
- Python API와 JSON은 `snake_case`를 사용한다. 원본 JavaScript의 wire JSON과 별도 계약이다.
- `Block`은 문단·제목·목록·표·이미지·구분선, `Table`은 격자, `Cell`은 anchor와 span을 담는다.
- 병합이 덮는 위치는 `covered=True`다. 값을 갖는 anchor 셀과 혼동하지 않는다.
- 중첩 표·그림은 `Cell.blocks`에 보존하며 `Cell.text`는 평탄화 표현이다.
- `keep_trailing_empty_cols=None` 기본값은 HWP/HWPX/HWP3에서 유지, 나머지 형식에서는 제거다.
  `True`/`False`를 지정하면 명시한 선택을 따른다.
- PDF 표의 `geometry_source`는 `clip`/`fill`/`line`/`text`로 추출 근거를 나타낸다.
- PDF `source.bbox`는 `(left, top, right, bottom)`, 상단 원점, pt 단위다.
  원본 kordoc의 `x/y/width/height`와 그대로 비교하지 않는다.
- 0.8.0에서 복원한 PDF 문단·여러 줄 제목은 각 물리 줄의 좌표를 선택 필드
  `Block.regions`에 남긴다. `source.bbox`는 그 영역의 합집합이다. 빈 `regions`는
  JSON에서 생략한다. JSON schema version 1의 선택 필드 추가다.
- PDF/DOCX 목록의 `level`은 1부터 시작하며 Markdown에 들여쓰기를 반영한다.
  PDF는 좌표·글꼴에 근거한 추정이고 DOCX는 원본 numbering/outline 정의를 읽는다.
- HWP/HWPX의 `page_mode="section"`은 section 근사다. 물리 쪽 번호를 생성하지 않는다.
- 원본 파일 hash와 ZIP part/XML anchor 또는 HWP stream/record offset을 함께 보존한다.
- `success`는 실행 결과다. 실제 요구규격 포함, 모든 이미지 내용 복원, 전체 문서 품질 통과를 뜻하지 않는다.
- 이미지가 섞인 문서에는 `UNEXTRACTED_IMAGE_TEXT`가 남을 수 있다. 내용이 없는 PDF와
  이미지 입력은 OCR을 끄면 `NEEDS_OCR` 실패로 반환한다. 원본과 실행 상태가 다를 수 있다.
- ZIP 누적 전개 크기, XML node/깊이, DEFLATE 크기, 표 cell 예산을 제한한다.
  실행 시간 제한은 상위 Task/프로세스가 담당한다.
  XLSX worksheet는 값·수식이 없는 서식 셀을 순차 읽기 중 제거하며, XML node 예산은
  보존한 노드에 적용한다. ZIP 전개 크기·XML 깊이·표 cell 예산은 계속 적용한다.
  일반 XML 문서의 node 예산을 일괄 늘리지 않는다.
- PDF에서 동일 헤더·열 경계·연속 행 번호와 쪽 경계가 확인된 표는 반복 헤더를 제거해
  연결하며 `REPEATED_TABLE_HEADER_MERGED`를 남긴다. 목록 재시작과 새 본문은 연결을 막는다.
- PDF의 두 열 헤더 아래 값·단위가 보이지 않는 clipping 열로 나뉜 경우, 실제 내부
  세로선이 없고 행·텍스트가 안전하게 대응할 때 두 필드로 표현한다. 합친 셀의
  `blocks`에는 각 조각의 원래 좌표를 보존한다. 모든 무괘선 표의 열을 합치지는 않는다.
- 옵션을 조용히 무시하지 않도록 `ParseOptions`는 알려진 필드만 받는다. `ocr=True`는
  현재 PDF의 텍스트 없는 페이지와 이미지 입력에만 적용된다.

## 단일 PDF 엔진

0.7.0부터 PDF 추출과 OCR용 이미지 렌더링은 **MuPDF 하나**로 처리한다.
`pdfplumber`, `pdfminer.six`, `pypdfium2`와 `pdf_native` extra를 제거했다.
다른 PDF 엔진으로 되돌리는 경로는 없다. 표·중첩·병합·읽기 순서는 Python에서
복원한다. PyMuPDF의 `find_tables()` 결과로 전체 구조를 교체하지 않는다.
pdfplumber의 MIT 좌표 군집화·표 교차점 알고리즘 중 필요한 부분은 자체 모듈로
옮겼고, PDF 파일 해석 코드와 의존성은 포함하지 않는다.

```bash
uv sync --project archive/kory_parser --locked --group dev
uv run --project archive/kory_parser --locked kory-parser document.pdf -o parsed.json
```

```python
result = parse("document.pdf", ParseOptions(ocr=False))
```

회전 페이지의 문자·도형·클리핑·이미지에는 같은 회전 행렬을 적용한다.
Unicode 매핑이 없는 문자는 내장 글꼴의 명시적 cmap/글리프 이름과 검토한 윤곽
서명을 확인한다. 한컴바탕 기호 25종은 글꼴 계열과 전체 윤곽 hash가 일치할 때만
복원한다. 글리프 번호·문서명으로 치환하지 않는다. 빈 `.notdef`는 공백으로
버리지 않는다. 검증되지 않은 문자는 `�`와 `UNRESOLVED_PDF_GLYPH`로 남긴다.
글꼴 높이 정보가 비정상인 같은 baseline의 한글·한자는 실제 줄 정보를 사용해
묶고 원래 글자 좌표는 보존한다.

`ParseOptions.pdf_backend`와 숨긴 CLI `--pdf-backend`는 기존 MuPDF 호출 호환을
위해 `pymupdf` 값만 허용한다. `pdfplumber`를 요청하면 명시적으로 거절한다.
0.6.0의 두 엔진 비교 기록과 배포 파일은 당시 상태 그대로 보존한다.

PyMuPDF는 **AGPL 또는 Artifex 상용 라이선스**이며 0.7.0부터 필수 의존성이다.
[공식 라이선스 안내](https://pymupdf.io/licensing)를 참고한다. 자체 Python 코드의
라이선스와 의존성의 라이선스는 별도다. 최신 검증은
[0.7.0 단일 엔진 검증](../verification/results/single_pdf_v0_7_0.html)에 있다.

## 범용 문서 구조 복원

0.8.0은 특정 업무의 구성품 추출 대신 읽기 순서·문단 경계·제목/목록 계층을
개선했다. 다단 PDF는 원본 줄 식별자와 세로 여백을 확인해 열을 나누고,
전체 폭 제목·표를 경계로 읽기 순서를 정한다. 보이지 않는 배치용 표를 풀 때도
각 줄 좌표를 유지한다. 문단은 글꼴·줄 간격·본문 경계·첫 줄 들여쓰기·목록
시작을 함께 판단한다. 회전 글씨는 원래 방향으로 읽고 합자에서 겹친 글자들의
원래 순서를 보존한다. 코드 모양의 고정폭 줄은 합치지 않지만 코드 의미 분석과
완전한 원본 들여쓰기 복원을 제공하는 것은 아니다.

새 공개 파일 8개(W3C PDF/Word 2쌍, 논문 2개, GNU Make 매뉴얼, RFC 9110)를
원본 kordoc 4.22.15·Python 0.7.0·0.8.0으로 비교했다. PDF/Word 쌍은 같은 내용이므로
독립 내용군은 6개다. GNU Make와 RFC는 앞 24쪽을 선택했고 전체 원본도 보존했다.
개발에 사용하지 않은 논문·RFC 2개는 코드 동결 후 처음 열어 검증했다.

이 별도 검증의 원문 점검 22개에서 원본 5개, 0.7.0은 6개, 0.8.0은 20개를
통과했다. BERT의 `Abstract` 제목 누락과 URL이 포함된 세 번째 글머리표 분리는
남아 있다. 선택 항목 통과 수이며 전체 문서 정확도나 모든 형식에서의 우위를
의미하지 않는다. 기존 106개 고유 입력의 숫자·실행 상태와 기존 원문 구조 검사를
함께 확인했다. 구성품 평가는 이번 고도화의 목표나 점수에 포함하지 않았다.

평가에서 원본의 `listType`은 글머리표와 기본 최상위 깊이로 정규화해 두 계약의
표현 차이를 오류로 세지 않는다. 기존 공고 정답 문구에서 빠진 `국고`는 원문을
확인한 별도 정정 기록을 적용했고, 과거 정답과 보고서는 유지했다.
[0.8.0 비교 보고서](../verification/results/general_layout_v0_8_0.html)와
[원문 검증 항목](../verification/general_layout_labels_v0_8_0.json)에 근거가 있다.

```bash
archive/kory_parser/.venv/bin/python \
  archive/kory_parser/verification/general_layout_review.py \
  --runs archive/kory_parser/.artifacts/general_layout_0_8_0 \
  --labels archive/kory_parser/verification/general_layout_labels_v0_8_0.json \
  --output archive/kory_parser/verification/results/general_layout_v0_8_0.json
```

재실행에는 보관한 원문·세 버전의 원시 출력이 필요하다. 배포 파일에는 공개 원문이나
원시 파싱 결과를 넣지 않으며, SHA-256·출처·선택 범위와 집계 증거를 보존한다.

## 선택 OCR

```bash
uv sync --project archive/kory_parser --locked --extra ocr --group dev
uv run --project archive/kory_parser --locked --extra ocr kory-parser scan.png --ocr -o scan.json
```

OCR은 로컬 CPU에서 실행하지만 모델이 없으면 RapidOCR이 처음에 내려받는다. 문서
본문을 외부 OCR API로 보내지 않는다. 기본 recognition은 Korean PP-OCRv5 mobile이며
PDF OCR의 detection/분류 모델은 lockfile의 RapidOCR 기본 설정을 따르고 ONNX intra-op
thread는 2개다. 이미지 OCR은 PP-OCRv4 mobile 검출·한국어 PP-OCRv5 mobile 인식과
페이지 방향 판별을 사용하고 스레드별 엔진을 재사용한다(intra-op 8 / inter-op 2). 기존 68개 문서 일치 비교는 OCR을 껐다. 이후의
[규격서 원문 품질 평가](quality_evaluation_2026_10_20.md)에서는 이미지 관련 규격서
2개를 원본과 Python 모두 OCR을 켜서 추가 실행했다. 원본이 OCR 본문·표에서 우세한
사례와, 양쪽 모두 혼합 PDF의 핵심 규격을 놓친 사례가 확인됐다.

## 원본 비교 재실행

원본 npm 패키지 4.22.15가 설치된 디렉터리와 Node.js가 필요하다. manifest는 JSON
배열이며 각 항목에 `document_id`, `source_path`, `sha256`, `format`이 있어야 한다.
상대 원본 경로는 manifest 디렉터리 기준이다. 파일명/원본 내용은 비교 summary에 쓰지 않는다.

```bash
uv run --project archive/kory_parser --locked kory-parser-compare manifest.json \
  --reference-package /path/to/node_modules/kordoc \
  --bridge archive/kory_parser/verification/reference_bridge.mjs \
  --output archive/kory_parser/.artifacts/new_comparison
```

이미 있는 output 디렉터리는 덮어쓰지 않는다. 두 엔진이 동일한 SHA-256의 원본을
읽는지 검사한다. 원본은 `ocr/formulaOcr/images=false`를 사용하고 HWP/HWPX에는
`layoutTables=keep`, 빈 열·문단 보존을 명시한다. Python은 자체 보존 계약을 사용한다.
설정 이름이 같은 것과 엔진 내부 동작이 같은 것은 별개다.

결과에는 두 native JSON, 원본/출력 hash, Python 소스 hash, 실행 설정, 문서별
숫자 비교가 남는다. 원본 실행 전체는 기본 600초, Python 문서별 프로세스는 기본
120초 제한이다. `comparison.json`과 `comparison.md`는 원문 내용을 담지 않는다.
native JSON은 원문을 포함하므로 배포 artifact/공개 저장소에 넣지 않는다.

비교 항목은 정규화한 본문, 문자 multiset precision/recall/F1, 순서 유사도, 표의
행·열·anchor·span, 같은 순번 표의 셀 내용이다. 공백·줄바꿈·일부 Markdown 표시를
정규화하므로 원본 바이트/서식 전체 일치 지표가 아니다. 문자 F1=1이어도 순서나
셀 관계는 틀릴 수 있다. reference 자체의 누락까지 정답으로 보지 않는다.
표 개수가 달라지면 순번 대응도 어긋날 수 있으며 최적 매칭을 추정해 점수를 올리지 않는다.
빈 본문끼리의 수치 일치는 내용 추출 성공으로 세지 않는다.

이전 품질 개선은 [0.5.0 원문 기준 평가](quality_upgrade_2026_10_20.md)를 참고한다.
OCR 없이 중복 없는 88개를 비교하고, 원문 기준 97개 항목과 셀 221개를 검사했다.
확인한 제목 17개를 heading으로 표현하고 기존 표 오탐 5곳을 제거했으며,
독립 양식 20개와 실제 중첩 표·규격값을 보존했다. 추가 샘플의 두 쪽짜리 셀도 연결한다.
선택 항목의 진단이며 전체 문서 정확도 점수가 아니다.
이전 0.4.0의 OCR 포함 결과는 [규격서 10개 평가](quality_evaluation_2026_10_20.md)에 보존한다.

## 테스트와 배포 파일

```bash
uv run --project archive/kory_parser --locked pytest -c archive/kory_parser/pyproject.toml archive/kory_parser/tests
uv run --project archive/kory_parser --locked ruff check archive/kory_parser/src archive/kory_parser/tests
uv build --project archive/kory_parser --out-dir archive/kory_parser/dist
```

테스트 표본은 직접 만든 소형 XML·OLE·BIFF·PDF·이미지이며 실제 공고 원문을
배포 패키지에 포함하지 않는다. wheel에서 문자 mapping resource와 MIT 고지 및
rhwp license가 포함되는지도 별도로 확인했다. upstream 근거는 `NOTICE`와
`verification/provenance_v0_7_0.json`에 남긴다.
