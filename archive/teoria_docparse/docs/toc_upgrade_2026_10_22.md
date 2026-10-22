# 목차 구조화 0.9.0 구현과 3개 파서 비교

선택한 목차 항목의 **계층 복원은 기존 Python 0.8.0과 원본 kordoc 4.22.15보다 개선됐다.**
그러나 문서 자체의 목차와 제안서 작성 양식을 혼동한 과탐, 일부 처리 지연이 남았다.
기본 활성화의 통과 조건을 모두 충족했다고 판단하지 않는다.
따라서 0.9.0에서는 `extract_contents=True` / `--contents` 실험 옵션으로 제공한다.
기본 실행에는 새 목차 단계와 PDF 쪽 번호 단서 수집을 넣지 않는다.

## 실제 구현

`document_contents.py`에서 명시적인 목차 제목을 찾고, 문단·표 행을 항목으로 읽는다.
PDF는 일반 문단 결합 전의 물리 줄을 사용한다. 점선 또는 마지막 숫자 열의 간격을
확인해 쪽 번호를 분리하므로 `Changes from RFC 2818`의 2818을 쪽 번호로 바꾸지 않는다.
장·절 번호의 계층과 부모 ID, 원문 위치를 `ParseResult.contents`에 저장한다.

여러 줄 항목은 원래 영역들을 함께 보존하며, 장마다 반복되는 `1. 적용범위`도
서로 다른 상위 장 아래에서 읽는다. 반복 머리말·꼬리말이 목차를 끊지 않도록 한다.
본문의 장 번호와 제목이 분리된 경우 근거 영역을 합쳐 목적지를 찾는다.
같은 번호·제목의 본문 후보가 하나면 연결하고 여러 곳이면 `ambiguous`, 없으면
`unresolved`로 남긴다. 인쇄된 참조 쪽 번호만으로 물리 쪽을 추측하지 않는다.
e-ICU 문서에서 선택한 세 항목은 실제 본문 3·5·8쪽 제목으로 연결됐다.

새 정보는 별도 목차 구조로 제공한다. 기존 문단·표·셀·병합·Markdown을 고쳐 쓰지 않는다.
HWP/HWPX의 section 근사는 여전히 물리 쪽 번호가 아니다.

```python
from teoria_docparse import ParseOptions, parse

result = parse("document.pdf", ParseOptions(extract_contents=True))
for contents in result.contents:
    for entry in contents.entries:
        print(entry.number, entry.title, entry.level, entry.printed_page_label)
        print(entry.source, entry.target_status, entry.target)
```

```bash
uv run --project archive/teoria_docparse --locked \
  teoria-docparse document.pdf --contents -o parsed.json
```

이 옵션은 JSON/API용이다. 기존 Markdown을 목차 트리 형식으로 바꾸지는 않는다.

## 같은 원문에서의 비교

OCR·이미지 바이트 추출은 모두 껐다. 원본 kordoc 4.22.15는 보관한 실제 npm 패키지로
새로 실행했다. 같은 원문 hash와 기존 비교 bridge의 형식별 옵션을 사용했다.
Python 0.8.0은 변경 전에 고정한 소스 snapshot으로 실행했다.

### 개발 20건 — 원문 선택 항목 40개

| 검사 | Python 0.8.0 | 원본 kordoc 4.22.15 | 0.9.0 목차 옵션 |
|---|---:|---:|---:|
| 선택 항목의 글자 포함 | 40/40 | 40/40 | 40/40 |
| 항목 경계 보존 | 32/40 | 40/40 | 40/40 |
| 명시적 상대 계층 | 6/40 | 10/40 | 40/40 |

### 분리 검증 20건 — 원문 선택 항목 36개

| 검사 | Python 0.8.0 | 원본 kordoc 4.22.15 | 0.9.0 목차 옵션 |
|---|---:|---:|---:|
| 선택 항목의 글자 포함 | 33/36 | 22/36 | 33/36 |
| 항목 경계 보존 | 33/36 | 22/36 | 33/36 |
| 명시적 상대 계층 | 1/36 | 2/36 | 27/36 |

분리 검증의 항목 경계 33개는 기존 Python에서도 보존됐다. 이번 변경의 새 효과는
주로 계층과 부모 관계의 명시화이며, 기존 Python의 글자 추출 우위를 새 개선으로
계산하지 않는다. 원본 kordoc은 일반 블록뿐 아니라 `outline`과 표 행도 검사했다.
문서 제목 때문에 생기는 전역 heading level의 차이는 목차 root 기준으로 정규화한다.
번호 텍스트나 들여쓰기만 보고 평가기가 계층을 새로 추론하지 않는다.
원본의 `listDepth`/중첩 `children` 표현도 확인했으며, 이 표본의 선택 목차 항목에는
해당 표현이 없었다. 쪽 번호를 전사하지 않은 null 정답은 쪽 번호 부재로 채점하지 않는다.

분리 검증은 파일 20개, 선언한 공고/기관 양식 8개 그룹이다. 양성 검사 항목은
그중 5개 그룹에 있다. 이 5개 그룹을 동일 가중치로 평균한 계층 통과율은
기존 Python 1.1%, 원본 kordoc 6.7%, 새 옵션 60.0%다.
19개 항목이 Oregon 매뉴얼 한 계열에 속하므로 27/36을 독립 표본 36개로 해석하지 않는다.

## 미통과 사례와 평가 범위

- 경남교육청 HWPX 2건은 명시적인 `목차` 제목 없이 장·절 개요를 제시한다.
  새 판독기가 이 구간을 잡지 못해 계층 6개가 미통과했다.
- 지역별 가상융합상생협력지원센터 PDF는 일부 목차 번호가 글자층에서 복원되지 않았다.
  관련 3개 계층 검사가 미통과했다. OCR 개선은 이번 변경이 아니다.
- 문서 자체 목차가 없는 음성 표본 9개 중 2개 파일에 과탐이 있었다.
  같은 고용노동부 공고의 HWPX/PDF 변환 쌍이며, 첨부된 **제출 제안서 작성 양식의 목차**를
  해당 문서 자체의 목차처럼 표현했다. 독립 오류 2개 기관으로 세지 않는다.
  이 항목들의 본문 목적지는 `unresolved`지만, 그것만으로 잘못된 구간 선택이 해결되지는 않는다.
- 이 결과는 선택 항목 검사다. 전체 목차 항목의 precision/recall, 모든 형식의 전체 정확도,
  이미지 내용 복원이나 원본 kordoc의 생성·편집·렌더 기능 우위를 뜻하지 않는다.

정답은 원문 PDF 렌더링·HWP 미리보기/레코드·Office XML로 작성했고 파서 출력을 정답으로
삼지 않았다. 분리 검증 정답은 후보 구현 전에 고정했으며, 최종 출력 점수를 본 뒤 추출
규칙을 재선정하지 않았다. 다만 같은 작업자가 원문 정답 준비와 코딩을 수행해 완전한
블라인드 검증은 아니다. 이후 이 오류를 수정할 때는 이번 검증 문서를 개발용으로 옮기고
새 분리 검증 표본을 확보해야 한다.

## 기존 동작과 처리 시간

기존 106개 원본의 JSON 값은 `parser_version`을 제외하고 기본 실행에서 모두 일치했다.
기존 실행 실패 입력도 제외하지 않았다. 문단·숫자·순서·표·셀·병합·원문 위치·Markdown을
포함하는 비교다. 선택 목차 옵션을 켠 40개 문서도 기존 출력 부분을 보존했다.

시간 검사는 목차 옵션을 켠 경로를 기존 Python과 비교했다. 독립 프로세스 3회 측정에서
문서별 중앙값의 합은 개발셋 11.691초→11.687초, 분리 검증셋 11.352초→13.082초였다.
기존 기준인 15% 및 10ms를 모두 초과한 시간 경고는 각각 2건·9건이었다.
개발셋을 문서별로 기존/신규 순서를 번갈아 5쌍 측정한 결과도 10.700초→11.385초,
시간 경고 3건으로 남았다. 측정 순서·환경 변동이 있으며 무저하로 판정하지 않는다.
메모리 경고(20% 및 8MiB 동시 초과)는 없었다.

원본 kordoc은 Node batch 실행, Python은 독립 프로세스 실행이므로 원본과의 속도 우위는
주장하지 않는다. 위 속도 결과는 **목차 옵션 활성 경로**의 결과이며, 기본 실행에
그 단계를 넣지 않은 이유다. 기본 경로의 모든 환경에서 동일 속도를 보장한다는 뜻은 아니다.

최종 비교 뒤에는 추출 알고리즘을 고치지 않고 API/CLI 옵션으로만 격리했다.
패키지의 옵션 활성 JSON 40/40건이 채점한 고정 후보의 JSON과 같고, 기본 JSON
106/106건은 과거 결과와 같은지 다시 확인했다. 이때도 버전 필드만 제외했다.

## 근거와 재실행

단위·회귀 테스트 174개와 변경 Python 파일의 Ruff 검사를 통과했다. 실제 PDF의 CLI
기본/`--contents` 실행을 대조해 기존 출력 보존과 목차 3개 항목의 본문 3·5·8쪽 연결을
확인했다. 최종 패키지 소스는 `packaged_final_0_9_0/`에 hash와 함께 보관했다.
0.9.0 wheel과 source distribution 빌드도 통과했다.

보관 경로는 `archive/teoria_docparse/.artifacts/toc_upgrade_0_9_0/`다.

- `candidate/`: 최초 최종 비교에 사용한 항상 활성 상태의 추출기 snapshot과 도구/정답 hash.
- `comparison_development/`, `comparison_holdout/`: 세 파서의 새 원시 출력, 반복 측정, 항목별 결과.
- `holdout_source_labels.json`과 `.lock.json`: 구현 전 고정한 선택 정답과 근거 범위.
- `paired_development_performance_after_guard/`: 교차 5회 시간 측정. 초기/경고 실행도 덮어쓰지 않았다.
- `packaged_option_validation.json`: 배포용 옵션의 기본 106건·활성 40건 동등성 확인.

기존 원문·고정 snapshot이 있는 환경에서 다음 명령으로 현재 패키지의 동등성을 재검사한다.
과거 비교 스크립트는 보관된 항상 활성 후보를 실행한다. 현재 패키지를 직접 호출할 때는
위의 명시적 옵션을 사용한다.

```bash
archive/teoria_docparse/.venv/bin/python \
  archive/teoria_docparse/verification/verify_contents_option.py \
  --output archive/teoria_docparse/.artifacts/contents_option_repeat.json
```

[항목별 비교 결과](../verification/results/toc_upgrade_v0_9_0.json),
[추출기](../src/teoria_docparse/document_contents.py),
[비교 코드](../verification/toc_upgrade_review.py),
[옵션 동등성 검증](../verification/verify_contents_option.py).
모든 변경은 archive 안에 있으며 활성 프로젝트나 배포에는 연결하지 않았다.
