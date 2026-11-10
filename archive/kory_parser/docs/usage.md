# Kory Parser

문서의 문단·표·목록·원문 위치를 읽는 독립 Python 라이브러리다.
설치 이름은 `kory-parser`, import는 `kory_parser`다.
버전은 `src/kory_parser/version.py`가 기준이다.

## 설치·호출

PyPI에는 아직 게시하지 않았다. GitHub에서 설치한다.

```bash
pip install "git+https://github.com/styglab/kory-parser.git"
kory-parser document.hwpx -o parsed.json
```

개발 환경에서는 파서 프로젝트 루트에서 실행한다.

```bash
uv sync --locked --group dev
uv run --locked kory-parser document.hwpx -o parsed.json
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
uv sync --locked --extra ocr --group dev
uv run --locked --extra ocr kory-parser scan.png --ocr -o scan.json
```

## 빌드와 개발 검증

파서 프로젝트 루트에서 배포본을 빌드한다.

```bash
uv build --out-dir /tmp/kory_parser_dist
```

평가·회귀 테스트·벤치마크·Codex 개선 실행기는 개발 작업 공간에서 별도로 관리한다.
이 공개 저장소와 파서의 wheel·source distribution에는 포함하지 않는다.
파서 실행에는 평가 도구·Node.js·Codex가 필요하지 않다.

## 라이선스와 배포

현재 Kory Parser 배포 라이선스는 **AGPL-3.0-or-later**다. 전문은
[LICENSE](../LICENSE), 이식 범위와 출처는 [NOTICE](../NOTICE)에 있다.
기존 MIT 고지는 [kordoc](../third_party/kordoc_license.txt),
[rhwp](../third_party/rhwp_license.txt),
[pdfplumber](../third_party/pdfplumber_license.txt) 파일에 보존한다.
원저작자 이름은 프로젝트 이름 변경이나 배포 라이선스 변경으로 교체하지 않는다.
이번 정리는 저작권 소유권 변경을 뜻하지 않으며, 과거 MIT 배포본에 이미 부여된
허가를 철회하지 않는다.

AGPL은 상업적 사용과 유료 판매를 허용한다. 프로그램을 배포할 때는 라이선스에 따른
고지와 Corresponding Source 제공 조건을 지켜야 한다. 수정 버전을 네트워크로
제공하면 원격 사용자에게 해당 버전의 소스를 무료로 받을 수 있는 방법을 제공해야
한다. 적용 범위와 조건은 [AGPL 원문](https://www.gnu.org/licenses/agpl-3.0.html)의
5·6·13조를 따른다. 소스 범위는 결합 관계에 따라 판단하며, 별도 프로세스 호출만으로
의무가 해소되었다고 간주하지 않는다.

필수 PDF 엔진인 PyMuPDF/MuPDF는 AGPL 또는 별도 상용 라이선스로 제공된다.
이 패키지의 라이선스가 의존성에 대한 별도 상용 사용권을 부여하지는 않는다.
[PyMuPDF 공식 안내](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright)를
확인한다. 다른 의존성과 선택적 OCR 모델도 각자의 라이선스를 유지한다.

wheel과 소스 배포본에는 라이선스 전문과 원저작권 고지를 포함한다. 외부 배포·서비스
제공 전에는 실제 배포 버전의 소스, 필요한 빌드·설치 자료, 의존성 고지와 소스 제공
방법을 함께 준비한다. 이 저장소의 공개가 이 라이브러리를 사용하는 운영 서비스의
소스 제공 기능이나 라이선스 준수 절차를 대신하지는 않는다.

2026-11-10에 배포 메타데이터와 고지를 정리했다. 파싱 동작과 버전은 0.9.16을 유지하며,
이 기록은 PyPI 게시나 운영 재배포를 뜻하지 않는다.
