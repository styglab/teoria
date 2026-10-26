# 파이프라인 작성 위치와 실행 경계

현재 실행 코드는 `backend/src/teoria/features/`의 소유 기능에 둔다.
Flow는 단계의 순서를 표현하고, 실패 지점과 재시도를 Prefect UI에서 확인할 주요 단계는
이름 있는 Task로 만든다. 기능 코드의 배치는 [개발 안내](development.md)를 따른다.

| 작업 | 현재 구현 위치 |
|---|---|
| 명시 입력 규격서 파싱·정보 추출·표준 적용 | `features/specification_processing/` |
| 표준 후보 관리·정규화 프로파일 | `features/goods_normalization/` |
| 법령 수집·구조화·적재 | `features/legal_information/collection/` |
| OpenMetadata ingestion Job 실행 | `features/metadata_management/ingestion/` |

HTTP·DB I/O는 native async client로 실행하고 호출을 `await`로 연결한다.
정규화·계산·검증은 일반 함수로 유지한다. DB 연결과 transaction을 Task 사이에 공유하지 않는다.
재시도 대상은 재실행해도 결과가 안전한 단위로 정하고 동시 실행에는 명시적인 제한을 둔다.
원본 응답 저장과 정규 적재가 모두 성공한 뒤에만 checkpoint를 갱신한다.

Provider API를 새로 수집할 때만 [Connector와 Definition](connectors.md)을 추가한다.
입력 설정은 `backend/config/`, 배포·스케줄은 `deploy/prefect/*.yaml`이 소유한다.
기존 Flow를 바꾸면 소유 기능의 테스트와 배포 선언 검증을 실행한다.
이미지 반영·Worker 교체·실행 검증은 [Prefect 운영 안내](prefect.md)를 따른다.

이 URL에서 안내하던 일반 주문 ETL 예제는 현재 제품 범위에 포함되지 않아
[보관 코드](../../archive/examples/db_sales/flows.py),
[배포 예제](../../archive/examples/db_sales/prefect.yaml),
[보관 테스트](../../archive/examples/db_sales/tests/test_flows.py)로 옮겼다.
운영 배포에 등록하지 않으며 Great Expectations·pandas와 전용 `etl-example` 의존성 그룹도
활성 백엔드에서 제거했다. 이 보관 예제를 현재 실행 절차로 사용하지 않는다.

공식 참고: [Prefect Task](https://docs.prefect.io/v3/concepts/tasks),
[배포 YAML](https://docs.prefect.io/v3/how-to-guides/deployments/prefect-yaml).
