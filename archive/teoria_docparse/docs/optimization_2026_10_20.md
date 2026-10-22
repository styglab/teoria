# PDF 성능 최적화 — Python 0.4.0

2026-10-20. `archive/teoria_docparse/` 안의 독립 설치 패키지만 변경했다. 이 버전의
목표는 **추출 결과를 보존하면서 처리 시간을 줄이는 것**이다. 본문·표 정확도나
OCR 품질을 새로 높인 버전으로 설명하지 않는다.

## 병목과 변경

가장 느린 표본 `corpus_013`을 warmup 뒤 cProfile로 조사했다. 기존 MuPDF 경로에서
문자 중복 제거가 프로파일 시간의 약 절반이었다. pdfplumber 0.11.10의 `dedupe_chars`
마지막 단계가 각 글자마다 `chars.index`로 전체 입력 목록을 다시 검색하는 것이 원인이었다.

- **중복 제거**: 글자·글꼴·크기·방향에 따른 그룹, Y/X의 연속 클러스터, 위·왼쪽 우선과
  입력 순서 tie break는 유지한다. 살아남는 입력 인덱스를 표시하고 한 번에 순서를 복원한다.
  마지막 단계의 이차 탐색을 제거했다. 변경한 구현은 `pdf_text.py`에 있다.
- **셀의 글자 검색**: 페이지 글자 중심을 Y 좌표로 인덱싱한다. 셀마다 전체 페이지를
  검색하지 않고 해당 Y 범위와 X 경계 안의 글자만 선택한다. 원래 입력 순서와 셀의
  경계 포함 규칙을 보존한다. 중첩 표와 페이지 경계의 상자도 이 인덱스를 재사용한다.
- **조합 번호**: 원형 글리프마다 모든 글자를 훑는 대신, 숫자 글자만 공간 인덱스에서
  조회한다. 원형의 오른쪽·아래 경계에 정확히 놓인 숫자를 포함하는 기존 규칙도 유지한다.
- **MuPDF 도형**: `get_drawings()`의 Point/Rect wrapper 생성을 거치지 않고 compact
  `get_cdrawings()` 좌표 tuple을 사용한다. 음수 방향 사각형은 같은 좌표로 정규화한다.
- 여러 셀로 구성된 그룹에서 불필요하게 단일 셀 테두리를 검사하던 호출도 제거했다.

문서의 파싱 결과를 파일 hash별로 캐시하지 않는다. 서로 다른 호출 사이에서 이전 결과를
재사용해 측정 시간을 줄이지 않는다. 기본 pdfminer 경로와 선택 MuPDF 경로 모두 같은
문자 처리 최적화를 사용한다. 추가 runtime 의존성은 없다.

## 결과 보존 검사

- **67개 테스트 통과** (`pdf_native` extra 포함), Ruff 정적·형식 검사 통과.
- 무작위 소형 glyph 배열을 고정 seed로 생성해 tolerance 0/0.3/1에서 pdfplumber의
  기존 함수와 전체 결과를 대조했다. 연속 클러스터, 좌표 오차, 글꼴·크기·방향 구분,
  tie break와 셀 경계·원형 경계를 검증한다.
- 실제 문서 **68개 × 2개 경로**를 다시 파싱했다. `parser_version`만 제외한 **전체
  JSON이 각 경로의 0.3.0 결과와 68/68개 일치**했다. 본문, Markdown, 표/셀/병합,
  좌표, metadata, 경고와 실패 상태도 비교 대상에 포함했다.
- 검사 근거는 [전체 결과 보존 기록](../verification/results/preservation_68_v0_4_0.json)에 있다.
  문서별 입력 hash와 버전을 제외한 출력의 canonical SHA-256을 남겼다.
- 원본 kordoc 4.22.15와의 본문·표·셀 일치는 **48/68개로 유지**된다.
  이번 기능 비교에서는 기존에 고정한 원본 JSON을 재사용했다. 원본 엔진은 아래 속도
  검증에서 29개 PDF를 새로 반복 실행했다.
- [기본 경로 비교](../verification/results/corpus_68_v0_4_0.json),
  [MuPDF 경로 비교](../verification/results/corpus_68_native_v0_4_0.json).
  이 파일에 있는 후보의 단발 시간은 동시 correctness 검사 중 측정한 값이다.
  속도 판단에는 아래 별도 반복 측정만 사용한다.

## 반복 측정

| 엔진 | 문서별 중앙값 합계 |
|---|---:|
| Python 0.3.0 MuPDF | 25.291초 |
| **Python 0.4.0 MuPDF** | **10.105초** |
| kordoc 4.22.15 | 11.863초 |

이 표본에서 이전 Python보다 **2.50배**, 원본보다 **1.17배** 빠르다.
원본 대비 처리 시간은 **14.8% 감소**했다. **19/29개**에서 원본보다 빨랐으며,
나머지 10개는 원본이 더 빠르다. 특히 `corpus_004/005/027` 등에서 차이가 남는다.
따라서 모든 문서에서 빠르다고 주장하지 않는다.

[전체 반복 측정 및 문서별 결과](../verification/results/benchmark_summary_v0_4_0.json)에
세 번의 측정, 엔진 버전과 Python 의존성, 입력 hash, 문서별 차이를 연결했다.

기존 6개를 골라 다시 재는 대신, corpus에 있는 PDF 중 **양쪽이 모두 성공한 29개 전체**를
사용했다. 텍스트 없는 PDF 2개와 암호 PDF 1개는 제외했다. OCR, 수식 OCR, 이미지 바이트
추출은 껐으며, PyMuPDF 1.27.2.3 및 Python 의존성을 두 Python 버전에서 동일하게 고정했다.

각 엔진에서 문서당 warmup 1회 후 3회 실행했다. 엔진은 같은 머신에서 순차 실행하며,
표의 값은 **문서별 중앙값의 합**이다. 입력 읽기, 모듈 import, 결과 JSON 변환·검사는
측정 구간 밖이다. 각 반복 뒤 추출 결과가 기준 결과와 같은지도 확인했다. 원본은
PDF.js가 실행마다 바꾸는 `fontName`의 `g_d<number>_` 문서 식별자만 정규화했다.
폰트 index, 본문·격자·스타일·좌표 등 나머지 데이터는 비교에서 제외하지 않았다.

3회 반복으로 통계적 우월성을 확정하지 않는다. 개발에 사용한 같은 corpus이며 독립
holdout이 아니다. CPU affinity나 머신 전체의 자원 격리를 적용하지 않았다. 결과는
warm 상태의 parse 시간이며 콜드 CLI 시작, Prefect Job 시작·큐 대기·전체 처리량을
측정한 값이 아니다. 표본별 시간과 느려진 문서도 상세 JSON에 공개한다.

측정 코드: [Python](../verification/benchmark_python.py),
[원본 kordoc](../verification/benchmark_reference.mjs).

## 사용과 패키지

위 MuPDF 성능을 재현하려면 선택 의존성과 경로를 지정한다. 기본 경로의 속도와 혼동하지 않는다.

```bash
uv sync --project archive/teoria_docparse --locked --extra pdf_native --group dev
uv run --project archive/teoria_docparse --locked --extra pdf_native \
  teoria-docparse document.pdf --pdf-backend pymupdf -o parsed.json
```

```python
from teoria_docparse import ParseOptions, parse

result = parse("document.pdf", ParseOptions(pdf_backend="pymupdf"))
```

PyMuPDF의 AGPL/Artifex 상용 라이선스 선택은 [이전 안내](usage.md)와 동일하다.
기본 경로는 PyMuPDF를 설치하지 않아도 실행된다. 실제 Prefect Flow나 운영 배포에는
연결하지 않았다. 기존의 복잡한 PDF 표 연결·읽기 순서, 원본 자체의 오탐, OCR이 필요한
문서의 차이는 그대로 남는다. 속도 향상을 전체 정확도 향상으로 표현하지 않는다.

0.4.0 wheel·sdist를 빌드하고 기본/선택 엔진의 격리 환경에서 설치·파싱을 확인했다.
소스와 비교 결과의 hash, license·문자표·새 모듈 포함, 문서 원문 제외도 확인했다.
[소스·의존성](../verification/provenance_v0_4_0.json),
[배포물과 설치 검증](../verification/build_artifacts_v0_4_0.json)을 함께 보존한다.
