# 공공조달 시장 분석 구현

> 과거 구현 자료: 이 기능은 2026-10-25 물품 규격서 중심 전환으로 비활성 보관했다.
> 아래 명령·연동·건수는 현재 활성 서비스의 실행 기준이 아니다. 현재 안내는 `docs/index.md`를 따른다.

`archive/procurement_services/platform/src/teoria/domains/public_procurement/market_analysis/`는 조달 원천을 읽어 기관·업체·공고 관계를 계산한다. DB 접근과
판정 정책을 섞지 않는 것을 기본 원칙으로 한다.

## 모듈과 위치

Capability 등록은 상위 `public_procurement/processors.py`가 기능 모듈을 직접
참조한다. Registry의 `market_context.*` ID와 응답의 provenance 이름은
게시된 계약의 호환성을 위해 유지한다. Python 구현 위치와 Registry ID는 다르다.

| 책임 | 위치 |
|---|---|
| 기관·기업 프로필 실행·집계·시장 구조 | `profiles/` |
| 기관·기업 관계·분야별 근거 | `relationships/` |
| 계약 변경·차수·계열·조회 보강 | `contracts/` |
| 공고 관계·참여 맥락·벤치마크·업체 선정 | `bid_context/` |
| 유사 실적·관련 사업 검색·필터·유사도 | `related_projects/` |
| 참여·경쟁사 조회 | `participation/` |
| 낙찰·계약 결과·단계별 활동 | `outcomes/`, `activity/` |
| 기업 근거·분야 식별·기간·신호 상수 | `company_evidence.py`, `field_identity.py`, `periods.py`, `signal_policy.py` |
| SQL 문장·Data DB 조회 경계 | 각 기능의 `sql.py`, `reader.py` |
| 프로필·참여 행의 내부 타입 검증 | `profiles/models.py`, `participation/models.py`, `row_validation.py` |

호출은 기능 모듈을 직접 참조한다. 이전 `market_context/`와 재노출
`processor.py`는 제거했다. 프로필 실행은 `profiles/service.py`가 소유한다.
기능 모듈은 순환 import하지 않는다.
각 기능의 메모리 cache는 해당 실행 모듈에 두고, 순수 정책은 Registry·DB
connection·Runtime cache와 분리한다. 기능 테스트는
`backend/tests/entrypoints/domains/public_procurement/market_analysis/`에 둔다.

## 변하지 않아야 하는 기준

- 계약과 업체를 먼저 고유 사건으로 병합한 뒤 필터와 페이지네이션을 적용한다.
- 신규·재진입 및 반복 판정은 각 계약일 직전 이력만 사용한다.
- 공동계약의 상태는 업체별로 판정하되 목록 건수는 계약 사건 기준이다.
- 사용자 표시 사유와 내부 전체 근거를 분리한다.
- 상대적인 상위 25% 계약은 절대적인 `대형 계약`으로 표현하지 않는다.
- 판정 임계값과 정렬 우선순위는 응답의 basis에 함께 반환한다.

## 변경 순서

1. 정책 모듈의 단위 테스트를 먼저 추가한다.
2. Capability 회귀 테스트로 응답 계약을 확인한다.
3. Registry 입력 또는 의미 계약이 바뀌면 버전과 release를 갱신한다.
4. 운영 공고로 고유 사건 수, 정렬, 캐시 결과를 검산한다.

Reader의 SQL import는 명시적으로 선언한다. 프로필과 참여 행은 날짜·Decimal
금액·nullable 값을 검증한 뒤 기존 dict 형태와 추가 원천 필드를 유지한다.
검증 오류에는 필드와 오류 유형만 담고 원본 행의 값은 노출하지 않는다.

참여 분석은 `profiles/participation_analysis.py`에서 같은 업체·입찰 차수의
분자·분모를 집계하며 별도 낙찰 실적과 구분한다. API의 `participation_analysis`
계약과 수집 상태·상위 10위 범위는
[활동·참여 집계 기준](activity_aggregation.md)에 정의한다.

활동 조회의 `activity/service.py`는 실행을 조립한다. 사건 병합은 `aggregation.py`,
단계·확장은 `lifecycle.py`, 결과 필터는 `filters.py`, 공고 묶음은 `grouping.py`,
묶음 선택·집계·정렬·페이지는 `result_selection.py`, Runtime 응답은 `presentation.py`가 담당한다.

각 기능은 실행과 Reader·SQL·행 타입을 같은 폴더에서 찾을 수 있게 배치한다.
분류 보강은 여러 Reader가 실제 사용하는 `classification.py`·`classification_sql.py`,
공통 행 검증은 `row_validation.py`가 담당한다. 프로필 Reader 등 실제 재사용하는
코드는 소유 기능을 명시해 참조한다. 테스트는 같은 기능 폴더를 따른다.

## 인접 기능 찾기

`public_procurement/context.py`는 조달 질문의 해석·계획·집계를,
`exploration/`은 자동완성·네트워크·분야 시장 탐색을 소유한다.
탐색의 `reader.py`는 Data DB 조회, `filters.py`는 입력 정책, `pagination.py`는 cursor,
`cache.py`는 Runtime cache 연결, `presentation.py`는 응답·근거 변환을 담당한다.
`discovery.py`, `network.py`, `field_market.py`가 각 기능의 실행을 조립한다.

첨부문서 요건 추출과 참가자격 판정은 보류되어 archive로 이동했다.
현재 Runtime에는 해당 Capability와 processor를 등록하지 않는다.

`classification/`은 조달 분류 정책, `data_profile.py`·`identity_validation.py`는
데이터 품질과 identity 검증, `metadata_operations.py`는 제한된 운영 read view 조회를
소유한다. Domain SQL을 범용 Ontology 패키지에 두지 않는다.

외부 호출 흐름과 노출 범위는 [조달 탐색 계약](../../../integration/procurement_exploration_contract.md),
공고·계약·낙찰 원본 수집은 [Pipelines 수집](../../../pipelines/domains/public_procurement.md)을 참고한다.
