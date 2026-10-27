# 기존 서버 요구조건 Capability 제거

사용자의 초기화 요청으로 서버·메모리 전용 모델, 프로파일과 다음 Capability를 제거했다.

- `search_server_specifications`
- `compare_server_specifications`
- `get_server_requirement_evidence`
- `get_server_requirements`

조회용 Source·Mapping·Runtime projection과 숫자 관찰 적재 코드도 제거했다.
현재 bundle `2026.10.27.3`의 물품 Capability discovery는 빈 목록이다.
이전 요청 예제와 snapshot ID를 새 모델의 데이터로 사용하지 않는다.

현재 작성 기준은 [규격서 물품 모델](../architecture/specification_goods_model.md)이며
`goods` 1.0.0은 새 Draft다. [초기화 기록](../verification/specification_goods_reset_2026_10_27.md)에
삭제 범위, 보존한 원본과 백업, 새 모델 및 실제 확인 결과를 기록한다.
