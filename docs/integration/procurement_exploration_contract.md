# 입찰체크 조달 탐색 연동 계약

자동완성·네트워크·분야 시장 조회를 연결할 때의 현재 계약과 관측 범위를 설명한다.
배포별 지원 기능과 입력 schema는 Runtime discovery·OpenAPI를 확인한다.
저장소 원본 Registry와 운영 artifact는 version이 다를 수 있다.
기본 호출 순서는 [입찰체크 연동](bid-check-service.md)을 따른다.

## 기능 선택

| Capability | 용도 |
|---|---|
| `autocomplete_procurement_entities` | 공고·기관·업체·공식 분야 후보 선택 |
| `get_procurement_network` | 기관·업체·분야 시작점의 제한된 계약 관계 그래프 |
| `get_organization_company_relationship` | 기관–업체 관계와 근거 조회; `network_edge` 모드 지원 |
| `analyze_procurement_field_market` | 수집 범위 내 분야·연도별 시장 집계 |
| `get_procurement_classification_catalog` | 관측된 공식 분류체계·코드·계층 |
| `get_procurement_region_filter_options` | 지원하는 참가 지역제한 코드·명칭 |

전체 프로필은 노드를 선택한 뒤 별도 Capability로 조회한다. 네트워크를 그리기 위해
각 노드의 프로필·경쟁사 API를 반복 호출하지 않는다. 특정 공고 맥락은
`get_bid_notice_relationship_context`, `analyze_bid_participation_context`,
`search_bid_related_projects`의 계약을 유지한다.

## 자동완성에서 필터로 연결하기

`query`, `types`, `limit`, `cursor`를 사용한다. 현재 limit은 기본 8, 최대 20이며
응답 전체 후보 수에 적용한다. 내부 검색 인덱스에서 prefix·초성·번호를 검색한다.
외부 기업정보 API나 실적 전체 집계를 호출하지 않는다.

후보의 type·ID·이름·번호와 검증된 `filter_values`를 사용한다. 누락값은 `null`로
유지하며 제목으로 분야를 추정하지 않는다. 공고기관·수요기관은 원천 역할을 구분한다.

공고의 참가 지역은 다음 형태다.

```json
{"basis": "participation_restriction", "codes": ["11", "26"], "match": "any"}
```

실제 응답의 값을 조회 입력 `region_basis`·`region_codes`로 전달한다. 위 코드는
형식 예이며 원천 근거 없는 지역을 추가하지 않는다. 단일 입력은 기존 `region_code`도
지원한다. 기관·업체 소재지를 공고 참가 지역제한으로 바꾸어 사용하지 않는다.

cursor는 조회 조건 fingerprint와 offset을 포함한다. 다른 질의에 재사용하면
`invalid_cursor`다. 현재 cursor가 고정된 데이터 snapshot을 보장하거나 시간 기반
만료를 제공한다고 가정하지 않는다. 검색 중 질의가 바뀌면 이전 응답을 UI에 반영하지 않는다.

## 네트워크 입력과 표시 제한

| 입력 | 현재 의미 |
|---|---|
| `root_type`, `root_id` | `organization`, `company`, `field` 시작점과 원천 식별자 |
| `field_code` | 분야 시작점 또는 분야 필터; 분야 시작점에서 root ID 대신 사용 가능 |
| `work_type` | 업무구분 필터 |
| `region_basis` | 현재 `participation_restriction`만 지원 |
| `region_code`, `region_codes` | 구조화된 공고 참가가능지역; 복수 코드는 대안 조건 |
| `period_from_year`, `period_to_year` | 최초 계약일의 연도 범위 |
| `depth` | 기본 1, 최대 2 |
| `first_hop_limit` | 기본 20, 최대 100 |
| `second_hop_limit` | 기본 50, 최대 200; 2단계 조회에만 적용 |

기관·업체 시작점에는 해당 ID를 사용하고 분야 필터는 선택적이다. 분야 시작점은
공식 분야 코드로 지정한다. 이름 유사성으로 노드를 합치지 않는다. 현재 2단계 제한은
2단계 조회 전체의 edge 목록에 적용하며 노드마다 limit만큼 확장하는 계약이 아니다.

응답은 nodes·edges·summary·truncation·coverage·analysis_basis를 포함한다.
선정 기준은 계약 건수 내림차순·업체 귀속금액 내림차순이며, `truncation.selection_basis`를
함께 확인한다. 상위 제한과 전체 시장 집계를 구분한다. 제외된 정확한 고유 건수를
계산하지 않은 경우 `omitted_node_count`·`omitted_edge_count`는 `null`이다.

## 현재 읽기 모델과 금액 기준

네트워크는 `contract_event_company_ledger`의 계약 관계를 조회한다.
현재 `coverage`는 계약만 `available`이며 낙찰·관측 참여·동시 참여·공동수급 관계는
`not_in_read_model`로 반환한다. 이러한 관계가 없다고 원천 업무에 존재하지 않는다는
뜻은 아니다. 동시 참여를 공동수급·협력으로 해석하지 않는다.

현재 네트워크의 금액 기준은 `latest_version_at_ledger_refresh`다. 연도 필터는 최초
계약일에 적용한다. 프로필의 조회 종료일 이전 최신 계약금액과 같다고 가정하지 않는다.
화면은 응답의 `analysis_basis`와 갱신 시점을 표시한다.
계약사건·공동수급 귀속의 기본 의미는 [계약 집계](../platform/domains/public_procurement/contract_aggregation.md),
활동·참여 관측은 [활동 집계](../platform/domains/public_procurement/activity_aggregation.md)를 따른다.

분야 시장의 전체는 수집 범위 내 전체다. 연도별 업체 수를 더해 전체 고유 업체 수로
사용하지 않는다. 공식 분류 catalog는 원천에서 관측한 범위이며 전체 공식 분류 마스터와
동일하지 않을 수 있다. 범위는 [분류 기준](../platform/domains/public_procurement/procurement_classification.md)을 참고한다.

## 관계 상세와 기준점

기관–업체 관계의 `view_mode=network_edge`는 네트워크 읽기 모델과 같은 필터로
집계·근거를 조회한다. 생략 시 기본 `history` 계약을 유지한다. history의 공고 연결
사건은 게시일, 공고 미연결 계약은 최초 계약일 기준이므로 두 모드를 혼용하지 않는다.

`snapshot_id`는 현재 ledger 갱신 시각을 표현한다. 네트워크·상세가 같은 필터와 갱신
기준인지 확인한다. 현재 반환 ID를 영속 snapshot 저장·만료·재현 계약으로 해석하지 않는다.
화면에 표시된 상위 edge의 합계와 전체 관계의 집계, 한 근거 페이지의 합계는 구분한다.

## 소비자 검증

- 같은 필터·동일한 읽기 모델 상태에서 edge와 상세 전체 집계를 비교한다.
- 없는 데이터, 미지원 필터, 표시 제한, 수집 범위 부족과 서버 오류를 구분한다.
- 여러 계약·변경본·장기계속계약의 계보·금액을 임의 합산하지 않는다.
- 응답의 근거·금액 기준·관측 범위·갱신 시각을 화면에 보존한다.
- 자동완성에서 선택한 다중 지역과 실제 조회 필터가 일치하는지 확인한다.

## 후속 요구사항과 성능 평가

다음 항목은 현재 보장과 구분하는 후속 검증 범위다.

- 과거 조회 종료일의 version을 네트워크 읽기 모델에서도 재현하는 계약
- graph·상세·cursor를 고정된 snapshot에 결속하고 만료를 구분하는 계약
- 읽기 모델에 없는 낙찰·참여·동시 참여·공동수급 관계의 근거와 수집 범위
- 서버·DB 작업까지의 취소 전파와 부하 조건별 성능 측정

기존 제안 P95 목표는 자동완성 200ms, 네트워크 cache hit 1초, miss 2초다.
합의·검증한 SLA가 아니며 데이터량·동시 요청·기간·depth·payload·cache 조건을 고정해
측정해야 한다. [2026-10-13 단회 관측](../verification/procurement_exploration_2026_10_13.md)은
해당 목표의 달성 증거가 아니다.

인덱스·ledger 생성·갱신과 Data DB migration은 Pipelines, 조회·집계·캐시·Capability는
Platform 공공조달 Domain이 소유한다. 문서 변경만으로 Registry·Published artifact나
Ontology가 바뀌지 않는다.
