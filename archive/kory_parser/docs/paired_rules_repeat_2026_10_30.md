# 반복 평가와 PDF 이중 테두리 결함 — 2026-10-30

후속 직접 수정에서 확인된 9×9 표 복구를 반영했다.
현재 결과는 [PDF 이중 테두리 표 복원](paired_rules_improvement_2026_10_30.md)을 따른다.
아래는 자동 실행기가 중단됐던 최초 실행의 기록이다.

새 실제 첨부문서 24개를 평가해 이중 테두리 때문에 빈 행·열이 생기는 결함을 확인했다.
**자동 수정 실행기의 sandbox 권한 오류로 수정 후보를 만들지 못했고, 코드 반영은 없다.**
현재 파서의 전체 테스트는 355개가 통과했다.

## 실행과 원문 근거

`evaluations.improve`를 1회·900초·patience 1로 실행했으며 기존 seed 검사는 모두 통과했다.
실문서 검증을 별도로 진행했다. 이전 사용 이력을 제외하고 현재 Data DB에서 읽기 전용으로
공고 150개·첨부 후보 537개를 확보했다. 새 seed로 24개를 다운로드해 개발 16개와
기존 이력에 없는 family의 검증 8개로 나눴다. HWP 4개, HWPX 5개, PDF 6개,
XLS 4개, XLSX 5개다. 고정 회귀 manifest·옵션·정답·의존성·평가기 코드는 유지했다.

개발 PDF `r26bk01763991_000_03`의 1·2쪽을 렌더해 Codex가 시각 확인하고,
원본 벡터 선의 위치를 함께 확인했다. 1쪽 표는 3행×5열로 정상이다.
2쪽은 논리적으로 9행×9열인데 현재 파서는 **15행×10열**을 만든다.
1.08pt 간격의 세로 이중선과 1.44pt 간격의 가로 이중선을 서로 다른 셀 경계로 세면서
내용 없는 행·열이 생긴다. 전체 문서 정확도가 아닌 선택한 원문 격자의 확인 결과다.

이 메커니즘을 검증하도록 1.4pt 간격의 이중 테두리와 A/B/C/D 네 셀이 있는
자체 작성 PDF 및 완전한 2행×2열 정답을 만들었다. 별도의 자체 작성 일반 문단을
validation smoke case로 두었다. 합성 검증을 실제 문서의 블라인드 검증으로 해석하지 않는다.

## 자동 수정이 중단된 이유

완전한 출력 정답을 가진 재현 manifest로 `evaluations.improve`를 다시 호출해
1회·600초·patience 1로 제한했다. 기존 파서는 이중 테두리 재현 사례에 실패했다.
하지만 Codex executor의 첫 shell 명령부터 다음 오류가 발생했다.

```text
bwrap: No permissions to create a new namespace
```

executor는 파일을 읽거나 변경하지 못했다. 외부 프로세스가 0으로 종료돼 loop의
기계적 종료 사유는 `no_progress` / `no_repair_with_regression_test`였지만,
로그에서 확인한 실제 원인은 sandbox 실행 권한 오류다. 이를 parser 개선 불필요나
정상적인 수정 시도 실패로 해석하면 안 된다.

사용한 [improve-kory-parser 스킬](../../../.agents/skills/improve_kory_parser/SKILL.md)은
“Stop on the configured budget, repeated no progress, missing input, contradictory oracle evidence,
or executor failure.”라고 정한다. 이에 따라 수정 실행을 중단하고 sandbox를 우회하거나
별도 수동 수정을 적용하지 않았다. 남은 읽기 전용 비교·결과 기록·정리는 완료했다.

## 비교와 회귀 결과

| 검사 | 현재 Kory | kordoc 4.22.15 |
|---|---:|---:|
| 새 표본 실행 성공 | 22/24 | 24/24 |
| 원문 XML 텍스트 조각 존재 | 499/499 | 499/499 |
| 원문 XML 표 개수 일치 | 5/5 | 5/5 |
| 검토한 PDF 쪽의 표 개수 일치 | 2/2 | 1/2 |
| 같은 PDF 쪽의 행·열 일치 | 1/2 | 1/2 |
| 원문 cached 셀 값 존재 | 4138/4138 | 4128/4138 |

OCR을 끈 조건에서 Kory가 실패한 검증 PDF 2개는 native 문자가 없는 `NEEDS_OCR` 사례다.
참조 구현의 실행 성공을 본문 복원 정확도로 해석하지 않는다.
XML·셀 값·시각 검토는 부분 검사이며, 독립된 사람의 검토나 모집단 정확도 추정이 아니다.

고정 회귀 재실행은 옛 원문 경로 4개가 없어 처음 17개에서 중단됐다.
동일 SHA-256의 로컬 사본으로 원래 경로를 복원한 뒤 **160개를 모두 재실행**했다.
baseline과 candidate의 소스 hash가 같으므로 공식 회귀 도구는 한 번 읽은 출력을
재사용했으며 160개 모두 동일했다. 서로 다른 두 구현의 비교라고 주장하지 않는다.

gate는 전체 테스트 **355개 통과**를 확인했지만 `no_source_quality_improvement`로
미채택했다. `accepted=false`, `applied=false`, 변경 문서 0개다.
baseline·candidate는 같은 코드이므로 관측된 처리시간 차이는 측정 변동이며
속도 개선으로 보고하지 않는다. 최초 비교와 종료 상태는 그대로 보존했다.

## 보존과 다음 과제

로컬 `.artifacts/cycle_2026_10_30_002/`에 표본·사용 이력·고정 소스,
`repair_inputs/`, `repair_loop/`, executor 로그, 원문 렌더와 labels,
`benchmark/`, `historical_regression/report.json`, `acceptance/`, `report/`,
`repair_executor_failure.json`, `final_state.json`을 보존했다.
기본 report cleanup과 추가 정리로 **139,423,744 bytes(약 133 MiB)를 제거**하고,
이번 실문서 실행과 seed 실행 합계 **16,031,744 bytes(약 15 MiB)를 보존**했다.
고정 회귀 원본과 사용 이력, 확인한 문제 원문은 유지했다.

다음 수정 대상은 이중 테두리의 경계를 합쳐 가짜 빈 행·열을 없애는 것이다.
자동 수정 재시도에 앞서 Codex sandbox가 shell 명령을 실행할 수 있도록 환경 문제를
해결해야 한다. 현재까지의 후보 변경은 없으며 기존 XLS 복구 개선은 그대로 유지된다.
