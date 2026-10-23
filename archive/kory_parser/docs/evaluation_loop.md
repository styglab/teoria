# Kory Parser 평가·개선 순환

평가 실행 코드는 `evaluations/`, 회귀 테스트는 `tests/evaluation/`, Codex 작업 절차는
저장소 루트 `.agents/skills/improve_kory_parser/SKILL.md`가 소유한다.
Codex에서 `$improve-kory-parser`로 호출한다. 디렉터리는 저장소의 snake_case,
스킬의 호출 이름은 Codex의 hyphen-case 형식을 따른다.
라이브러리 wheel에는 개발용 평가 코드를 넣지 않는다. source distribution에는 포함한다.
기존 로컬 `verification/` 도구와 과거 결과는 보존하며 새 평가의 필수 의존성으로 쓰지 않는다.

실제 공고의 표본 추출·문제 발견·세 구현 비교·조건부 반영은
[공고 첨부문서 사이클](public_procurement_cycle.md)을 따른다.
신규 탐색은 실행별 seed·사용 이력으로 이전 문서를 제외하고, 고정 회귀셋과 별도 검증셋을
함께 관리한다. 첫 실행 결과는 [2026-10-23 비교 보고서](public_procurement_cycle_2026_10_23.md)에 있다.

## 실행

저장소 루트에서 다음을 실행한다. 출력 경로는 실행마다 새 경로를 사용한다.

```bash
cd archive/kory_parser
uv sync --locked --group dev
uv run --locked python -m evaluations --output .artifacts/evaluation_001
uv run --locked python -m evaluations --output .artifacts/evaluation_002 \
  --baseline .artifacts/evaluation_001/report.json
uv run --locked python -m evaluations.improve --dry-run --output .artifacts/loop_preview
uv run --locked python -m evaluations.improve --output .artifacts/loop_001 \
  --iterations 3 --seconds 900 --patience 2
```

`--dry-run`은 실제 평가와 입력 검증까지 수행하고 Codex를 호출하지 않는다.
일반 실행은 인증된 로컬 `codex exec`를 사용하며 `--model`을 생략하면 사용자의 Codex
설정을 따른다. 모델 호출에는 해당 계정의 사용량이 발생할 수 있다. 실행기는
`workspace-write` sandbox를 요청하며 이를 자동 해제하지 않는다. Codex 미설치·인증 실패나
sandbox 실행 실패는 오류로 남긴다. 시간 만료 시 자식 process group도 종료한다.
공식 실행 방식: <https://learn.chatgpt.com/docs/non-interactive-mode>.
저장소 밖의 source distribution에서 반복 실행하려면 `--skill <SKILL.md 경로>`로
스킬 파일을 지정한다. 평가만 실행할 때는 스킬이나 Codex가 필요하지 않다.

모든 기본 검사가 통과하면 자동 실행은 종료한다. 새 기능이나 속도 개선은 먼저
원문 근거와 측정 목표를 갖춘 개발 사례로 등록한다. 점수를 높이기 위해 목표를 완화하지 않는다.
현재 시간 예산은 전체 wall-clock 제한이며 token/금액 한도는 아니다.
주기 실행 예약은 아직 설정하지 않았다. 같은 명령을 스케줄러에서 호출할 수 있다.

## 정답·입력 계약

`evaluations/corpus/seed.json`은 원본 합성 XML과 독립 작성 정답을 함께 보관한다.
합성 PDF도 이 디렉터리의 자체 작성 표본이다. 실제 공고나 개인정보를 포함하지 않는다.
이 코퍼스는 실행 재현용이며 실제 HWP·복잡한 PDF·OCR의 품질 근거가 아니다.

Manifest는 `schema_version: 1`, `corpus_version`, 비어 있지 않은 `cases`를 가진다.
각 case는 다음을 정의한다.

- `id`: 중복 없는 snake_case ID.
- `split`: `development` 또는 `validation`. 같은 원문과 그 변형은 같은 split에 둔다.
- `format`, `sha256`: 실제 입력 바이트 형식과 SHA-256. 불일치는 실행 전 오류다.
- `parts`: 자체 작성 ZIP 문서의 part 이름과 XML. 정렬·1980-01-01 timestamp·무압축으로
  바이트를 재생성한다. 또는 `source_path`로 `--corpus-root` 내부 파일을 참조한다.
- `evidence`: 원문에서 정답을 확인한 위치와 판단 근거. 파서 출력 복사는 정답이 아니다.
- `expected`: `success`, 성공 시 `blocks`, 실패 시 `error_code`.
  `blocks`는 문단 `{ "type": "paragraph", "text": "..." }` 또는
  표 `{ "type": "table", "table": { "rows": 1, "cols": 1,
  "cells": [[{ "text": "value", "row_span": 1, "col_span": 1 }]] } }` 형식이다.
  `contents`를 명시하면 제목·번호·깊이·참조 쪽·해결 상태도 비교한다.
- `options`: 고정된 `ParseOptions`. OCR 등을 비교 중 몰래 바꾸지 않는다.
- `max_seconds`: 문서별 worker 제한. 기본 30초이며 Python 시작 시간도 포함한다.

실문서는 별도 저장소에 두고 상대 경로·hash·원문 근거와 검토한 정답을 새 manifest에
등록한다. 비공개 원문에서 유래한 정답도 공개 저장소에 넣지 않고 접근 통제된 코퍼스와
같이 보관한다. `--manifest <path> --corpus-root <directory>`로 선택한다.
문서·정답·옵션이 바뀌면 새 corpus version으로 기준 평가부터 다시 실행한다.

문자 precision/recall은 NFC·공백 정규화 후 문자 multiset으로 측정한다. 읽기 순서는
정규화 본문 sequence similarity, 표 구조는 순서·격자·병합, 표 셀은 내용까지 비교한다.
표 지표는 문서별 전체 일치 여부이며 셀 단위 평균 정확도는 아니다.
`contents` 없는 사례에는 목차 점수를 만들지 않는다. `thresholds`는 metric별 0~1이며
생략 시 1이다. 정규화 비교는 글꼴·시각적 조판·공백의 정확성을 보장하지 않는다.
처리시간은 warm-up 1회 뒤 3회 중앙값을 기록하며 제한 초과는 실패다.
공통 성공 사례의 시간 합이 5% 넘게 늘거나 문서별 15%와 10 ms를 모두 초과하면
자동 루프는 미채택으로 남긴다. 별도 확인 없이 속도 퇴행을 품질 개선으로 상쇄하지 않는다.
원본 kordoc 비교는 기존 CLI로 별도 실행하며 독립 정확도와 구분한다.

## 개선 후보와 판정

`report.json`은 소스·평가기·manifest·lock hash, Python·주요 dependency 버전,
문서별 지표·실행시간·실패 항목을 기록한다. 정답 본문을 보고서에 복사하지 않는다.
`parsed.json`, 입력 복사본과 실행 로그는 출력 폴더 안에만 보관한다.

반복 실행은 각 iteration의 `candidate/`에 코드를 복사한다. 기존 테스트·평가기·정답·설정은
보호하고 `src/` 수정과 새 회귀 테스트만 허용한다. 기존 테스트 삭제·수정은 거절한다.
원래 테스트와 후보의 테스트를 모두 후보 구현으로 실행하고, 외부 평가기는 고정한다.
추가한 테스트는 수정 전 구현에서 실패하고 후보 구현에서 통과해야 한다.
개발 지표가 하나 이상 상승하고 어느 문서의 지표나 합격 상태도 퇴행하지 않은 후보만
다음 iteration의 기준으로 채택한다. validation은 바깥 평가에서만 실행하고 실패 내용을
수정 프롬프트에 전달하지 않는다. 공개 seed는 비밀 holdout이 아니며 보안 격리를 뜻하지 않는다.
실제 비공개 최종 holdout은 별도 실행 환경에서 평가해야 한다.

`loop.json`과 `loop.md`에 반복 내역·종료 이유·채택 후보 위치를 기록한다.
후보는 검토 가능한 파일로 남기며 원본 작업 트리에 자동 적용하거나 commit/push하지 않는다.
iteration 한도, 시간 한도, 연속 미개선, 전체 검사 통과 또는 실행 오류에서 종료한다.
`all_checks_passed`, `dry_run`, `iteration_budget`, `no_progress`는 정상 종료이며
시간 만료·실행 실패는 완료가 아니다. 중간에 종료된 후보도 원본에 적용하지 않는다.

Harness²는 아직 의존성에 추가하지 않았다. 이 순환의 재현성을 확보한 뒤 같은 수정 과제로
스킬·분석 절차의 효과를 비교할 때 별도 실험으로 연결한다.
