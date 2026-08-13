# 입찰체크 서비스 연동 가이드

이 문서는 다른 저장소에서 개발하는 입찰체크 서비스가 Teoria의 입찰공고, 참가요건 및 기업 자격 평가 기능을 사용하는 데 필요한 계약을 정리한다.

## 권장 연결 구조

```text
입찰체크 서비스 ──HTTPS + Bearer token──▶ Teoria Runtime API
                                           ├─ 정규화된 공고·참가요건 DB 조회
                                           └─ 공식 기관 API를 통한 기업 상태·자격 조회
```

외부 서비스는 Pipeline Connector, Teoria Data DB 또는 제공기관 API 키에 직접 접근하지 않는다. Pipeline은 데이터를 수집·정규화하고, Runtime API가 읽기 전용 DB와 Source API를 조합한다. AI Client가 Tool 호출이 필요한 경우에만 `입찰체크 서비스 → MCP Gateway → Runtime API` 구조를 선택한다.

## 접속 정보

운영자가 다음 두 값을 별도 보안 채널로 제공해야 한다.

| 값 | 예시 | 설명 |
|---|---|---|
| Runtime API base URL | `https://teoria.example.com/runtime-api` | 환경별 URL. 실제 경로는 배포 설정에 따름 |
| Runtime API token | 비공개 | 모든 `/v1/*` 호출에 사용하는 Bearer token |

```http
Authorization: Bearer <token>
Content-Type: application/json
```

`GET /health`는 인증 없이 상태만 확인한다. `GET /v1/version`은 Runtime 및 Registry 버전을, `GET /v1/capabilities`는 현재 제공되는 Capability와 JSON 입력 스키마를 반환한다. 클라이언트는 입력 스키마를 코드에 복제하기보다 이 discovery 응답을 계약 확인과 호환성 점검에 활용하는 것이 좋다.

## 입찰체크의 기본 호출 순서

### 1. 공고 검색

```http
POST /v1/capabilities/search_bid_notices:execute
```

```json
{
  "inputs": {
    "notice_published_at_from": "2026-08-01T00:00:00+09:00",
    "notice_published_at_to": "2026-08-13T23:59:59+09:00",
    "query": "정보시스템 운영",
    "work_type": "service",
    "bid_status": "open",
    "bid_deadline_at_from": "2026-08-14T00:00:00+09:00",
    "bid_deadline_at_to": "2026-08-31T23:59:59+09:00",
    "contract_method_name": "제한경쟁",
    "estimated_price_min": 100000000,
    "estimated_price_max": 500000000,
    "sort": "deadline_asc",
    "page": 1,
    "page_size": 20
  },
  "options": {
    "max_objects": 200,
    "include_property_provenance": false
  }
}
```

게시기간은 필수이고 나머지 검색 조건은 선택이다. `query`는 공고명·공고번호·공고기관명·수요기관명을
부분 일치로 검색한다. `work_type`에는 `goods`, `service`, `construction`, `foreign`, `other` 중
하나를 지정할 수 있다. `sort`는 게시일 최신순인 `published_desc`가 기본이고 마감 임박순은
`deadline_asc`이다. 마감일이 없는 공고는 마감 임박순의 마지막에 배치된다.

`page`는 1부터 시작하고 기본값은 1이다. `page_size`는 기본 20, 최대 100이다. 응답의
`pagination.total_items`와 `pagination.total_pages`는 연결된 기관 객체가 아닌 고유한
`bid_notice` 수를 기준으로 한다. 검색 결과가 없으면 `total_items`와 `total_pages`는 모두 0이다.
각 정렬은 `bid_notice_id`를 최종 tie-breaker로 사용한다.

```json
{
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total_items": 1284,
    "total_pages": 65
  },
  "truncated": false
}
```

뒤에 페이지가 남아 있다는 이유로 `truncated`가 참이 되지는 않는다. 페이지 검색에서는 현재
페이지의 공고와 연결 객체를 모두 반환하며, 이들이 실제 서버 제한으로 누락된 경우에만
`truncated=true`이다. 페이지 번호 방식은 숫자형 탐색을 위한 계약이므로 검색 도중 신규 공고가
추가되면 페이지 경계가 이동할 수 있다.

### 2. 공고와 참가요건 확인

공고 식별자는 `공고번호:공고차수` 형식이다. 예: `R25BK00934251:000`.

```http
POST /v1/capabilities/get_bid_notice:execute
```

```json
{
  "inputs": {
    "notice_number": "R25BK00934251",
    "notice_order": "000"
  }
}
```

공고 객체에는 공고명, 업무유형, 게시·마감·개찰 시각, 기관, 입찰·계약 방식, 추정가격, 배정예산, 원문 URL와 함께 다음 요건 추출 상태가 포함될 수 있다.

- `requirement_expression`: `all`, `any`, `leaf`로 구성된 참가요건 조건식
- `extraction_completeness`: 첨부문서 기반 요건 추출 완전성
- `requires_review`: 사람의 원문 검토가 필요한지 여부

개별 요건과 문서 근거가 필요하면 다음 Capability를 호출한다.

```http
POST /v1/capabilities/get_bid_requirements:execute
```

```json
{
  "inputs": {
    "notice_number": "R25BK00934251",
    "notice_order": "000"
  },
  "options": {
    "max_objects": 500,
    "include_property_provenance": true
  }
}
```

`bid_requirement` 객체는 요건 유형·연산자·요구값, 원문, 적용 주체, 기준일, 필수 여부, 추출 신뢰도, 표준 판정 규칙 및 문서 근거를 제공한다. 화면에서는 정규화된 판정 결과와 함께 `original_text`, `proposition_text`, `evidence_summary`를 사용자가 확인할 수 있게 표시하는 것을 권장한다.

### 3. 회사의 종합 입찰 적격성 평가

대부분의 입찰체크 화면은 여러 조회 API를 직접 조합하지 않고 다음 단일 Capability를 사용하면 된다.

```http
POST /v1/capabilities/assess_company_bid_eligibility:execute
```

```json
{
  "inputs": {
    "business_registration_number": "1234567890",
    "bid_notice_id": "R25BK00934251:000",
    "reference_date": "2026-08-13",
    "participation_mode": "single"
  },
  "options": {
    "max_objects": 1000,
    "include_property_provenance": true
  }
}
```

`business_registration_number`와 `bid_notice_id`는 필수다. `reference_date`를 생략하면 공고의 입찰마감일을 기준으로 평가한다. `participation_mode`는 단독 또는 공동수급처럼 평가에 적용할 참가방식이며, 서비스가 의미를 확실히 아는 경우에만 전달한다.

평가 응답에서 확인할 핵심 객체는 다음과 같다.

| `type` | 용도 | 핵심 속성 |
|---|---|---|
| `bid_eligibility_assessment` | 전체 결과 | `outcome`, `lifecycle_status`, `satisfied_count`, `unsatisfied_count`, `needs_review_count`, 버전·지문 |
| `requirement_assessment` | 요건별 결과 | `outcome`, `reason_code`, 요구값, 평가값, 판단 요약 |
| `evidence` | 판단 근거 | 원천, 관찰값, 문서 페이지·조항·발췌, 유효기간, 관찰시각 |

`outcome`은 3값으로 처리해야 한다.

| 값 | 서비스 표시 예 | 의미 |
|---|---|---|
| `satisfied` | 충족 | 현재 근거로 요건 충족 |
| `unsatisfied` | 미충족 | 현재 근거로 요건 불충족 |
| `needs_review` | 확인 필요 | 근거 부족, 지원하지 않는 규칙, 모호성 또는 원문 검토 필요 |

`needs_review`를 `unsatisfied`로 간주하거나 “입찰 불가”로 단정하면 안 된다. 최종 법적 판단이 아니라 공식 데이터와 추출된 공고요건을 바탕으로 한 의사결정 지원 결과로 표시한다.

## 공통 응답 형태

```json
{
  "status": "success",
  "capability": "assess_company_bid_eligibility",
  "objects": [
    {
      "ontology": "assessment",
      "type": "bid_eligibility_assessment",
      "id": "...",
      "properties": {},
      "provenance": [],
      "property_provenance": {}
    }
  ],
  "links": [],
  "total_objects": 1,
  "total_links": 0,
  "truncated": false,
  "registry": {
    "status": "published",
    "version": "..."
  }
}
```

객체 배열의 순서에 의존하지 말고 `ontology`, `type`, `id`로 분류한다. `links`는 객체 사이의 관계를 나타낸다. 감사·이의제기 대응이 필요하면 `include_property_provenance: true`를 사용하고 평가의 버전·지문 및 Registry 버전을 결과와 함께 보관한다. `objects`가 잘리면 근거나 요건별 결과가 누락될 수 있으므로 적격성 평가에서는 충분히 큰 `max_objects`를 지정하고 반드시 `truncated`를 검사한다.

## 오류 처리

| HTTP | 대표 코드 | 처리 |
|---:|---|---|
| 401 | `unauthorized` | token 설정 확인. 사용자에게 원문 token을 노출하지 않음 |
| 404 | `unknown_capability`, `bid_notice_not_found` | Capability discovery 또는 공고번호·차수 확인 |
| 409 | `bid_requirements_not_found` | 요건 추출이 아직 없음을 표시하고 원문 검토 경로 제공 |
| 422 | `invalid_capability_input`, `invalid_bid_notice_id` | 입력 스키마·`공고번호:차수` 형식 확인 |
| 502 | Source/실행 오류 | 일시 오류로 분류하되 상세 오류에 따라 운영 알림 |
| 504 | `capability_timeout` | 제한된 횟수로 지수 backoff 재시도 |

외부 기관 API 조회를 포함한 평가는 일반 조회보다 오래 걸릴 수 있다. 클라이언트 timeout은 Runtime의 기본 Capability 제한인 120초보다 길게 설정하고, 동일 요청 재시도 시 사업자번호·공고 ID·기준일·참가방식을 동일하게 유지한다.

## 업체 정보 조회

입찰체크 서비스는 적격성 평가와 별도로 업체 상세 화면을 구성할 수 있다. 대부분의 조달정보는 사업자등록번호 10자리로 조회하며, 법인 기본·재무정보는 법인등록번호가 필요하다.

### 조달업체 종합 프로필

나라장터 등록업체 기본정보, 등록업종, 등록 공급물품 및 부정당제재를 한 번에 조회한다.

```http
POST /v1/capabilities/get_company_procurement_profile:execute
```

```json
{
  "inputs": {
    "business_registration_number": "1234567890"
  },
  "options": {
    "max_objects": 500,
    "include_property_provenance": true
  }
}
```

응답은 다음 객체와 이들의 관계를 포함할 수 있다.

| `type` | 내용 |
|---|---|
| `business_registration` | 조회 대상 사업자 식별정보 |
| `procurement_supplier` | 나라장터 조달업체 기본정보 |
| `registered_industry` | 나라장터 등록업종 |
| `registered_supply_product` | 나라장터 등록 공급물품 |
| `procurement_sanction` | 부정당제재 정보 |
| `public_organization` | 제재 처분 기관 |

이 Capability는 조달청 공식 API를 호출하므로 운영 Runtime에 해당 Source 인증정보가 설정되어 있어야 한다.

### 입찰 자격 프로필

특정 기준일에 유효한 여성기업·장애인기업 자격과 세부품명별 직접생산확인을 함께 조회한다.

```http
POST /v1/capabilities/get_company_bid_qualification_profile:execute
```

```json
{
  "inputs": {
    "business_registration_number": "1234567890",
    "reference_date": "2026-08-13"
  },
  "options": {
    "max_objects": 500,
    "include_property_provenance": true
  }
}
```

`reference_date`는 필수다. 응답의 `qualification`과 `direct_production_confirmation` 객체에서 상태와 유효기간을 확인한다. 입찰공고 평가 기준일과 동일한 날짜를 전달해야 화면의 업체 프로필과 평가 결과가 일치한다.

### 사업자 상태

국세청 기준의 현재 영업상태와 과세유형을 여러 사업자번호에 대해 한 번에 조회할 수 있다.

```http
POST /v1/capabilities/get_business_registration_status:execute
```

```json
{
  "inputs": {
    "business_registration_numbers": ["1234567890", "0987654321"]
  }
}
```

응답의 `taxpayer_status_observation` 객체에서 사업자 상태, 과세유형 및 관찰시각을 확인한다. 이 API는 사업자등록 진위확인과 다르다. 상호, 대표자명, 개업일자를 검증해야 한다면 별도 `verify_business_registration` Capability의 입력 스키마를 확인한다.

### 혁신기업 인증 확인

다음 Capability는 모두 사업자등록번호 하나를 입력으로 받는다.

| Capability | 확인 내용 | 대표 결과 위치 |
|---|---|---|
| `verify_venture_company` | 현재 벤처기업 공시 여부 | 응답 최상위 `outcome` 및 `venture_company_disclosure` |
| `verify_innobiz_company` | 현재 이노비즈 인증 여부 | 응답 최상위 `outcome` 및 `innovation_certification_observation` |
| `verify_mainbiz_company` | 현재 메인비즈 인증 여부 | 응답 최상위 `outcome` 및 `innovation_certification_observation` |

```json
{
  "inputs": {
    "business_registration_number": "1234567890",
    "sort": "contract_desc",
    "page": 1,
    "page_size": 20
  }
}
```

`outcome`은 각 Capability가 정의한 현재 공시·인증 상태다. 객체가 없다는 사실만으로 상태를 추론하지 말고 `outcome`과 호출 성공 여부를 함께 확인한다.

### 공공조달 계약 이력

수집·정규화된 Teoria Data DB에서 업체가 참여한 공공조달 계약, 업체 역할, 공동도급 방식 및 지분율을 조회한다.

```http
POST /v1/capabilities/get_company_public_procurement_contracts:execute
```

```json
{
  "inputs": {
    "business_registration_number": "1234567890"
  },
  "options": {
    "max_objects": 1000
  }
}
```

이 조회는 `contract_participation`과 `contract` 객체를 반환한다. 페이지 집계 기준은 고유
`unified_contract_number`이며 기본 20건, 최대 100건이다. 응답의 `pagination`은 업체가 참여한
고유 계약 수를 나타낸다. 현재 계약업체 Source에는 계약일과 계약유형이 없으므로 이 Capability의
정렬은 계약번호 내림차순만 지원한다. 기간·유형 검색은 계약정보를 결합한 Runtime View를 추가한
뒤 확장해야 한다.

전체 공공조달 계약 검색은 `search_public_procurement_contracts`를 사용한다. 계약체결일 범위는
필수이며 계약명·계약번호·계약기관코드 자유어, 계약유형, 계약방법, 총계약금액 범위를 선택할 수
있다. 정렬은 `concluded_desc` 또는 `amount_desc`이고, 페이지 집계 기준은 고유 계약번호다.

```http
POST /v1/capabilities/search_public_procurement_contracts:execute
```

```json
{
  "inputs": {
    "concluded_date_from": "2026-01-01",
    "concluded_date_to": "2026-08-13",
    "query": "정보시스템",
    "contract_type": "service",
    "contract_method_name": "제한경쟁",
    "total_amount_min": 100000000,
    "total_amount_max": 500000000,
    "sort": "concluded_desc",
    "page": 1,
    "page_size": 20
  }
}
```

### 법인 기본정보와 재무정보

법인등록번호를 확보한 경우 다음 Capability를 사용할 수 있다.

| Capability | 필수 입력 | 내용 |
|---|---|---|
| `get_company_profile` | `corporate_registration_number` | 법인 기본정보, 주소, 연결된 사업자등록번호 |
| `get_company_financials` | `corporate_registration_number`, `fiscal_year` | 요약재무정보, 재무상태표, 손익계산서 |

사업자등록번호만 가지고 법인 기본·재무정보를 바로 조회할 수 있다고 가정하면 안 된다. 법인등록번호가 없으면 조달 프로필과 사업자 상태 등 사업자번호 기반 기능만 제공한다.

### 세부 조회 Capability

종합 프로필 전체가 필요하지 않은 화면이나 운영 진단에는 다음 API를 선택적으로 사용할 수 있다.

- `get_company_qualifications`: 기준일의 여성기업·장애인기업 자격
- `get_procurement_supplier`: 나라장터 조달업체 기본정보
- `get_procurement_supplier_industries`: 등록업종
- `get_procurement_supplier_products`: 등록 공급물품
- `get_procurement_supplier_sanctions`: 부정당제재
- `get_direct_production_confirmations`: 직접생산확인

정확한 입력과 현재 제공 여부는 배포된 서버의 `GET /v1/capabilities`가 반환하는 `input_schema`를 최종 기준으로 한다.

### 조회 결과 해석

다음 상태를 서로 구분해야 한다.

- 호출 성공 + 관련 객체 없음: 공식 원천에서 조건에 맞는 정보가 조회되지 않음
- Capability의 `outcome`이 미등록·미인증 상태: 정상적으로 확인된 부정 결과
- 502 또는 504: 제공기관 오류, 인증정보 문제 또는 timeout으로 확인하지 못함
- `truncated: true`: 조회에는 성공했지만 응답 객체 일부가 제한됨

업체 상세 화면은 “정보 없음”, “해당 없음”, “조회 실패”, “일부만 표시”를 같은 상태로 표현하지 않는다. 각 객체의 `provenance.observed_at` 또는 속성별 provenance도 함께 이용해 정보 기준시점을 표시한다.

## 보안 및 데이터 취급

- Runtime token은 서버 측 secret으로만 보관하고 브라우저·모바일 앱에 배포하지 않는다.
- 사업자번호와 평가 결과는 서비스의 개인정보·기업정보 보존정책에 따라 최소한으로 저장한다.
- 제공기관 API key와 Data DB 접속정보는 입찰체크 서비스에 전달하지 않는다.
- 응답 provenance에는 추적 가능한 원천 정보가 포함될 수 있으므로 일반 사용자용 응답과 운영 감사 로그의 노출 범위를 분리한다.
- 공고 첨부 원문과 추출 결과에는 별도의 보존기간이 적용될 수 있으므로 영구 조회를 전제로 하지 않는다.

## 현재 계약의 제약

- 검색은 게시기간을 필수로 하며 지역·업종과 cursor 페이지네이션은 현재 공개 Capability 입력에 없다.
  숫자형 페이지 탐색은 지원하지만 변경이 잦은 결과 집합의 안정적인 전체 순회는 별도 cursor 계약이 필요하다.
- 공고요건은 최신 `completed` 추출본을 사용한다. 첨부문서가 아직 처리되지 않았거나 추출이 불완전하면 평가가 `needs_review`가 될 수 있다.
- 모든 자연어 요건에 표준 판정 규칙이 연결되어 있지는 않다. 지원하지 않는 규칙은 자동 추측하지 않고 확인 필요로 남긴다.
- Runtime API token은 현재 단일 Bearer token 계약이며 사용자별 권한·quota 계약은 별도로 정의되어 있지 않다. 외부 공개 서비스에서는 API gateway에서 rate limit, token rotation 및 접근 로그를 추가해야 한다.

## 인수 체크리스트

- 운영 URL과 token을 비밀 채널로 수령했다.
- `/health`, `/v1/version`, `/v1/capabilities` 호출에 성공했다.
- discovery의 Registry 버전과 필수 Capability 존재 여부를 배포 시 검사한다.
- 검색 응답의 `truncated`를 처리한다.
- 평가 결과의 3값과 `needs_review` UX를 구현했다.
- 요건 원문, 판단 요약 및 근거를 함께 표시할 수 있다.
- 401, 404, 409, 422, 502, 504를 구분한다.
- token과 사업자정보가 로그에 평문으로 남지 않는다.
- 평가 결과와 함께 기준일, 참가방식, Registry·ruleset·evaluator 버전 또는 지문을 보관한다.
