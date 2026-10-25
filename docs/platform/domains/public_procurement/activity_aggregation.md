# 공공조달 활동·참여 집계

> 과거 구현 자료: 이 기능은 2026-10-25 물품 규격서 중심 전환으로 비활성 보관했다.
> 아래 명령·연동·건수는 현재 활성 서비스의 실행 기준이 아니다. 현재 안내는 `docs/index.md`를 따른다.

공고·개찰 참여·낙찰·계약을 함께 조회할 때의 사건일, 중복 제거, 공고 묶음과
관측 범위를 설명한다. 대상은 `search_procurement_activity`와 기관·업체 프로필의
활동·참여 지표다. 계약사건 병합·최신 금액·공동수급 귀속은
[계약 집계 기준](contract_aggregation.md)을 함께 적용한다.

같은 기간을 조회해도 지표별 사건일은 다르다. 각 지표의 근거 범위와 집계 단위를
먼저 확인하고, 참여 기록이 없는 것을 미참여나 실패로 해석하지 않는다.

## `yearly_activity`의 지표별 연도 기준

`yearly_activity`는 하나의 공통 활동일을 사용하지 않는다. 지표마다 다음 날짜를
독립적으로 적용한다.

| 지표 | 연도 기준 | 중복 제거 단위 |
|---|---|---|
| `notice_count` | `notice_published_at` | `bid_notice_id` |
| `participation_count` | 한국시간 개찰일; 없으면 최종낙찰일·입찰시각 순서 | 업체 + 공고번호 + 공고차수 + 분류번호 + 재입찰차수 |
| `award_event_count` | 한국시간 `opening_at`, 없으면 `final_award_date` | 공고번호 + 공고차수 + 분류번호 + 재입찰차수 |
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

## 참여 분석과 수집 상태

기관·업체 프로필의 `outcome.participation_analysis`를 참여 실적 표시 계약으로
사용한다. `summary`와 `yearly_activity`는 같은 업체·입찰 사건 집합에서
`observed_participation_count`, `result_confirmed_participation_count`,
`observed_award_count`를 집계한다. `observed_success_rate`는 마지막 두 값의
비율이며 분자·분모도 `success_rate_numerator`와 `success_rate_denominator`로
반환한다. 최종 낙찰업체가 비어 있는 결과는 확정된 탈락으로 처리하지 않는다.

`independent_award_event_count`는 참여 기록 수집 여부와 무관한 별도 낙찰
실적이다. 이를 성공률의 분자로 사용하지 않는다. 기존 `summary`·
`yearly_activity`의 `award_event_count`도 이 별도 낙찰 실적이며, 기존 응답
구조의 호환을 유지한다. 참여 카드에는 새 분석의 `observed_award_count`를
사용해야 한다. 계약금액은 계속 최초 계약 연도로 집계하므로 낙찰금액과 구분한다.

수집 대기·실행·재시도 상태는 `collection_status=collecting`과
`collection_status_label=수집 중`으로 제공한다. 이 상태에서 관측된 참여가
없으면 표시용 `participation_count`는 `null`, 관측 건수는 0, 성공률은 `null`이다.
`complete`는 알려진 입찰 사건의 **보존 대상** 수집 완료만 의미한다. 실패와
확인할 수 없는 상태는 각각 `failed`·`unknown`이며 완료로 추정하지 않는다.
상태는 Data DB의 제한된 조회 view로 제공하고 Runtime에는 `ingestion` 스키마
조회 권한을 부여하지 않는다.

현재 보존 범위는 개찰 순위 1~10위와 원천 응답에 있는 최종 낙찰업체다.
`basis.maximum_opening_rank=10`,
`retain_available_final_winner_regardless_of_rank=true`,
`all_participants_retained=false`로 범위를 제공한다. 10위 밖 참여를 알 수 없으므로
`overall_success_rate`는 항상 `null`이며 알려진 낙찰 공고의 수집 완료만으로
업체 전체 참여 이력의 완전성을 주장하지 않는다. 도움말과 화면 표시는
입찰체크에서 구현한다.

## 수정과 검증 위치

활동 조회는 `platform/src/teoria/domains/public_procurement/market_analysis/activity/`,
프로필의 참여 분석은 `profiles/participation_analysis.py`, 관측 참여 조회는
`participation/`에서 찾는다. 각 기능의 테스트는
`platform/tests/unit/domains/public_procurement/market_analysis/`의 같은 기능 아래에 있다.

정책 변경 시 계약 집계와 활동 조회의 사건 수·기간 기준을 함께 검증한다.
수집 완료·부분 수집의 의미는 [Pipelines 공공조달 수집](../../../pipelines/domains/public_procurement.md)을 따른다.
