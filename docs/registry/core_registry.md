# Data Type와 Value Set Registry

공통 값 정의는 `platform/registries/core/`에서 관리한다.

## Data Type

Data Type은 여러 Source와 Ontology에서 재사용하는 값의 표현 계약이다.

```yaml
- id: corporate_registration_number
  base_type: string
  pattern: "^[0-9]{13}$"
  normalization:
    - trim
    - digits_only
```

- `base_type`: `string`, `integer`, `number`, `boolean` 중 하나
- `pattern`: 값 검증에 사용할 정규식
- `normalization`: 허용된 정규화 작업의 선언

날짜처럼 원천 표현이 다른 경우 `date_yyyymmdd`와 표준 `date`를 구분할 수 있다. 실제 Source–Ontology 변환은 Mapping codec이 수행한다.

## Value Set

Value Set은 Ontology Property가 사용할 표준 의미 값의 닫힌 집합이다.

```yaml
- id: business_operating_status_kr
  name: 국내 사업자 영업상태
  description: 대한민국 과세당국 기준의 사업자 영업상태
  values:
    - id: active
      name: 계속사업자
      description: 현재 계속 영업 중인 사업자
```

원천기관의 코드와 라벨은 Source Registry에 남겨두고, 표준 Value Set ID와의 대응은 Mapping에서 `decode` codec으로 정의한다.

Ontology Property는 `data_type` 또는 `value_set` 중 정확히 하나만 사용한다.
