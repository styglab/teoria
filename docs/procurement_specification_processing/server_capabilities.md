# 서버 요구조건 검색·비교

첫 물품군은 컴퓨터 서버(`4321150102`)다. 승인된 정규화 프로파일을 적용한 관찰을
Data DB에 적재하고 Database Source·Mapping·Capability를 통해 조회한다.
현재 구현은 격리 PostgreSQL·OPA·불변 Runtime bundle에서 검증했다.
운영 Ontology 게시와 운영 bundle 전환은 수행하지 않았다.

## 입력과 저장

- 의미 작성: `backend/authoring/ontology_blueprints/computer_server.yaml`의 서버·메모리·구성 관계.
- 프로파일 작성: `backend/authoring/normalization_profiles/computer_server_memory.yaml`의
  Stable Key를 선택한 Published Ontology의 Stable Concept ID로 해석한 뒤 검토·승인한다.
- 의미 연결: `backend/authoring/ontology_migrations/pending/2026_10_server_specifications/capability_bindings.yaml`.
  Binding 승인에는 불변 Registry release가 필요하다.
- 실행: `teoria-pipelines specification run --manifest ...`에 승인 패키지 URI와 checksum을 고정한다.
  기존 추출을 재사용할 때도 원본 파일과 추출 checkpoint의 checksum을 확인한다.
- 새 Data DB migration: `093_specification_query_observations.sql`.

프로파일을 적용한 숫자 요구조건만 `specification_requirement_observations`에 적재한다.
관찰 ID·주체·서버 소유자·값·단위·연산·역할·범위·원문 위치와 의미 버전을 보존한다.
원문 및 추출·정규화 본문은 파일/S3에 유지한다. 관찰 적재와 실행 완료 상태 갱신은
같은 transaction으로 처리한다. 적재 실패는 완료 checkpoint까지 함께 rollback한다.
기존 구형 표준 draft 실행은 조회용 관찰로 승격하지 않는다.

메모리 구성품에 붙은 요구조건은 승인 프로파일의 `has_memory` 관계가 있고, 원문 추출
관계가 `explicit`이며 소유 서버가 하나일 때만 그 서버에 연결한다. `specification_for`,
해석된 관계, 소유자 누락·중복은 서버 귀속을 만들지 않는다.
`server_requirement_observations` view는 완료·부분 완료 실행의 서버 관찰만 노출한다.
완료 실행이 부분 완료라면 검색 결과를 전체 문서의 완전한 요구조건 목록으로 해석하지 않는다.

## Capability

| ID | 입력 | 결과 |
|---|---|---|
| `search_server_specifications` | `memory_min`, 선택적 역할·범위·단위·snapshot·page | 조건에 맞는 요구조건 관찰과 pagination |
| `compare_server_specifications` | `left_snapshot_id`, `right_snapshot_id` | 동일 의미·역할·범위·단위·버전의 조건 차이와 비교 불가 사유 |
| `get_server_requirement_evidence` | `snapshot_id`, `observation_id` | 추출 checksum 검증 후 원문 구절·node와 관찰 버전 |
| `get_server_requirements` | `snapshot_id`, page | 비교 실행에서 사용하는 내부 조회; 공개 discovery에서 제외 |

검색 결과 단위는 문서 수가 아니라 **요구조건 관찰과 주체의 조합**이다.
한 문서에 여러 서버나 여러 요구조건이 있으면 여러 행을 반환한다.
`memory_min`은 원문의 요구값을 필터링하며 제품의 충족 여부를 판정하지 않는다.
기본값은 `requirement_candidate`, `system_total`, `GB`, 연산 `eq/gte/gt`다.
따라서 지원 상한·기보유 사양·모듈당 값이 기본 검색에 섞이지 않는다.
GB/GiB는 승인된 단위 정책으로 정확히 환산하고 원문 단위·값도 함께 반환한다.
`value_decimal`은 응답에서 정밀도를 보존한 십진 문자열이다.

Runtime 인증을 구성한 뒤 다음 요청을 실행한다.

```json
{
  "inputs": {
    "memory_min": 64,
    "page": 1,
    "page_size": 20
  }
}
```

경로는 `POST /v1/capabilities/search_server_specifications:execute`다.
검색 결과의 `snapshot_id`를 비교 입력으로, `observation_id`를 근거 조회 입력으로 사용한다.
snapshot은 실행 ID와 문서 ID로 고정되며 다른 프로파일로 재처리하면 별도 실행을 사용한다.

비교는 한 의미·역할·범위·단위 그룹에 각 문서의 조건이 하나씩 있고 Ontology·프로파일
버전과 연산·한정자도 같을 때만 수치 차이를 계산한다. 여러 서버·중복 조건은 모호함으로,
버전·단위·범위 차이는 비교 불가로 반환한다. 문자열 이름만으로 다른 문서의 물품을 합치지 않는다.
문서당 1,000개 관찰을 넘으면 부분 결과를 완전한 비교로 반환하지 않고 오류로 중단한다.
근거 조회도 같은 상한을 사용한다. 범용 자연어 planner는 연결하지 않았다.

## 실행 경계와 검증

파이프라인은 Runtime을 호출하지 않는다. 숫자 관찰 준비는 규격서 기능의 Prefect Task,
transaction과 SQL은 규격서 Repository가 소유한다. 검색은 기존 선언형 Runtime을 사용하고,
비교·근거 처리기는 `features/goods_querying/`에서 제공하여 진입점에서 등록한다.

운영은 기존 artifact를 유지한다. 새 구성을 반영하려면 의미·프로파일 검토 및 승인,
Data DB migration, 새 Registry release, 게시 의미·승인 Binding을 포함한 bundle 검증,
Worker와 Runtime 이미지 및 artifact 전환을 순서대로 수행한다.
기존 게시 SQL·Ontology·bundle은 수정하지 않는다.
Compose의 Runtime에는 Worker와 같은 `/app/specification_artifacts` volume을 읽기 전용으로
연결한다. 모델 인증 volume은 제공하지 않는다. S3를 쓰는 환경에서는 Runtime에 별도의
조회 전용 credential 또는 workload identity와 `TEORIA_SPECIFICATION_S3_ENDPOINT` 등
저장소 설정을 제공한다. K3s 운영의 S3/IAM 연결은 별도 환경 검증이 필요하다.

검증 명령과 실제 확인 범위는 [검증 기록](../verification/server_capabilities_2026_10_26.md)에 있다.
합성 원문 사례, 과거 노출 실제 문서의 고정 추출 재사용과 새로운 모델 정확도 평가는 구분한다.
