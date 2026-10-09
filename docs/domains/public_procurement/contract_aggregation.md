# 공공조달 계약 집계 기준

이 문서는 Teoria의 기관·업체 조달 프로필에서 계약 건수와 계약금액을 산정하는
현재 기준을 정의한다. 화면 문구나 개별 서비스 구현보다 이 문서를 우선하며, 대상
Capability는 다음과 같다.

- `analyze_organization_procurement_profile`
- `analyze_company_procurement_profile`

원천 계약 검색 결과를 그대로 세는 규칙이 아니라, 변경계약을 하나의 계약사건으로
병합하고 업체별 귀속금액을 계산하는 분석 규칙이다. 일반 계약 검색 Capability의
페이지 집계 기준과 혼용하지 않는다.

## 핵심 원칙

> 계약 건수는 최초 계약일 기준이며, 금액은 조회 종료일 현재 확인되는 최신
> 계약금액이다.

최신 계약금액도 원계약의 최초 계약 연도에 귀속한다. 최근 변경일은 최신 버전을
선택하고 최근 계약 관계를 정렬하는 데 사용하지만 연도별 계약 건수나 금액의 귀속
연도를 바꾸지 않는다.

## `yearly_activity`의 지표별 연도 기준

`yearly_activity`는 하나의 공통 활동일을 사용하지 않는다. 지표마다 다음 날짜를
독립적으로 적용한다.

| 지표 | 연도 기준 | 중복 제거 단위 |
|---|---|---|
| `notice_count` | `notice_published_at` | `bid_notice_id` |
| `participation_count` | 공고 게시일 | 관계 대상과 참여사건 키의 조합 |
| `award_event_count` | `final_award_date`, 없으면 `opening_at` | 낙찰사건 키 |
| `contract_event_count` | 최초 계약일 | 계약사건 키 |
| `attributed_contract_amount` | 최초 계약일 | 계약사건별 업체 귀속금액 |
| `company_count` | 최초 계약일 | 해당 연도 계약업체의 사업자등록번호 |

공고는 낙찰·계약 행에 반복해서 나타나더라도 게시연도에 한 번만 센다. 기관
프로필은 해당 기관이 기간 안에 게시한 공고 목록을 기준으로 하고, 업체 프로필은
업체 활동과 연결된 공고 중 기간 안에 게시된 공고를 기준으로 한다. 따라서 동일한
필터와 기간에서 다음 불변식을 만족해야 한다.

```text
sum(yearly_activity[*].notice_count) == summary.notice_count
```

낙찰일과 개찰일이 모두 없는 낙찰행은 연도별 낙찰 집계에 포함하지 않는다. 계약의
최근 변경일은 여전히 연도별 계약 지표에 사용하지 않는다.

## 용어와 식별 기준

| 용어 | 정의 |
|---|---|
| 계약 버전 | 원계약과 변경계약 등 원천에 별도 행으로 존재하는 계약 기록 |
| 계약사건 | 같은 계약으로 확인되는 계약 버전을 합친 분석 단위 |
| 최초 계약일 | 조회 종료일 이전 계약 버전의 `concluded_date` 최솟값 |
| 최신 계약 버전일 | 조회 종료일 이전 계약 버전의 `concluded_date` 최댓값 |
| 최신 계약금액 | 조회 종료일 이전 최신 버전의 `current_contract_amount` |
| 업체 귀속 계약금액 | 최신 계약금액 중 해당 계약업체에 귀속할 수 있는 금액 |

계약사건 키는 다음 순서로 선택한다.

1. 값이 있는 `confirmed_contract_number`
2. 값이 있는 `contract_reference_number`
3. `unified_contract_number`

기관 프로필에서는 기관 코드와 계약사건 키를 함께 사용해 버전을 묶는다. 업체별
관계와 금액은 같은 계약사건 안에서도 사업자등록번호 단위로 구분한다. 따라서 한
공고에서 계약이 여러 건 체결되면 공고 수가 아니라 확인된 계약사건 수를 센다.

## 기간 기준

내부 조회는 시작일 이상, 종료일 미만인 반개구간
`[period_from, period_to_exclusive)`을 사용한다. 응답의 `analysis_basis.period_to`는
사용자에게 표시할 포함 종료일이다.

- `period_from_year`와 `period_to_year`를 지정하면 해당 달력연도 전체를 대상으로
  한다. 종료 연도가 현재 연도이면 오늘까지만 포함한다.
- 연도를 지정하지 않으면 `period_years`의 가장 오래된 포함 연도 1월 1일부터
  오늘까지 조회한다.
- 계약사건의 기간 포함 여부는 최초 계약일로만 판단한다.
- 공고일은 최초 계약일의 대체값으로 사용하지 않는다.

예를 들어 원계약이 2023년 2월 1일이고 2025년 6월 1일에 변경된 계약은 2023년
계약사건이다. 2025년만 조회하면 이 사건은 2025년 계약 건수로 다시 들어가지 않는다.

## 계약 버전 병합과 금액 선택

조회 종료일 이전에 확인된 버전만 계약사건 후보로 사용한다. 같은 계약사건에서는
다음 순서로 최신 버전을 선택한다.

1. `concluded_date` 내림차순 (`NULL`은 마지막)
2. `updated_at` 내림차순
3. `unified_contract_number` 내림차순

선택된 최신 버전의 `current_contract_amount`를 현재 계약금액으로 사용한다. 변경계약
때문에 금액이 1억 원에서 1억 3천만 원으로 바뀌었다면 계약 건수는 한 건이고,
1억 3천만 원을 최초 계약 연도에 반영한다. 버전 수는 별도
`contract_version_count`로 제공한다.

## 공동수급과 업체별 금액 귀속

관계별·분야별·연도별 금액에는 전체 계약금액을 업체마다 반복 합산하지 않고 업체
귀속 계약금액을 사용한다.

| 조건 | 업체 귀속 계약금액 | 완전성 |
|---|---:|---|
| 통화가 KRW이고 지분율이 있음 | 최신 계약금액 × 지분율 ÷ 100 | `complete` |
| 통화가 KRW이고 계약업체가 1개 | 최신 계약금액 전액 | `complete` |
| 계약업체가 여러 개이고 지분율이 없음 | 산정하지 않음 (`null`) | `partial` |
| 계약금액이 없거나 통화가 KRW가 아님 | 산정하지 않음 (`null`) | `unknown` |

`total_attributed_contract_amount`는 산정 가능한 업체 귀속 계약금액의 합이다. 금액이
`null`인 사건을 0원 계약으로 확정한다는 뜻은 아니다. 응답의
`amount_completeness`와 `data_completeness.missing_reasons`를 함께 확인해야 한다.

## 최초 계약일 누락

최초 계약일이 없는 계약사건은 공고일이나 변경일로 보정하지 않는다.

- 기간·연도별 계약 건수와 계약금액에서 제외한다.
- `summary.missing_first_contract_date_count`에 고유 계약사건 수를 기록한다.
- `data_completeness.missing_reasons`에
  `some_contract_events_missing_first_contract_date`를 추가한다.

따라서 `missing_first_contract_date_count`가 0보다 크면 화면의 계약 합계는 확인
가능한 최초 계약일을 가진 사건에 대한 부분 집계다.

## 연도별 집계 예시

| 원천 상황 | 집계 결과 |
|---|---|
| 2023년 원계약 1억 원, 2025년 변경계약 1억 3천만 원 | 2023년 1건·1억 3천만 원 |
| 같은 공고에서 서로 다른 계약번호로 2건 체결 | 계약 2건 |
| 2억 원 공동수급, A 60%, B 40% | A 1억 2천만 원, B 8천만 원 |
| 2억 원 공동수급, 업체별 지분율 없음 | 건수는 포함, 업체 귀속금액은 미산정 |
| 최초 계약일 없음 | 기간 집계 제외, 누락 건수에 1건 추가 |

## API가 반환하는 기준 정보

클라이언트는 표시 문구를 추측하지 않고 `outcome.analysis_basis`를 확인한다. 현재
계약은 다음 필드를 반환한다.

```json
{
  "contract_event_date_basis": "first_contract_date",
  "contract_amount_basis": "latest_version_at_or_before_period_end",
  "contract_amount_year_attribution": "first_contract_year",
  "contract_version_deduplication": "merged_by_contract_event",
  "notice_year_basis": "notice_published_at",
  "award_year_basis": "final_award_date_or_opening_at",
  "contract_year_basis": "first_contract_date"
}
```

화면에는 최소한 다음 안내를 계약 추이와 계약금액 근처에 표시한다.

> 계약 건수는 최초 계약일 기준이며, 금액은 조회 종료일 현재의 최신 계약금액입니다.

`latest_contract_date`는 최근 변경을 포함한 최신 계약 버전일이므로 최근 관계 정렬과
표시에는 사용할 수 있지만 계약 추이의 연도 기준으로 사용하지 않는다.

## 변경 관리와 검증

이 기준을 변경할 때는 다음 항목을 한 변경에서 함께 갱신한다.

1. Runtime 조회·집계 구현과 단위 테스트
2. 기관·업체 프로필 Capability 설명과 Registry version
3. 이 문서와 입찰체크 표시 문구
4. `analysis_basis` 계약 및 실제 Runtime 응답 검증

최소 회귀 사례는 변경계약의 최초 연도 귀속, 조회 종료일 이후 버전 제외, 공동수급
배분, 최초 계약일 누락, 동일 공고의 복수 계약사건이다.
