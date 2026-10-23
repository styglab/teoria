# 목차 고도화용 개발·최종 검증 표본 준비

Harness² 없이 직접 파서를 개선하기 위한 문서 분할과 기존 동작의 기준선을 준비했다.
작업 범위는 `archive/kory_parser/`이며 파서 실행 코드와 활성 Platform·Pipelines·MCP는
변경하지 않았다. 모델 가중치 학습은 하지 않으므로 학습셋 대신 개발셋이라고 부른다.

## 구성

| 용도 | 파일 수 | 형식 |
|---|---:|---|
| 개발 | 20 | PDF 10, HWP 3, HWPX 4, DOCX 3 |
| 최종 검증 예약 | 20 | PDF 7, HWP 5, HWPX 4, DOCX 4 |
| 기존 전체 회귀 | 106 | PDF 44, HWP 36, HWPX 19, DOCX 1, XLSX 4, PNG 2 |

개발셋에는 앞서 확인한 13건을 모두 포함했다. 한국어 목차가 있는 HWP·HWPX·PDF,
쪽 번호 없는 목차, 다단계 목차, 목차가 아닌 제출 안내의 언급, 목차가 보이지 않는
짧은 규격서와 이미지 누락 사례를 포함한다. 개발·회귀의 중복을 제거하면 110개 원본이다.

최종 검증용은 이번에 새로 내려받은 공개 문서다. 대외경제정책연구원·제주특별자치도교육청·
고용노동부·경상남도교육청·나라장터의 공고/과업 문서와 Oregon OSHA의 Word/PDF 매뉴얼이다.
다운로드 URL·시각·실제 컨테이너 형식·SHA-256·크기를 고정했다.
나라장터는 검색 결과 제목이 HWPX여도 실제 PDF를 반환하므로 파일 바이트를 기준으로 했다.

**20개 파일을 20개의 독립 양식으로 해석하지 않는다.** 최종 검증셋은 공고·기관 양식
8개 그룹으로 묶었다. 같은 공고 첨부파일, PDF/한글 변환본, 같은 매뉴얼의 장들은
같은 분할에 두었다. 이후 결과는 파일별·형식별과 함께 그룹별로도 확인해야 한다.

## 중복·사용 이력 확인

- 최종 검증셋과 개발/기존 회귀셋 사이의 원본 hash·공고 그룹·선언된 양식 그룹 중복 없음.
- 다른 보관 위치의 `original.*`와도 동일 크기 파일의 hash를 대조해 기존 원본 재사용 없음.
- 파서의 구조화 출력을 사용하지 않고 원본 PDF 글자층·HWP 레코드·Office XML로만
  텍스트 유사도를 검사했다. NFKC·대소문자·숫자를 정규화한 13자 shingle의
  bottom-512 sketch를 사용했다. 추정 Jaccard 0.35 이상 또는 동일 정규화 본문은 검토 대상이다.
- KISA 후보의 기존 공고와의 추정 유사도 0.443을 확인해 해당 기관 후보 2건을 함께
  제외하고 경남교육청 문서로 교체했다. 채택된 20건은 위 경고 기준에 해당하지 않았다.
- 이 검사는 유사 양식 누출 위험을 줄이는 휴리스틱이며 모든 양식의 독립성을 증명하지 않는다.
- 기존 회귀 5건은 원래 경로에서 `semantic_corpus/retired_inputs/`로 이동되어 있었다.
  원문 hash가 일치하는 이동본을 사용했으며 과거 manifest는 수정하지 않았다.

## 원문 정답 준비 상태

개발 20건에 대해 원문 기반 선택 검사를 기록했다.

- 목차 있음 7건, 검토한 글자층에 목차 없음 11건, 이미지 때문에 미확정 2건.
- 선택 목차 항목 40개: 제목·번호·상대 계층·부모 ID·인쇄 쪽 번호·원문 근거.
- HWP/HWPX/DOCX 표는 파서와 별개의 원본 레코드/XML 검사로 셀·주소·병합 근거를 저장했다.
- 원문 20건의 hash, 항목 ID 중복 없음과 선언된 부모 계층의 유효성을 확인했다.
- HWP 근거 중 `PrvText`는 부분 미리보기이므로 눈으로 확인한 해당 항목에만 사용한다.
  미리보기만으로 전체 문서의 목차 유무나 본문 구간을 확정하지 않았다.
- PDF 항목은 원문 렌더링을 기준으로 전사했다. 근거에는 물리 쪽과 페이지 영역을 남겼지만
  항목별 bbox는 아직 전사하지 않았다. 본문 연결 대부분도 미확정이다.
- 목차 없는 글자층과 이미지 안의 목차 부재를 혼동하지 않는다.

**최종 검증셋은 확보·분리된 상태이며 정답 검수가 끝난 평가셋은 아니다.**
대상 파서 실행과 후보 성능 측정은 하지 않았다. 독립된 원문 검수로 정답을 고정하고,
후보 코드·옵션을 고정한 다음 평가해야 한다. 정답 작성 중 파서 출력을 정답으로 삼지 않는다.
개발셋에도 DOCX 목차 양성, 여러 줄 목차 항목과 본문 목적지의 정답 보강이 필요하다.
현재 선택 검사만으로 이 항목들의 전체 품질을 판정하지 않는다.

## 기존 품질·속도 기준선

기존 106건의 전체 native JSON은 과거 0.8.0 출력과 모두 일치했다.
비교에서는 `parser_version` 필드만 제외하고 본문·순서·표·병합·근거 위치를 유지했다.
실행 실패를 분모에서 제외하지 않았으며 이미지 입력의 기존 OCR 필요 실패도 보존한다.

110개 고유 입력을 각각 독립 프로세스에서 3회, 총 330회 실행해 원시 결과·파싱 시간·프로세스
최대 RSS를 저장했다. 110건 모두 반복 실행의 출력이 일치했다. 기존 실행 실패 입력 5건도
제외하지 않았다. 동시 실행 수는 1이다. 파서 소스·데이터 파일·lockfile을 별도
snapshot으로 보관하고 실행기 hash와 의존성 버전을 기록한다. 결과는 원본 hash로
결합하므로 같은 입력의 개발 ID와 기존 회귀 ID가 달라도 중복 집계하지 않는다.

실행기 수정 중 사용한 탐색 실행 `baseline_v1/`과 달리 채택할 기준선은
`baseline_final/`이다. 실행기가 측정 도중 변경되면 최종 기준선 명령은 실패한다.

후속 변경의 품질 통과 조건은 기존 내용·숫자·순서·셀·병합·원문 위치의 설명되지 않는
변경이 없는 것이다. 목차 항목 분리 등 의도한 변경은 원문으로 별도 검토한다.
속도는 문서별 3회 중앙값이 15% 및 10ms를 모두 초과해 느려지면 조사한다.
메모리는 최대 RSS 중앙값이 20% 및 8MiB를 모두 초과해 늘면 조사한다.
이 수치는 측정 잡음을 고려한 초기 경고 기준이며 자동 성능 보증이 아니다.
같은 머신·의존성·실행기·옵션으로 비교해야 한다.

## 파일과 재현

보관 기준 경로는 `archive/kory_parser/.artifacts/toc_corpus_2026_10_22/`다.

| 경로 | 내용 |
|---|---|
| `corpus/development_manifest.json` | 개발 원본 20건과 분할 그룹 |
| `corpus/development_labels.json` | 개발 원문 선택 항목·미확정 상태 |
| `corpus/development/source_evidence/` | 원본 표 레코드/XML 근거 |
| `corpus/holdout_manifest.json` | 새 최종 검증 원본 20건과 출처 |
| `corpus/regression_manifest.json` | 기존 106건과 현재 원문 위치 |
| `corpus/freeze.json`, `policy.json` | 원본 계약·파서 snapshot hash와 평가 정책 |
| `corpus/template_similarity.json` | 원문 기반 유사 양식 검사 |
| `corpus/annotation_lock.json` | 개발 선택 항목·근거 파일 hash |
| `holdout_rejected.json` | 제외한 후보와 이유 |
| `baseline_final/` | 채택할 3회 기준 실행과 원시 결과 |
| `historical_regression_check.json` | 기존 106건의 전체 출력 보존 검사 |

이미 있는 출력 디렉터리는 덮어쓰지 않는다. 최종 검증을 실행하는 CLI는 이번에 추가하지 않았다.

```bash
archive/kory_parser/.venv/bin/python \
  archive/kory_parser/verification/toc_corpus.py audit \
  --corpus archive/kory_parser/.artifacts/toc_corpus_2026_10_22/corpus

archive/kory_parser/.venv/bin/python \
  archive/kory_parser/verification/toc_corpus.py baseline \
  --corpus archive/kory_parser/.artifacts/toc_corpus_2026_10_22/corpus \
  --output archive/kory_parser/.artifacts/toc_corpus_repeat
```

[검증 도구](../verification/toc_corpus.py),
[분할·누출 방지 테스트](../tests/test_toc_corpus.py),
[고정된 원본·분할 목록](../verification/toc_corpus_manifest_2026_10_22.json),
[준비 결과](../verification/results/toc_corpus_preparation_2026_10_22.json).
기존 테스트와 새 검사 8개를 합해 155개 통과. archive의 Git ignore 정책은 유지한다.
