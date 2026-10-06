# 입찰체크 서비스 연동

입찰체크 서비스는 MCP나 Data DB에 직접 연결하지 않고 Runtime HTTP API를 호출한다.

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

입찰 대상 검색, 공고 상세·참가요건 확인, 회사 profile 조회, 종합 적격성 평가
순서로 실행한다. 목록 화면은 batch 평가 Capability가 발견된 경우 이를 사용하고
단건 평가를 N회 반복하지 않는다.

Capability 응답의 object와 link에는 type, identity와 provenance가 포함된다.
객체가 없다는 사실만으로 자격 상태를 추론하지 말고 Capability가 정의한 outcome,
오류와 데이터 기준일을 함께 확인한다.

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
