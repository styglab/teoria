# OCR 제외 구조 품질 개선 — Python 0.5.0

2026-10-20. `archive/teoria_docparse/`의 독립 패키지에서 PDF 표 오탐, 제목 표현,
페이지를 넘는 셀을 수정했다. 모든 비교에서 OCR을 껐다. 이번 작업의 성능은
처리 속도가 아니라 **원문을 얼마나 올바르게 구조화하는지**로 평가한다.

## 원문 기준 개선 결과

| 검사 | 원본 kordoc 4.22.15 | Python 0.4.0 | Python 0.5.0 |
|---|---:|---:|---:|
| 기존 규격서의 제목을 heading으로 표현 | 6/7 | 0/7 | **7/7** |
| 추가 문서의 제목을 heading으로 표현 | 4/10 | 0/10 | **10/10** |
| 기존에 확인한 5곳의 표 오탐 | 1곳 | 5곳 | **0곳** |
| 별도 요구사항 양식의 독립성 | 4/20 | 20/20 | **20/20 유지** |
| 추가 규격서의 두 쪽짜리 셀 연결 | 성공 | 실패 | **성공** |
| HWP/HWPX/DOCX의 셀 내용·주소·병합 | 221/221 | 221/221 | **221/221 유지** |
| 선택한 규격·조건 문구 | 36/36 | 36/36 | **36/36 유지** |

이 표는 선택한 원문 검사 항목별 결과다. 전체 문서 정확도나 모든 종류의 제목 계층을
점수화한 결과가 아니다. 기본 pdfplumber와 선택 MuPDF 경로 모두 같은 항목별 결과를 얻었다.

## 변경한 판단

### 장식과 실제 표 구분

- 한 줄에 연속된 좁은 사각형들 위로 글자가 걸치고, 실제 세로 구분선이 없는 경우
  색상 그라데이션을 그리기 위한 조각으로 판정한다. 문서명·파일 hash를 조건으로 쓰지 않는다.
  실제 괘선이 있는 좁은 입력칸과 음영 데이터 표는 유지한다.
- clipping 표의 셀들이 더 큰 선 기반 표의 동일 셀과 일치하면 중복 후보를 제거한다.
  헤더가 표 면적의 절반을 차지하는 경우에도 나머지 행을 복원한다. 동일 범위의 clipping
  격자에 빠진 셀을 채운 기존 `grid_fill` 출처는 보존한다.
- 쪽 경계 부근의 단일 clipping이 실제 부모 셀 안에 있고 독립 테두리가 없으면,
  해당 글자는 부모 셀 본문으로 남긴다. 이를 내부 표로 다시 만들지 않는다.

`doc_01`의 파란 제목 배너 두 곳, 중복 헤더 한 곳, `SER-001`과 `PSR-002` 본문의
가짜 내부 표 두 곳을 제거했다. 본문을 삭제해서 표 수만 줄인 것이 아니다.
기존의 실제 중첩 표와 디스크·보조장치 병합, CPU=2·메모리=4 수량도 유지한다.

### 제목 표현

PDF 글자에서 크기·글꼴 이름·가능한 경우 굵기 flag를 측정한다. 페이지와 문서의
주된 본문 크기, 짧은 제목의 번호 패턴을 함께 사용해 `heading`과 level을 지정한다.
보이지 않는 clipping 격자가 문단으로 풀릴 때도 단일 행의 측정값을 보존한다.

날짜, 페이지 번호, 크게 쓴 용량·전력 값과 `CPU: ...` 같은 필드 값은 제목 승격에서
제외한다. 같은 위치에 반복되는 머리말도 본문 제목으로 세지 않는다.
이는 제목/문단의 구조 표현을 개선한 것으로, 모든 문서의 세밀한 목차 계층을 완성한 것은 아니다.

### 페이지를 넘는 셀

숫자뿐 아니라 영문·한국어 목록의 다음 번호를 확인한다. 기존 두 쪽 연결 뒤 세 번째
조각이 오면 이미 합쳐진 표의 소유자와 마지막 쪽 영역을 따라간다. 새 제목이나 본문이
사이에 있거나 목록이 처음부터 다시 시작하면 연결하지 않는다.

추가 문서 `additional_008`의 1쪽 `가/나` 항목은 2쪽의 `다..카`로 이어진다.
이전 버전은 2쪽을 별도 문단으로 내보냈지만, 0.5.0은 같은 전체 너비 셀에 연결한다.
`JupyterHub/JupyterLab`과 마지막 `전자문서` 내용이 같은 셀에 있으며,
`Table.regions`와 내부 문단에는 **1·2쪽의 실제 출처**가 남는다.
모든 형태의 다열·여러 쪽 표 연결까지 해결했다고 주장하지 않는다.

## 검증 범위와 회귀 검사

기존 입력 경로 68개에는 동일 SHA-256의 `corpus_041/044`가 있었다. 이를 한 번만
세고, 이전 68개에 없던 **추가 21개**를 포함해 **중복 없는 88개**를 비교했다.

| 형식 | 고유 입력 수 |
|---|---:|
| PDF | 36 |
| HWP | 34 |
| HWPX | 13 |
| DOCX | 1 |
| XLSX | 2 |
| PNG | 2 |
| 합계 | **88** |

- 원본 kordoc과 후보의 두 경로를 동일 입력으로 새로 실행했다. 원본을 정답으로
  간주하지 않고, 기존 source 기준 평가와 추가 PDF 4개의 시각 확인 항목을 사용했다.
  추가 21개 중 4개 PDF의 검사 항목은 원문 기준, 나머지는 차이·보존 검사다.
- 기존 평가에서 OCR 관련 항목을 빼고 57개를 유지했으며, 추가 문서에서 40개를
  더해 **수동 원문 기준 97개**를 고정했다. 이 항목과 별도로 원본 컨테이너/XML에서
  읽은 **221개 셀**을 검사했다. 후보 두 경로 모두 검사 항목을 통과했다.
- PDF를 제외한 **52/52개**는 `parser_version`만 제외한 전체 JSON이 이전 Python과
  같다. 원문 전체의 정답률이 아니라 동작 보존 근거다.
- 전체 **88/88개**의 숫자 토큰 multiset과 성공/실패 상태가 이전 Python과 같다.
  이는 기존 수치의 누락·추가 여부를 검사한 것으로, 이전 숫자 자체가 모두 정답임을
  보증하지 않는다. 원문 규격·조건 문구는 별도의 36개 확인 항목으로 평가했다.
- 기존에 원본과 본문·표·셀이 일치한 48개는 모두 유지했다. 전체 88개에서 원본과의
  일치는 65개다. 이 수치는 호환성 보조 기록이며 품질 점수로 사용하지 않는다.
- OCR을 껐으므로 텍스트 없는 PDF 2개·PNG 2개와 암호 PDF 1개는 후보의 실패 상태를
  유지한다. 후보 성공 83/88개를 내용 정확도와 혼동하지 않는다.
- 추가 샘플을 보며 수정한 진단이다. 독립 holdout·blind 평가나 전문가 이중 검수는 아니다.
  88개 전체를 글자별·셀별로 정답 전사한 것도 아니다.

원문 근거와 정답 항목은 [quality_labels_v0_5_0.json](../verification/quality_labels_v0_5_0.json),
항목별 결과와 숫자/상태 보존은 [quality_upgrade_v0_5_0.json](../verification/results/quality_upgrade_v0_5_0.json)에 있다.
[기본 경로 비교](../verification/results/corpus_88_pdfplumber_v0_5_0.json),
[MuPDF 비교](../verification/results/corpus_88_pymupdf_v0_5_0.json)와
[입력·소스·실행 근거](../verification/provenance_v0_5_0.json)도 보존한다.

## 테스트와 설치 패키지

전체 **96개 테스트 통과**, Ruff 정적·형식 검사 통과. 양쪽 PDF 경로에서 장식 배너,
실제 음영 표와 좁은 입력칸, 중복 헤더, 실제/가짜 중첩 표, 날짜·규격값·머리말의
오승격 방지, 두 쪽 셀과 세 쪽 목록의 출처 보존을 검사했다.

평가기에는 한 셀 안의 연결을 별도 셀에 있는 같은 단어와 구분하는 검사도 추가했다.
읽기 순서는 해당 성능 항목 뒤에서 검사한다. 앞의 구성품 목록에 먼저 등장한 같은
용량 때문에 올바른 본문 순서를 오류로 판정하지 않도록 범위를 명시했다.

0.5.0 wheel·sdist를 만들고 기본/선택 엔진의 격리 환경에서 설치와 파싱을 확인했다.
원본 규격서의 제목·오탐 표와 두 쪽짜리 셀도 설치된 wheel로 다시 확인했으며,
이때 외부 프로세스 호출을 차단했다.
빌드 증거는 [build_artifacts_v0_5_0.json](../verification/build_artifacts_v0_5_0.json)에 기록한다.
이전 버전의 배포물과 증거는 덮어쓰지 않는다. 추가 runtime 의존성은 없다.
표 순번, PDF `Block.type`과 Markdown의 제목 구조는 의도한 개선에 따라 달라진다.

이번 비교의 단발 시간은 동시 correctness 실행 중 얻은 값이다. 0.5.0의 속도 우위
근거로 사용하지 않는다. 이전 0.4.0의 반복 측정도 0.5.0 측정값으로 바꾸어 설명하지 않는다.
활성 Platform·Pipelines·Registry·Prefect·배포에는 연결하지 않았다.

재평가 코드는 [quality_upgrade_review.py](../verification/quality_upgrade_review.py)다.
원문·전체 JSON·렌더링은 `archive/teoria_docparse/.artifacts/quality_upgrade_0_5_0/`와
기존 `.artifacts/`에만 보존한다.

```bash
archive/teoria_docparse/.venv/bin/python archive/teoria_docparse/verification/quality_upgrade_review.py \
  --runs archive/teoria_docparse/.artifacts/quality_upgrade_0_5_0 \
  --manifest archive/teoria_docparse/.artifacts/quality_upgrade_0_5_0/unique_manifest.json \
  --labels archive/teoria_docparse/verification/quality_labels_v0_5_0.json \
  --pdfplumber archive/teoria_docparse/.artifacts/quality_upgrade_0_5_0/final_pdfplumber \
  --pymupdf archive/teoria_docparse/.artifacts/quality_upgrade_0_5_0/final_pymupdf \
  --output archive/teoria_docparse/verification/results/quality_upgrade_v0_5_0.json
```
