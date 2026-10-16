# 기업-공고 참가 가능성 vertical 검증 보고서

검증 시각: 2026-10-07 UTC

## 검증 질문

> 사업자등록번호 `2708101970`인 기업이 공고 `R26BK01725727:000`에 단독으로
> 참가할 수 있는가?

완료된 참가자격 추출이 존재하고 실제 낙찰업체 사업자등록번호가 확인되는 조합을
Data DB에서 선택했다. Runtime API의 Published artifact로
`assess_company_bid_eligibility` Capability를 실제 실행했다.

## 판정

**Runtime 종단 실행은 성공했으며, 결과를 임의로 합격 처리하지 않고
`needs_review`로 보존했다.** 현재 차단점은 Capability나 데이터 연결 부재가 아니라
세 가지 요건에 대응하는 authoritative company evidence와 표준 평가 규칙이 없다는
점이다.

| 항목 | 결과 |
|---|---|
| Runtime HTTP 실행 | 성공 |
| Published Registry | `2026.10.07.8` |
| Runtime artifact checksum | `sha256:67bf6c...4674c` |
| 반환 Object / Link | 19 / 18 |
| 종합 outcome | `needs_review` |
| 충족 | 1 |
| 불충족 | 0 |
| 사람 검토 필요 | 3 |

## 요건별 결과

| 요건 | 판정 | 이유 |
|---|---|---|
| 공동수급 불가·단독 참가 | `satisfied` | 요청한 참가방식이 `single`이므로 `single_participation_selected` |
| 나라장터 전자입찰 이용자 등록 | `needs_review` | `unsupported_standard_rule` |
| 울진군 안전점검 수행기관 명부 등록 | `needs_review` | `unsupported_standard_rule` |
| 대표자·입찰대리인 지문정보 등록 | `needs_review` | `unsupported_standard_rule` |

평가 응답에는 공고, 요구조건, 사업자등록, 납세자 상태, 조달업체, 등록 업종과
각 판단 근거가 provenance object와 link로 함께 반환됐다. 확인할 수 없는 등록 여부를
기업이 낙찰받았다는 사실로 추론하지 않은 것이 올바른 동작이다.

## 다음 완료 조건

1. `procurement_registration`을 판정할 수 있는 권위 Source에서 전자입찰 이용자와
   대표자·대리인 등록 근거를 확보한다.
2. 지방자치단체별 수행기관 명부처럼 범용 Source가 없는 요건은 `custom` 또는
   document evidence 기반 수동 검토 정책을 명시한다.
3. 자동 판정 가능한 표준 요건과 항상 사람 검토가 필요한 요건을 분리해
   Capability 응답과 Admin UI에 표시한다.
4. `satisfied`, `unsatisfied`, `needs_review`, 부분 Source 실패 사례를 포함한
   대표 평가셋을 구축한다.
5. 같은 실제 실행을 Runtime API와 MCP 양쪽에서 회귀 검증한다.

이 조건을 충족하기 전에는 “기업 참가 가능성을 자동 판정한다”고 표현하지 않는다.
현재 정확한 제품 상태는 **구조화된 요건과 기업 근거를 비교해 확인 가능한 항목은
판정하고, 근거가 없는 항목은 검토 필요로 보존하는 의사결정 지원 Capability**다.
