# 공고 첨부문서 기반 개선 사이클

실제 수집 공고에서 표본을 뽑고, 원문으로 확인한 문제를 수정한 뒤 기존 Kory와 kordoc에
대해 같은 입력·옵션·지표로 비교한다. 합성 seed 통과를 실문서 개선 완료로 해석하지 않는다.
작업 주체는 `$improve-kory-parser`이며 모든 다운로드·평가·후보는 archive 내부에서 수행한다.
활성 Platform·Pipelines·MCP·배포에 문서 파싱을 연결하지 않는다.

## 표본 확보

패키지 디렉터리에서 실행한다. Docker worker는 Data DB에 접근할 수 있는 실제 Pipeline
container를 지정한다. MCP의 공고 검색으로 문맥을 확인할 수 있지만 현재 공고 projection에는
첨부 URL이 없으므로 원천 payload의 URL은 읽기 전용 Pipeline 연결로 조회한다.
DB 인증정보를 호스트 명령 인자·로그·manifest에 넣지 않는다.

```bash
cd archive/kory_parser
uv sync --locked --group dev
TASK_RUN=$(uv run --locked python -c 'import secrets; print(".artifacts/cycle_" + secrets.token_hex(8))')
uv run --locked python -m evaluations.public_procurement.export_notices \
  --worker-container teoria-prefect-worker-1 \
  --from-date 2026-10-01T00:00:00+09:00 --to-date 2026-10-24T00:00:00+09:00 \
  --notices-per-work-type 12 --output "$TASK_RUN/notices.json"
uv run --locked python -m evaluations.public_procurement.sample \
  --notices-json "$TASK_RUN/notices.json" --output "$TASK_RUN/sample" \
  --count 30
```

날짜 범위와 업무유형별 공고 수를 명시한다. `--seed`를 생략하면 export와 sampling이 각각
새 seed를 생성해 기록한다. 명시한 seed로 순서를 재현할 수 있지만 선택 결과에는 사용 이력도
영향을 준다. 이미 선택한 문서의 재평가는 저장한 manifest를 사용하며 다시 sampling하지 않는다. SQL은
`evaluations/public_procurement/sample_notices.sql`이 소유한다. 업무유형별 공고 frame 안에서
파일 형식·업무유형을 순환하고 hash 순서로 첨부를 선택하며 공고차수당 최대 3개를 받는다.
URL의 확장자가 아니라 실제 파일 signature를 기록한다. 다운로드는 순차 실행하고
파일당 25 MiB, 총 150 MiB로 제한한다. 실패·중복을 시도 기록에 남기고 같은 바이트는 제거한다.
manifest는 시도마다 저장하므로 중단된 표본도 남는다. 완결 여부는 `sampling.json`으로 확인한다.
이 선택은 전체 공고 모집단에 대한 통계적 정확도 추정용 무작위 표본이 아니다.

공통 이력은 `.artifacts/corpus_history/state.json`이다. 첫 실제 사이클과 기존 보관 코퍼스를
합쳐 160개 원문을 초기 고정 회귀셋으로 등록했다. 이력·고정 manifest·원문을 함께 보존한다.
새 checkout에서 이 파일들이 없으면 기존 코퍼스를 복원하고 한 번 초기화한다.

```bash
uv run --locked python -m evaluations.public_procurement.history freeze-regression \
  --manifest .artifacts/regression_inputs/manifest.json
uv run --locked python -m evaluations.public_procurement.history status
```

초기화 입력은 `document_id`, `source_path`, `sha256`, `format`을 가진 기존 원문 manifest다.
이후 고정 풀을 바꾸지 않고 사용 이력만 추가할 때는 `history register --manifest <경로>`를 쓴다.
`--history`로 별도 실험 이력을 선택할 수 있으나, 이전 사용 자료를 새 표본으로 보이게 하려고
기본 이력을 초기화하거나 우회하지 않는다. 고정 풀 변경은 별도 버전과 의도적인 기준 갱신 작업이다.

export는 사용한 공고번호 전체를 SQL에서 제외한다. sampler도 이력을 다시 확인하고,
새 공고·URL이라도 기존 SHA-256이면 제외하며 해당 공고 alias를 이력에 추가한다.
중단되거나 수용되지 않은 실행의 다운로드도 사용 이력에 남아 다음 실행에서 재사용하지 않는다.
동시에 실행한 sampler는 파일 lock으로 직렬화하고, 상태를 원자적으로 저장한다.

기관·업무유형을 family로 묶어 개발/검증으로 나눈다. 검증은 기존 이력에 없는 family만
선택하며 약 1/3을 할당하고 나머지는 개발에 사용한다. 이미 본 family의 새 문서는 개발에만
들어갈 수 있다. 검증 family에서 기존 파일의 재배포가 발견되면 그 family를 이번 검증에서
제외한다. 필요한 새 자료가 부족하면 `insufficient_fresh_candidates`와 종료 코드 2를 남기고,
이전 문서나 개발 문서로 검증을 채우지 않는다.

각 실행은 변하지 않는 `regression_manifest.json`, 신규 `development_manifest.json`,
신규 `validation_manifest.json`, 둘을 합친 `manifest.json`과 각 hash를 담은
`cycle_manifest.json`을 생성한다. `history_before.json`은 감사용 snapshot이며 활성 이력으로
사용해 과거 상태로 되돌리지 않는다. 같은 원문과 관련된 그룹의 분리는 알려진 metadata에
기반하므로 유사 양식의 독립성까지 증명하는 것은 아니다. 같은 공고와 변환본을 서로 다른
split에 두지 않는다. 반복 양식은 기관 그룹만으로 완전히 분리되지 않으므로, 새 검증셋을
만들 때 기존 manifest의 hash·공고·양식 유사도를 추가 확인한다. seed만 바꾸어 같은 원문을
다시 골랐다고 새 블라인드 검증셋이라고 부르지 않는다.

## 문제 발견과 후보 수정

수정 전 `evaluations.improve.snapshot`으로 baseline과 candidate를 각각 별도 디렉터리에
고정한다. baseline의 `src/`는 수정하지 않는다. 최초 탐색 실행에서 실행 실패·경고,
원문 구조와의 차이, kordoc와의 차이, 시간 지연을 정리한다.

XML 문서는 원본 part와 셀 값·구조에서 직접 probe를 작성할 수 있다. PDF는 원문 렌더링을
시각 확인해 표 개수·행열 등 확인 가능한 항목을 기록한다. 시각 검토자가 Codex인지 사람인지
기록한다. 원문을 보지 않은 추정과 대상 파서 출력을 정답으로 쓰지 않는다.
kordoc와 다르다는 사실만으로 Kory의 결함이라고 판단하지 않는다.

개발 사례에서 재현되는 하나의 문제를 고르고 candidate의 책임 모듈을 수정한다.
기존 구현에서 실패하고 수정 후보에서 통과하는 합성 회귀 테스트도 추가한다.
검증 문서를 수정 방향 선정에 사용하지 않는다. 검토한 검증 문서는 다음부터 회귀용으로
취급하고, 일반화 확인에는 새 공고·양식의 원문을 추가한다.

## 같은 조건의 세 구현 비교

`KORDOC_PACKAGE`는 설치된 고정 버전 kordoc의 package 디렉터리다.

```bash
uv run --locked python -m evaluations.benchmark \
  --manifest "$TASK_RUN/sample/manifest.json" \
  --baseline "$TASK_RUN/baseline" --candidate "$TASK_RUN/candidate" \
  --reference-package "$KORDOC_PACKAGE" --output "$TASK_RUN/benchmark" \
  --repetitions 3 --timeout 90
uv run --locked python -m evaluations.public_procurement.probes \
  --manifest "$TASK_RUN/sample/manifest.json" --reviewed "$TASK_RUN/reviewed_source.json" \
  --labels "$TASK_RUN/source_labels.json" --benchmark "$TASK_RUN/benchmark" \
  --output "$TASK_RUN/quality.json"
```

실행 전 원문 SHA-256을 검증하고 각 구현의 소스·버전과 옵션을 기록한다. OCR·이미지 추출은
모두 끈다. Python과 Node 모두 파일을 미리 읽은 바이트를 사용하고, 문서마다 warm-up 1회 뒤
3회 측정의 중앙값을 사용한다. 프로세스 시작·파일 읽기는 parse 시간에서 제외하며
구현 실행 순서를 문서마다 바꾼다. JSON 본문과 실행기의 stdout을 분리해 PDF 라이브러리의
로그를 파싱 실패로 잘못 집계하지 않는다. 실패 문서를 분모에서 숨기지 않는다.

probe 정답은 `source_labels.json`으로 고정한다. 이 파일이 있으면 자동 재생성하지 않는다.
`reviewed_source.json`은 문서 ID별 SHA-256, evidence, `pdf_pages`를 담는다. 각 page에는
물리 쪽 번호 `page`, `table_count`, `rows`, `cols`를 기록한다. 정답이 틀렸다면 별도 corpus
수정으로 검토하고 이전 결과를 보존한다. XML fragment 존재율은 본문 전체 정확도가 아니며
셀 cached 값의 의미 일치는 화면 표시 형식의 정확도가 아니다.

고정 회귀셋도 매번 같은 입력으로 재실행한다.

```bash
uv run --locked python -m evaluations.public_procurement.regression \
  --manifest "$TASK_RUN/sample/regression_manifest.json" \
  --baseline "$TASK_RUN/baseline" --candidate "$TASK_RUN/candidate" \
  --output "$TASK_RUN/regression"
```

원문 hash와 두 소스 hash를 확인하고 버전 표기를 제외한 출력을 비교한다. 두 소스 hash가
완전히 같으면 한 번 실행한 출력을 재사용하고 그 사실을 보고한다. 이는 서로 다른 구현의
비교 결과를 대신하는 것이 아니다. 예산 초과·불완전 실행·예상 밖 출력 변화는 실패다.

## 개선한 경우에만 반영

정책 기준은 `evaluations/public_procurement/acceptance_policy.json`이다.

- 원문 기준의 목표 검사 항목이 개선되고 다른 원문 검사에 퇴행이 없어야 한다.
- 목표 문서 이외의 출력은 버전 표기만 제외하고 동일해야 한다. 다른 변화는 별도 원문 검토가 필요하다.
- 전체 회귀 테스트가 통과해야 한다. 기존 실문서 회귀 결과가 있으면 같이 검사한다.
- 공통 성공 문서들의 중앙값 합이 기존 대비 5% 넘게 느려지면 거절한다.
- 문서별로 15%와 10 ms를 모두 초과한 지연은 5회 확인 측정을 요구한다.
  확인에서도 기준을 넘으면 거절한다. 최초 측정을 삭제하거나 확인 측정으로 덮어쓰지 않는다.
- 속도만으로 정확도 퇴행을 상쇄하지 않는다. 개선 없음·근거 부족·시간 초과도 반영하지 않는다.

```bash
uv run --locked python -m evaluations.public_procurement.gate \
  --benchmark "$TASK_RUN/benchmark" --quality "$TASK_RUN/quality.json" \
  --policy evaluations/public_procurement/acceptance_policy.json \
  --candidate "$TASK_RUN/candidate" --output "$TASK_RUN/acceptance" \
  --cycle-manifest "$TASK_RUN/sample/cycle_manifest.json" \
  --historical-report "$TASK_RUN/regression/report.json" --apply
```

지연 경고가 있으면 해당 문서들의 별도 manifest로 동일 snapshot을 5회 측정하고
`--confirmation <확인 실행/benchmark.json>`을 추가한다. 기존 실문서 회귀는 원본 hash를
확인해 후보를 재실행하고 `--historical-report`로 문서 수·일치 수·후보 소스 hash를 전달한다.
이력이 없는데 있다고 선언하지 않는다. 새 sampling의 `cycle_manifest.json`을 사용한
benchmark는 고정 회귀 재실행 결과가 필수다. 이를 생략하거나 다른 풀·소스의 결과를
제출하면 gate가 거절한다. 불완전한 새 표본도 반영 대상으로 승인하지 않는다.

`--apply`는 사용자가 개선 반영을 요청한 작업에서만 지정한다. gate는 후보 hash·품질 보고서와
benchmark identity·현재 baseline hash를 확인하고 자체적으로 테스트를 실행한다.
합격한 경우에만 후보 소스를 복사하며, commit/push·서비스 배포는 수행하지 않는다.
`evaluations.improve`의 정답 기반 자동 루프에도 3회 중앙값과 같은 지연 기준을 적용한다.
자동 루프에서는 확인이 필요한 지연도 일단 미채택으로 남긴다.

수치 보고서는 다음 명령으로 재생성할 수 있다. 입력 파일의 hash와 정답 identity를 확인한다.

```bash
uv run --locked python -m evaluations.public_procurement.report \
  --cycle-root "$TASK_RUN" --output "$TASK_RUN/report"
```

보고서 생성 후에는 불필요한 성공 표본과 중복 중간 출력을 자동 정리한다. 고정 회귀 원문,
정답·문제 사례, hash·이력·보고서·소스 snapshot은 남긴다. 평가 중인 새 표본이나 적용을
검토 중인 후보는 정리하지 않는다. 전체 중간 자료가 필요한 실행은 report의
`--keep-intermediates`를 사용한다. 세부 보관 기준은 [Git 보관 범위](git_storage.md)를 따른다.

마지막으로 발견한 문제, 수정, 세 구현의 수치, 적용/미적용 이유, 다음 원문 검토 과제를
기록한다. 이미지의 `NEEDS_OCR`처럼 고정 옵션에서 예상한 제한과 확정 결함을 구분한다.
다음 사이클은 새 표본과 누적 회귀셋으로 이 과정을 반복한다. 현재 주기 실행 예약은 없다.

## OCR 활성화 비교

`evaluations.benchmark --ocr`는 Python과 kordoc 실행기에 모두 OCR 활성화를 명시하고 보고서에 기록한다. 기본값은 기존처럼 꺼짐이다. kordoc 4.22.15의 이미지 입력은 `ocr=false` 요청에도 OCR을 수행하는 사례가 확인되었으므로, 이미지까지 포함한 비교에서는 `--ocr`와 설치된 OCR optional dependency를 사용한다. 기본 비활성 평가와 OCR 활성 평가의 시간·성공률을 합쳐서 비교하지 않는다. OCR 평가는 별도 manifest·원문 정답·기준 실행을 먼저 고정한다.
