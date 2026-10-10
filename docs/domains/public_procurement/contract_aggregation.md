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

## 계약 분야 분류

기관 프로필과 조달 활동 검색의 계약 단계는 동일한 계약 분야 식별 정책을 사용한다.
계약의 원천 분류번호·분류명을 우선 사용하고, 연결된 공고에 같은 분류번호의 대분류·
중분류가 없으면 해당 분류번호가 확인된 최근 공고의 공식 분류 계층으로 보완한다.
분야 필터는 이 보완이 끝난 계약사건에 적용한다. 따라서 동일한 기관·기간·업무구분·
분야 조건에서는 다음 불변식을 만족해야 한다.

```text
analyze_organization_procurement_profile.summary.contract_event_count
== search_procurement_activity(stage=contract).pagination.total_items
```

공고의 표시용 분야를 계약사건의 분야보다 우선하지 않는다. 연결 공고가 조회 기간에
포함되어 같은 생애주기 레코드로 합쳐져도, 계약 단계 필터와 결과의 분야 값은 계약에
적용된 공통 분야 식별 결과를 사용한다.

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

## 공급업체 진입 목록의 검색과 페이지네이션

`search_organization_supplier_entries`는 기관·대상연도·진입상태·업무구분·분야
필터를 적용한 계약업체를 사업자등록번호 기준으로 한 번만 집계한다. 업체명 또는
사업자등록번호의 부분 일치 `company_query`를 적용한 다음 안정적인 보조키와 함께
정렬하고 마지막에 페이지네이션한다. 따라서 `pagination.total_items`는 검색어까지
적용된 고유 업체 수다.

`supplier_entry`는 검색 목록과 의미가 다르다. 이 요약은 `company_query`에 영향받지
않으며 선택한 기관·연도·업무구분·분야 전체의 신규 관측·재진입·기존 업체 수를
유지한다. 검색 결과가 없더라도 요약을 0으로 바꾸지 않는다.

정렬 기준은 `contract_amount_desc`, `contract_count_desc`,
`latest_contract_desc`, `company_name_asc`다. 기존 호출 호환을 위해
`first_contract_desc`도 유지한다. 모든 정렬은 사업자등록번호를 최종 보조키로 사용해
페이지 경계에서 누락이나 중복이 생기지 않게 한다.

업체 귀속금액은 계약사건의 최신 금액과 공동수급 지분율을 사용한다. 확인 가능한
귀속금액의 합계가 실제 0원이면 `0`, 모든 계약사건의 귀속금액을 확인할 수 없으면
`null`을 반환하며 `amount_completeness`를 함께 제공한다.

## 업체별 발주기관 관계 진입 상태

`analyze_company_procurement_profile`은 `target_year`에 해당 업체와 계약한 발주기관을
조회 가능한 과거 계약 이력과 비교한다. 대상연도 이전 계약이 없으면
`first_observed`, 직전 3개 역년 안에 계약이 있으면 `incumbent`, 더 오래된 계약만
확인되면 `reentering`으로 분류한다. 이는 법적 의미의 최초 거래가 아니라 Teoria가
조회할 수 있는 이력에서의 최초 관측이다. 업체 방향의 기관 관계 분류는 Capability가
지원하는 2000년부터 대상연도 직전까지의 계약 이력을 조회해 2020년 이전 거래도
판정에 포함한다.

`organization_entry`에는 상태별 전체 기관 수와 신규 관측 비중을 반환한다.
`organization_entry_status`를 지정하면 전체 프로필 집계와 상태별 요약은 유지하고
`organization_relationships`에만 상태 필터를 적용한다. 그 다음 `organization_query`,
정렬, 페이지네이션을 적용하므로 `pagination.total_items`는 검색 조건까지 적용된 전체
고유 기관 수이며 현재 페이지의 행 수가 아니다.

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

## 조달 활동 검색과의 일관성

`search_procurement_activity`도 단계마다 동일한 사건일을 사용한다.

- 공고 단계: `notice_published_at`
- 낙찰 단계: `final_award_date`, 없으면 `opening_at`
- 계약 단계: `first_contract_date`

계약 단계는 공고 생애주기 단위가 아니라 계약사건 단위로 한 레코드를 반환한다.
동일 공고에서 계약이 여러 건 체결되면 각 계약사건을 별도로 반환하고, 변경계약은
계약사건 키로 병합한다. 따라서 기관·기간·업무구분·분야 필터가 같고 추가 검색어 또는
업체 필터가 없으면 다음 불변식을 만족해야 한다.

```text
search_procurement_activity(stage="contract").pagination.total_items
== analyze_organization_procurement_profile.summary.contract_event_count
```

계약 레코드의 `latest_activity_date`는 기간 귀속 기준인 최초 계약일이다. 최신 변경일과
최신 계약금액은 레코드 내부의 계약 상세로 제공하며 기간 귀속을 바꾸지 않는다.

### 공고 중심 그룹 조회

`search_procurement_activity`의 기본 `view_mode=flat`은 기존과 같이 단계별 사건을
반환한다. `view_mode=notice_grouped`는 기간·업무구분·분야 필터를 적용한 사건을 다음
키로 그룹화한 뒤 그룹 단위로 상태 집계, 정렬과 페이지네이션을 수행한다.

- 공고 연결 활동: `bid_notice_id`
- 공고 미연결 계약: `contract_event_id`, 없으면 `unified_contract_number`

### 계약 계보와 근거 수준

`search_procurement_activity(view_mode=notice_grouped)`의 `contracts[]`는 계약사건
병합과 서로 다른 계약사건 사이의 계보를 구분한다. 같은 `contract_event_id`에 속한
원계약·변경본은 기존대로 하나의 계약사건으로 병합하고
`contract_version_count`로 원천 버전 수를 표시한다. 서로 다른 계약사건을 하나의
원계약 계보로 연결하는 판단은 별도의 `contract_family_id`와 근거 수준으로 표현한다.

- `long_term_continuation_type=장기`: `long_term_continuing`
- `long_term_continuation_type=계속비`: `installment`
- `long_term_continuation_type=신규`: `single`
- 그 밖의 값 또는 결측: `unknown`

원천에는 명시적인 부모 계약 ID와 구조화된 차수 번호가 없다. 따라서 장기·계속비
계약에서 같은 공고에 연결되고, 차수 표기를 제거한 계약명이 정확히 같은 계약사건은
하나의 후보 계보로 묶되 `relationship_status=inferred`로만 반환한다. 이때 계약명에서
명시적으로 확인되는 `N차`만 `phase_number`로 추출한다. 제목이나 금액이 비슷하다는
이유만으로 `confirmed`를 부여하지 않는다. 추론 근거는 `relationship_basis`에 공고 ID,
원천 장기계속구분, 정규화된 계약명과 차수 표기를 남긴다.
같은 후보 계보에서 동일한 차수 표기가 여러 계약사건에 반복되면 날짜순 첫 사건은
`phase`, 이후 사건은 앞 사건을 부모로 하는 `amendment` 후보로 표시하되 이 관계 역시
`inferred`다. 동일 `contract_event_id` 안의 변경본 병합과 이 추론 관계를 혼용하지 않는다.

계약상세 URL에 조달청이 제공한 `ctrtNo`와 `ctrtChgOrd`가 있고, 두 값을 결합한
번호가 `confirmed_contract_number` 또는 `contract_reference_number`와 정확히
일치하면 예외적으로 원천 식별자가 확인된 변경계약 계보로 본다. 같은 `ctrtNo`를
`contract_family_id`로 사용하고 변경차수 `00`은 `original`, 이후 연속 차수는
`amendment`로 연결한다. 이때만 `relationship_status=confirmed`를 반환한다. 중간
변경차수가 조회 결과에 없으면 존재하지 않는 부모를 추정하지 않고 부모 ID를 `null`로
둔다.

변경계약 가족에서는 가장 큰 변경차수의 레코드만 `is_current_record=true`이며 이전
레코드는 `superseded_by_contract_event_id`로 다음 변경본을 가리킨다. 각 변경본의
금액은 누적 합산하지 않는다. 최신 레코드 하나만 `include_in_family_total=true`로
표시한다.

`total_contract_amount`는 최신 계약 버전의 원천 `total_amount`,
`phase_contract_amount`는 최신 계약 버전의 원천 `current_contract_amount`다. 두 값의
0과 `null`은 구분한다. 원천 `total_amount=0`은 총액 0원의 증거로 사용하지 않고
미제공 값으로 취급한다. 단일계약에서 유효한 `current_contract_amount`가 있으면 이를
`total_contract_amount`로 보완하고
`total_contract_amount_basis=current_contract_amount_for_single_contract`를 함께
제공한다. 현재 계약 API에는 부가세 포함 여부가 없으므로
`amount_tax_basis`는 `unknown`이다. 총계약금액과 금차계약금액은 의미가 다르고, 동일
공고의 원천 계약 기록끼리도 중복될 수 있으므로 화면에서 단순 합산하지 않는다.

계약별 `amount_record_type`, `effective_contract_amount`,
`include_in_family_total`은 금액의 역할과 합산 여부를 나타낸다. 공고 그룹의
`result_summary`는 가족별 유효 레코드만 사용해 `effective_contract_amount`,
`effective_contract_event_id`, `contract_family_count`와
`amount_aggregation_status`를 제공한다. 모든 가족이 원천 식별자로 확정되면
`confirmed`, 추론 가족이 포함되면 `partially_confirmed`, 유효 레코드를 하나로 정할
수 없거나 계보가 불완전하면 `unresolved`다.

### 장기계속계약의 교차 가족 계보

나라장터가 연도나 차수 전환 시 서로 다른 기초 계약번호를 발급하면 계약 가족 내부의
변경차수만으로 전체 장기계속계약을 표현할 수 없다. 이 경우 계약 가족과 별도로 다음
교차 가족 계보를 제공한다.

- `contract_series_id`: 같은 장기계속계약일 가능성이 있는 가족들의 계보 식별자
- `previous_contract_family_id`: 직전 계약 가족
- `original_contract_family_id`: 후보 계보의 최초 계약 가족
- `family_relationship_type`: `continuation`·`independent`·`unknown`
- `family_relationship_status`: `confirmed`·`inferred`·`unresolved`
- `family_relationship_basis`: 공고 ID, 장기계속 구분, 원천 요청번호, 명시적 차수와
  직전 총액 승계 여부 등 판단 근거

공통된 원천 장기계속 식별자가 없으면 같은 공고, 정확히 같은 정규화 계약명, 명시적
차수와 직전 총액 승계가 모두 관찰되더라도 `confirmed`로 승격하지 않는다. 이러한
관계는 `inferred`이며 `family_relationship_basis.authoritative_series_identifier`를
`null`로 반환한다. 제목·업체·금액·날짜 유사성만으로 확정 관계를 만들지 않는다.

장기계속 계보가 둘 이상의 계약 가족을 포함하면서 관계가 확정되지 않은 경우 다음
안전 불변조건을 적용한다.

```text
amount_aggregation_status == "unresolved"
effective_contract_amount == null
effective_contract_event_id == null
```

이때 확인 가능한 계약 가족의 금액을 버리지는 않는다.
`latest_confirmed_contract_amount`와 `latest_confirmed_contract_event_id`에는 가장 최근
확정 가족의 유효 금액과 이벤트를 제공하고, `included_contract_family_count`와
`included_contract_event_ids`에는 확인된 부분집합을 명시한다. 이 값은 전체 계약금액이
아니며 클라이언트가 임의 합산해서는 안 된다. `amount_aggregation_reason`은
`long_term_continuation_relationship_unresolved`처럼 전체 금액을 확정할 수 없는 이유를
제공한다.

서로 독립된 계약 가족임이 원천으로 확인된 경우에만 가족 금액을 합산한다. 이때 여러
이벤트가 합산되므로 단일 `effective_contract_event_id` 대신
`included_contract_event_ids`를 사용한다.

같은 공고에 계약사건이 여러 개 있으면 공고 그룹은 하나지만 `contracts`에는 각
계약사건을 별도로 유지한다. 같은 계약사건의 변경본은 하나로 병합하고 최초 계약일,
최신 변경 확인일, 조회 종료일 이전 최신 계약금액과 버전 수를 구분한다. 공고명이나
업체명 유사성은 그룹 관계의 근거로 사용하지 않는다.

`stage_counts`는 그룹의 최신 단계 기준이며 `pagination.total_items`도 그룹 수를 센다.
전체 상태 조회에서는 다음 불변식을 만족해야 한다.

```text
sum(stage_counts[scheduled, open, closed, award, contract, failed, cancelled])
== stage_counts.all
== pagination.total_items
```

## 변경 관리와 검증

이 기준을 변경할 때는 다음 항목을 한 변경에서 함께 갱신한다.

1. Runtime 조회·집계 구현과 단위 테스트
2. 기관·업체 프로필 Capability 설명과 Registry version
3. 이 문서와 입찰체크 표시 문구
4. `analysis_basis` 계약 및 실제 Runtime 응답 검증

최소 회귀 사례는 변경계약의 최초 연도 귀속, 조회 종료일 이후 버전 제외, 공동수급
배분, 최초 계약일 누락, 동일 공고의 복수 계약사건이다.
