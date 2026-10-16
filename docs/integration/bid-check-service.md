# 입찰체크 서비스 연동

입찰체크 서비스는 MCP나 Data DB에 직접 연결하지 않고 Runtime HTTP API를 호출한다.

호출 가능한 Capability와 입력 계약은 배포된 Runtime의 `GET /v1/capabilities`에서
확인한다. 저장소의 Registry 원본과 운영 artifact는 version이 다를 수 있으므로
클라이언트가 사용하는 배포의 discovery와 OpenAPI를 기준으로 한다.
조달 탐색 Capability 5개와 기관·업체 관계의 `network_edge` 모드는 Runtime bundle
`2026.10.13.1`부터 제공한다. 배포마다 discovery를 확인한 뒤 기능을 활성화한다.

빠른 탐색의 신규 이름, 기존 계약 재사용 범위와 인수 조건은
[조달 탐색 연동 계약](procurement_exploration_contract.md)에 있다.

```text
Bid service → API gateway → Teoria Runtime API → Capability → Source/Data DB
```

## 계약 발견

배포마다 Registry release가 달라질 수 있으므로 정적 Capability 목록이나 입력
schema를 client 코드에 복제하지 않는다.

1. `GET /health`로 상태를 확인한다.
2. `GET /v1/version`으로 Runtime과 Registry version을 기록한다.
3. `GET /v1/capabilities`에서 Capability ID와 `input_schema`를 조회한다.
4. 필요한 Capability를 `POST /v1/capabilities/{id}:execute`로 실행한다.

정확한 request와 response는 discovery 응답과 배포된 OpenAPI가 최종 기준이다.

```bash
curl -H "Authorization: Bearer $TEORIA_RUNTIME_API_TOKEN" \
  http://localhost:8081/runtime-api/v1/capabilities
```

## 권장 호출 흐름

입찰 대상 검색, 공고 상세·낙찰·참여 이력 확인, 회사 profile 조회 순서로 실행한다.
첨부문서에서 참가요건을 추출하거나 업체의 참가 가능성을 판정하는 기능은 보류되어
현재 discovery 계약에 포함하지 않는다.

Capability 응답의 object와 link에는 type, identity와 provenance가 포함된다.
객체가 없다는 사실만으로 자격 상태를 추론하지 말고 Capability가 정의한 outcome,
오류와 데이터 기준일을 함께 확인한다.

## 기관·업체 계약 집계 표시

기관·업체 조달 프로필의 계약 통계는
[`analyze_organization_procurement_profile`](../../platform/registries/domains/public_procurement/capabilities/analyze_organization_procurement_profile.yaml)과
[`analyze_company_procurement_profile`](../../platform/registries/domains/public_procurement/capabilities/analyze_company_procurement_profile.yaml)을 사용한다.
산정 규칙의 단일 원본은 [공공조달 계약 집계 기준](../platform/domains/public_procurement/contract_aggregation.md)이다.

입찰체크는 응답의 `analysis_basis`와 `summary.amount_completeness`,
`summary.missing_first_contract_date_count`를 함께 해석해야 한다. 계약 추이에는 최근
변경일이 아니라 최초 계약일을 사용하고, 다음 안내를 계약 건수·금액과 함께 표시한다.

> 계약 건수는 최초 계약일 기준이며, 금액은 조회 종료일 현재의 최신 계약금액입니다.

## Ontology 경계

입찰체크 Ontology는 기존 Published version을 직접 사용하거나 수정하지 않는다.
Published version에서 새 Draft를 생성하고 의미가 유지되는 stable concept를
승계한다. 기관·업체 프로필, 공고 관계 컨텍스트, 유사사업 경험과 같은 집계 응답은
Business Object로 만들지 않고 Capability 결과 projection으로 유지한다.

## 오류와 pagination

| 종류 | 처리 |
|---|---|
| 인증/권한 | 재시도하지 말고 credential 또는 gateway 정책 확인 |
| 입력 검증 | discovery schema에 맞춰 요청 수정 |
| timeout/일시 장애 | 멱등 호출만 제한된 exponential backoff로 재시도 |
| provider 오류 | 부분 결과와 provenance를 보존하고 사용자에게 표시 |
| cursor | 응답 cursor를 그대로 다음 요청에 전달 |

client timeout은 Runtime의 Capability deadline보다 길게 설정한다. 검색 결과의
`truncated`, `has_more`와 cursor 의미를 혼용하지 않는다.

## 보안과 운영

- `TEORIA_RUNTIME_API_TOKEN`은 backend secret으로 관리하고 브라우저에 노출하지 않는다.
- 외부 공개 시 gateway에서 사용자 인증, rate limit, token rotation과 접근 로그를 적용한다.
- 사업자번호 등 식별정보를 application log와 analytics event에 그대로 남기지 않는다.
- 응답의 Registry version, artifact checksum과 provenance를 감사 가능하게 보존한다.
- 데이터 수집 완전성과 최신성은 Capability 존재 여부와 별개로 monitoring한다.

## 인수 확인

- 배포 시작 시 discovery와 필수 Capability 존재 여부를 검사한다.
- input schema 변경을 contract test로 감지한다.
- 성공, 빈 결과, 부분 결과, validation error, timeout을 각각 시험한다.
- Registry release 전환과 이전 artifact rollback을 시험한다.
