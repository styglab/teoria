# Teoria Semantic Platform

`platform`은 데이터의 의미와 사용자 요청 실행을 소유한다. Source, Data Type, Value Set, Ontology, Mapping, Capability Registry와 Runtime 코드가 여기에 있다.

```bash
uv run --locked --package teoria-platform pytest platform/tests
uv run --locked --package teoria-platform teoria validate platform/registries
```

직접 호출 Source의 근거 문서는 `platform/references/providers/`, verification case는 `platform/registries/sources/verification_cases/`에 둔다. 수집 전용 API는 이 프로젝트에 추가하지 않고 `pipelines/connectors/`에 둔다.

`runtime/mapping/transforms/`는 Mapping Registry가 참조하는 의미 값 변환 함수다. raw 데이터를 정규 테이블로 만드는 코드는 Data Pipelines의 `normalization/`에 둔다.

Capability의 `kind`는 실행 성격을 `query`, `compute`, `action`으로 구분한다. `effects.reads`와 `effects.produces`는 조회 대상과 비영속 계산 결과를, `effects.creates`와 `effects.updates`는 Action이 저장하는 업무 상태 변경을 선언한다. 기존 조회 Capability는 `kind: query`가 기본값이다.

Registry의 `domains/`는 업무 소유권으로 구성한다. `company/runtime_contracts/`에는
`company.yaml`, `public_procurement/runtime_contracts/`에는 `public_procurement.yaml`과
`assessment.yaml`을 둔다. 참가자격 평가 Capability도 공공조달의 `capabilities/`가
소유하며 `assessment.*` ID는 기존 실행 계약의 호환성을 위해 유지한다.
자세한 작성·이관 기준은 [Registry guide](../docs/registry/README.md)를 따른다.

Application DB 통합 테스트는 `TEORIA_TEST_APP_DATABASE_URL`이 설정된 격리 DB에서
실행하며 CI의 `platform-app-integration` Job이 migration·승인·게시·적용 복구를
검증한다. 운영 적용 전에는 신규 Application DB migration을 실행해야 한다.

```bash
TEORIA_TEST_APP_DATABASE_URL=postgresql://... \
  uv run --locked --package teoria-platform pytest platform/tests/integration
```
