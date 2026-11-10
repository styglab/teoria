# Kory Parser

한국어 문서, PDF, Office 파일에서 텍스트와 표를 추출하는 Python 라이브러리입니다.
문단·목록·병합 셀과 원문 위치를 구조화된 데이터로 읽고, JSON과 Markdown으로 저장할 수 있습니다.

- 여러 문서 형식을 하나의 `parse()` API로 처리
- 표의 행·열·병합 구조와 문서별 원문 참조 제공
- Python API와 CLI 지원, 이미지 OCR 선택 사용

## 목차

- [설치](#설치)
- [빠른 시작](#빠른-시작)
- [지원 형식](#지원-형식)
- [CLI](#cli)
- [주요 옵션](#주요-옵션)
- [문서와 문의](#문서와-문의)
- [라이선스](#라이선스)

## 설치

Python **3.11 이상**이 필요합니다. 현재 GitHub 소스에서 설치할 수 있습니다.

```bash
pip install "git+https://github.com/styglab/kory-parser.git"
```

OCR을 사용하려면 추가 의존성과 함께 설치합니다.

```bash
pip install "kory-parser[ocr] @ git+https://github.com/styglab/kory-parser.git"
```

## 빠른 시작

```python
import json
from pathlib import Path

from kory_parser import parse

result = parse("document.hwpx")
if not result.success:
    raise RuntimeError(result.error_code)

print(result.markdown)

Path("document.md").write_text(result.markdown, encoding="utf-8")
Path("document.json").write_text(
    json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
    encoding="utf-8",
)
```

`parse()`는 파일 경로 또는 `bytes`를 받아 `ParseResult`를 반환합니다.

| 속성 | 내용 |
|---|---|
| `blocks` | 문단·제목·목록·표·이미지 등의 구조화된 블록 |
| `markdown` | Markdown 본문 |
| `warnings` | 파싱 진단 코드와 원문 참조 |
| `error_code` | 실패 원인 코드 |
| `to_dict()` | JSON으로 저장할 수 있는 결과 사전 |

## 지원 형식

| 형식 | 추출 대상 |
|---|---|
| HWP·HWPX·HWPML | 문단, 목록, 표, 병합·중첩 셀 |
| PDF | 텍스트, 좌표, 읽기 순서, 괘선 표 |
| DOCX | 본문, 번호 목록, 표 |
| PPTX | 슬라이드 텍스트, 표, 도형 텍스트 |
| XLS·XLSX | 셀, 시트, 병합 셀, 도형 텍스트 |
| 이미지 | OCR 텍스트 |

추출 범위와 정확도는 원문 구조에 따라 달라집니다. 스캔 문서는 OCR이 필요하며,
PDF의 복잡한 레이아웃이나 표는 결과 확인이 필요합니다.

## CLI

JSON으로 저장:

```bash
kory-parser document.hwpx -o parsed.json
```

Markdown으로 저장:

```bash
kory-parser document.pdf --format markdown -o document.md
```

이미지에 OCR 적용:

```bash
kory-parser scan.png --ocr -o scan.json
```

전체 옵션은 `kory-parser --help`로 확인할 수 있습니다.

## 주요 옵션

`ParseOptions`로 OCR, PDF 페이지 선택, 시트 출력 등을 지정합니다.

```python
from kory_parser import ParseOptions, parse

result = parse("document.pdf", ParseOptions(pages=(1, 2)))
```

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `ocr` | `False` | 이미지와 스캔 PDF의 OCR 활성화 |
| `images` | `False` | 지원되는 이미지 블록에 이미지 데이터 포함 |
| `pages` | `None` | PDF에서 읽을 페이지 번호 지정. 첫 페이지는 `1` |
| `sheet_layout` | `"compact"` | 스프레드시트의 빈 행·열을 줄임. `"source"`로 원본 배치 사용 |
| `recover_numbered_structure` | `True` | HWPX의 수동 번호·들여쓰기를 목록 계층으로 복원 |

OCR 모델은 최초 실행 시 다운로드될 수 있습니다. `ocr=True`는 OCR 추가 의존성을
설치한 환경에서 사용합니다.

## 문서와 문의

- [설치·옵션·지원 범위와 제한](docs/usage.md)
- [변경 이력](docs/change_history.md)
- [버그 제보와 기능 요청](https://github.com/styglab/kory-parser/issues)

버그를 제보할 때는 파서 버전, 파일 형식, 실행 코드, 기대한 결과와 실제 결과를 알려주세요.
공유 가능한 최소 재현 문서가 있으면 문제를 확인하는 데 도움이 됩니다.

## 라이선스

[AGPL-3.0-or-later](LICENSE) · [Third-party notices](NOTICE)
