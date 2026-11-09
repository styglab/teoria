# Kory Parser

문서의 문단·표·목록·원문 위치를 읽는 독립 Python 라이브러리다.
코드는 `archive/kory_parser/`에 있고 설치 이름은 `kory-parser`, import는 `kory_parser`다.
버전은 `src/kory_parser/version.py`가 기준이다. Teoria backend 의존성에는 합치지 않는다.
규격서 처리는 별도 Python 프로세스로 설치된 파서를 호출하며 실행기는
`TEORIA_SPECIFICATION_PARSER_PYTHON` 또는 처리 입력의 `parser_python`으로 지정한다.

## 설치·호출

저장소 루트에서 실행한다.

```bash
uv sync --project archive/kory_parser --locked --group dev
uv run --project archive/kory_parser --locked kory-parser document.hwpx -o parsed.json
```

```python
from kory_parser import ParseOptions, parse

result = parse("document.hwpx", ParseOptions(ocr=False, images=False))
if not result.success:
    raise ValueError(result.error_code)
native_json = result.to_dict()
markdown = result.markdown
```

`parse()`는 동기 CPU 작업이다. 비동기 API에서는 직접 호출하지 않고 별도 프로세스나
동시 실행·시간 제한을 둔 Task로 격리한다. 입력 크기·셀 수·XML 깊이 등의 제한은 `ParseOptions`를 따른다.

## 지원 범위와 제한

| 형식 | 제공하는 구조 |
|---|---|
| HWP·HWPX·HWPML | 문단·목록·표·병합·중첩·원문 위치 |
| DOCX·PPTX | 본문·기본 번호·표·도형 텍스트 |
| XLS·XLSX | 셀·병합·시트·도형 텍스트 |
| PDF | PyMuPDF 기반 텍스트·좌표·읽기 순서·괘선 표 |
| 이미지 | 선택적 OCR |

문서 생성·편집·렌더링은 범위 밖이다. 원본 kordoc의 모든 기능과 동등하지 않으며
임의 양식·표·OCR의 정확도를 보장하지 않는다. 진단 코드와 원문 근거를 확인한다.
`sheet_layout="compact"`는 빈 행·열을 줄이며 원래 셀 주소는 유지한다.
HWPX 수동 번호 계층 복원은 기본 활성이고 `recover_numbered_structure=False` 또는
CLI `--no-numbered-structure`로 끈다. 물리적 페이지 조판이나 업무 관계를 추정하는 기능은 아니다.

OCR은 추가 의존성을 설치하고 명시적으로 사용한다. 모델이 없으면 최초 실행 시 다운로드할 수 있다.

```bash
uv sync --project archive/kory_parser --locked --extra ocr --group dev
uv run --project archive/kory_parser --locked --extra ocr kory-parser scan.png --ocr -o scan.json
```

## 테스트·평가

```bash
uv run --project archive/kory_parser --locked --group dev \
  pytest -c archive/kory_parser/pyproject.toml archive/kory_parser/tests
uv build --project archive/kory_parser --out-dir /tmp/kory_parser_dist
```

합성 회귀 테스트는 저장소 파일만으로 실행한다. 실제 문서·OCR·kordoc 비교에는 별도 입력과 환경이 필요하다.
원문 정확도와 reference 일치율을 구분한다. 과거 수치를 현재 코드의 성능 보장으로 사용하지 않는다.

- [평가·개선 실행과 manifest](evaluation_loop.md)
- [실문서 표본·독립 검증·게이트](public_procurement_cycle.md)
- [적용된 변경 이력](change_history.md)

## 보관과 정리

Git에는 소스·테스트·작은 합성 코퍼스·평가 도구·lock·라이선스를 둔다.
실제 문서와 결과는 접근이 제한된 `.artifacts/`에 두고 환경·캐시·빌드 산출물은 커밋하지 않는다.
검증을 마친 사이클의 일반 성공 표본·동일 파싱 출력·재생성 가능한 중간 사본만 정리한다.
고정 회귀 원문·정답·문제 사례·사용 이력·manifest·hash·측정 요약·동결 소스는 유지한다.
미완료 검증·검토 중인 후보·실행 중인 환경을 삭제하지 않는다.

최종 보고서 명령이 기본 정리를 수행한다. 별도 정리는 패키지 디렉터리에서 다음과 같이 실행한다.

```bash
uv run --locked python -m evaluations.public_procurement.cleanup --cycle-root .artifacts/cycle_001
uv run --locked python -m evaluations.public_procurement.cleanup --cycle-root .artifacts/cycle_001 --apply
```

파서 동작을 바꾸면 patch 버전과 변경 이력을 함께 갱신한다. 문서 정리만으로 버전을 올리거나 배포하지 않는다.
저작권·의존성 라이선스는 `LICENSE`·`NOTICE`·`third_party/`를 유지한다.
