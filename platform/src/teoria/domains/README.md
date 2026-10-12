# Domain implementations

이 디렉터리는 Platform이 실행하는 업무 Domain과 이름 있는 기능 패키지를 소유한다.
수집·정규화·Data DB migration은 `pipelines/`에 둔다.

- `company/identity/`: 기업 식별과 상세 정보 조합
- `public_procurement/context.py`: 조달 질문 해석, 계획과 결과 집계
- `public_procurement/bid_eligibility/`: 입찰 참가 가능성과 근거 평가
- `public_procurement/market_analysis/`: 프로필·참여·경쟁사·계약 이력·공고 비교별 관계 분석
- `public_procurement/data_profile.py`, `identity_validation.py`: 조달 데이터 품질·identity 검증
- `public_procurement/bid_eligibility/registry_validation.py`: 참가자격 실행 계약 검증
- `public_procurement/classification/`: 조달 분야 분류 정책
- `public_procurement/bid_check.py`, `admin_api.py`: 공고 요건 관리용 조회와 HTTP adapter

각 Domain의 `processors.py`는 동일한 Runner handler 호출 계약으로 기능을 등록한다.
`runtime/composition.py`가 기본 handler 집합을 만들며 새 processor를 추가할 때
공통 Runner를 수정하지 않는다. query 후처리도 같은 등록 경계에 둔다.
등록된 ID만 실행하며 Registry 문자열로 임의 모듈을 import하지 않는다.

Context의 기본 query handler는 `context/composition.py`에서 선택한다.
Domain handler는 질문 해석·계획 생성·결과 집계를 수행한다. 공통 Context Engine은
의미 조회와 계획·실행의 정책 결정을 유지한다.

기존 `assessment.*`, `market_context.*`, `company_identity.*` processor ID는
게시된 Registry와 artifact의 호환성을 위해 유지한다. Python 모듈 경로와 다르다.
공공조달 정책은 두 번째 Domain에서 실제 재사용이 확인되기 전에는 공통 엔진으로
승격하지 않는다.
