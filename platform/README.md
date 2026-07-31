# Teoria Semantic Platform

`platform`은 데이터의 의미와 사용자 요청 실행을 소유한다. Source, Data Type, Value Set, Ontology, Mapping, Capability Registry와 Runtime 코드가 여기에 있다.

```bash
uv run --locked --package teoria-platform pytest platform/tests
uv run --locked --package teoria-platform teoria validate platform/registries
```

직접 호출 Source의 근거 문서는 `platform/references/providers/`, verification case는 `platform/registries/sources/verification_cases/`에 둔다. 수집 전용 API는 이 프로젝트에 추가하지 않고 `pipelines/connectors/`에 둔다.

`runtime/mapping/functions/`는 Mapping Registry가 참조하는 의미 값 변환 함수다. raw 데이터를 정규 테이블로 만드는 코드는 Data Pipelines의 `normalization/`에 둔다.
