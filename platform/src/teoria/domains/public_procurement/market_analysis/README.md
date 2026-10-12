# Public procurement market context

이 패키지는 조달 원천을 읽어 기관·업체·공고 관계를 계산한다. DB 접근과
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
| 참여·경쟁사 조회 | `participation.py` |
| 낙찰·계약 결과·단계별 활동 | `outcomes.py`, `activity.py` |
| 기업 근거·분야 식별·기간·신호 상수 | `company_evidence.py`, `field_identity.py`, `periods.py`, `signal_policy.py` |
| SQL 문장·Data DB 조회 경계 | `sql/`, 기능별 `readers/` 모듈 |
| 프로필·참여 행의 내부 타입 검증 | `records.py` |

새 호출은 기능 모듈을 직접 참조한다. `market_context/`와 이 패키지의
`processor.py`는 기존 Python 호출 경로를 위한 재노출 모듈이며 구현을 복제하지
않는다. 기능 모듈은 호환 경로를 경유하거나 순환 import하지 않는다.
각 기능의 메모리 cache는 해당 실행 모듈에 두고, 순수 정책은 Registry·DB
connection·Runtime cache와 분리한다. 기능 테스트는
`platform/tests/unit/domains/public_procurement/market_analysis/`에 둔다.

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
분자·분모를 집계하며 별도 낙찰 실적과 구분한다. API의 새 `participation_analysis`
계약과 수집 상태·상위 10위 범위는
[조달 집계 기준](../../../../../../docs/domains/public_procurement/contract_aggregation.md)에 정의한다.
