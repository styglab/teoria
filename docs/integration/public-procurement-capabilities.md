# 공공조달 Capability 현황

이 문서는 현재 Platform Registry에 등록된 공공조달 Capability를 제품 기능 관점에서 정리한다.
여기서 지원 여부는 Runtime API로 실행 가능한 조회 계약을 기준으로 하며, 실제 적재 데이터의 최신성이나
특정 기간의 수집 완료 여부를 보장하지 않는다.

## 지원 수준

| 구분 | 의미 |
|---|---|
| 직접 지원 | 하나의 Capability로 필요한 이력을 조회할 수 있다. |
| 조합 지원 | 여러 Capability 결과를 공고번호, 사업자등록번호 또는 기관코드로 결합해야 한다. |
| 부분 지원 | 기반 데이터는 있으나 전체 첨부, 집계 또는 명시적 관계 일부가 빠져 있다. |
| 미지원 | 현재 공개된 Capability만으로 해당 결과를 만들 수 없다. |

현재 검색 Capability는 조건 검색, 정렬과 페이지네이션을 제공한다. 건수·합계·점유율·집중도·추이처럼
전체 결과 집합을 대상으로 하는 서버 측 집계는 제공하지 않는다.

## 기관 분석

기관명이나 기관코드로 기관을 찾을 때는 `search_public_organizations`를 사용한다. 검색 결과의
기관코드를 아래 공고·낙찰·계약 검색 Capability에 전달한다. 조달청 Provider API를 호출하는
`get_demand_organization`은 기관코드를 이미 알고 있을 때 원천 상세정보를 확인하는 용도다.

| 주요 기능 | 지원 수준 | 사용할 Capability | 현재 가능한 범위 |
|---|---|---|---|
| 기관별 공고 내역 | 직접 지원 | `search_bid_notices` | 게시기간과 공고기관 코드 또는 수요기관 코드로 공고를 검색한다. 업무유형, 상태, 계약방법, 추정가격 조건을 추가할 수 있다. |
| 기관별 낙찰 내역 | 직접 지원 | `search_bid_awards` | 실개찰 기간과 수요기관 코드로 최종낙찰 결과를 검색한다. 낙찰업체와 낙찰금액을 확인할 수 있다. 공고기관 코드 조건은 현재 없다. |
| 기관별 계약 내역 | 직접 지원 | `search_public_procurement_contracts` | 계약체결 기간과 계약기관 코드로 계약을 검색한다. 계약유형, 계약방법과 금액 조건을 추가할 수 있다. |

위 Capability는 기관별 원본 이력 목록을 반환한다. 기관별 발주 규모, 공고 빈도, 상위 낙찰업체,
업체 집중도와 같은 집계 결과는 아직 직접 반환하지 않는다.

## 업체 분석

| 주요 기능 | 지원 수준 | 사용할 Capability | 현재 가능한 범위 |
|---|---|---|---|
| 업체별 참여 내역 | 직접 지원 | `get_company_bid_history`, `search_bid_participations` | 사업자등록번호로 개찰 참여 이력을 조회한다. 개찰순위, 투찰금액·투찰률과 평가점수를 포함한다. |
| 업체별 낙찰 내역 | 직접 지원 | `get_company_bid_history`, `search_bid_awards` | 사업자등록번호로 최종낙찰 이력을 조회한다. 낙찰금액·낙찰률과 수요기관을 포함한다. |
| 업체별 계약 내역 | 직접 지원 | `get_company_public_procurement_contracts` | 업체가 참여한 계약, 업체 역할, 공동도급 방식과 참여 지분율을 조회한다. |
| 경쟁업체 내역 | 조합 지원 | `search_bid_participations`, `get_bid_result` | 해당 업체가 참여한 공고를 찾은 뒤 같은 공고의 다른 참여업체를 조회할 수 있다. 경쟁업체별 동시 출현 횟수나 승패 요약은 제공하지 않는다. |

업체의 참여 건수, 낙찰 건수, 낙찰률, 주요 고객기관과 경쟁업체 순위는 반환된 이력을 별도로 집계해야 한다.

## 공고 분석

| 주요 기능 | 지원 수준 | 사용할 Capability | 현재 가능한 범위 |
|---|---|---|---|
| 공고 기본정보 | 직접 지원 | `get_bid_notice` | 공고번호와 차수로 공고명, 기관, 일정, 상태, 방식과 금액 정보를 조회한다. |
| 참가조건과 문서 근거 | 직접 지원 | `get_bid_requirements`, `get_bid_participation_findings` | 참가요건, 제출·절차 정보, 수행 의무, 원문 발췌, 첨부파일명·페이지·URL 등의 근거를 조회한다. |
| 전체 첨부파일 목록 | 부분 지원 | 위 근거 조회 Capability | 요건이나 참여정보의 근거가 된 첨부는 확인할 수 있지만 공고에 속한 모든 첨부파일을 독립적으로 나열하는 Capability는 없다. |
| 참여업체 | 직접 지원 | `get_bid_result`, `search_bid_participations` | 공고별 개찰 참여업체와 사업자등록번호를 조회한다. |
| 개찰·낙찰 | 직접 지원 | `get_bid_result` | 개찰순위, 투찰가격·투찰률, 평가점수, 최종 낙찰업체와 낙찰금액을 조회한다. |
| 계약 연결 | 조합 지원 | `get_bid_result`, `search_public_procurement_contracts`, `get_public_procurement_contract` | 계약 객체에 저장된 공고번호로 연결할 수 있다. 공고번호를 직접 입력받아 연결 계약을 반환하는 전용 Capability는 없다. |

목록 화면에서 여러 공고를 처리할 때는 `get_bid_notices_by_ids`와
`get_bid_requirements_by_notice_ids`를 사용해 최대 100개 공고를 한 번에 조회할 수 있다.

## 시장 분석

| 주요 기능 | 지원 수준 | 사용할 Capability | 현재 가능한 범위 |
|---|---|---|---|
| 업종·품목별 공고 | 부분 지원 | `search_bid_notices`, `get_bid_requirements` | 업무유형과 자유어 검색은 가능하다. 공고에 표준 업종·품목 분류를 적용해 검색하는 입력은 없다. 요구 업종이 추출된 공고는 참가요건에서 확인할 수 있다. |
| 업체 점유율 | 미지원 | 없음 | 업체별 낙찰·계약 원본은 조회할 수 있지만 시장 전체 금액, 업체별 비중과 집중도를 계산하는 Capability는 없다. |
| 기관 수요 | 부분 지원 | `search_bid_notices`, `search_bid_awards`, `search_public_procurement_contracts` | 기관별 공고·낙찰·계약 목록은 조회할 수 있다. 기관별 품목, 금액과 기간 추이는 별도로 집계해야 한다. |

업체가 나라장터에 등록한 업종과 공급·제조 세부품명은 각각
`get_procurement_supplier_industries`, `get_procurement_supplier_products`로 조회할 수 있다.
이는 업체 프로필 정보이며 업종·품목별 시장 집계와는 구분한다.

## 관계 분석

| 주요 기능 | 지원 수준 | 사용할 Capability | 현재 가능한 범위 |
|---|---|---|---|
| 기관 ↔ 업체 | 조합 지원 | `search_bid_awards`, `search_public_procurement_contracts`, `get_company_public_procurement_contracts` | 기관–낙찰업체와 기관–계약업체 관계를 공통 기관코드·사업자등록번호로 구성할 수 있다. 거래 빈도·금액·최근성 요약은 별도 집계가 필요하다. |
| 업체 ↔ 업체 | 조합 지원 | `search_bid_participations`, `get_bid_result`, `get_company_public_procurement_contracts` | 같은 입찰의 경쟁 참여와 같은 공동계약의 업체 참여를 확인할 수 있다. 업체 쌍별 관계를 직접 반환하지는 않는다. |
| 공고 ↔ 공고 | 부분 지원 | `search_bid_notices`, `get_bid_notice` | 공고번호·차수, 재공고 여부와 생명주기 상태를 확인할 수 있다. 원공고–재공고 계보와 제목·내용 유사도 관계는 제공하지 않는다. |

## 관련 Registry

- Capability 정의: `platform/registries/domains/public_procurement/capabilities/`
- 공공조달 Ontology: `platform/registries/domains/public_procurement/ontology.yaml`
- Data DB Source: `platform/registries/sources/teoria_public_procurement.yaml`
- Runtime API 사용법: `docs/integration/bid-check-service.md`

Runtime 클라이언트는 `GET /v1/capabilities`로 실제 배포본의 Capability와 입력 JSON Schema를
확인하고, `POST /v1/capabilities/{capability_id}:execute`로 실행한다.
