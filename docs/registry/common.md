# Registry 공통 원칙

Registry는 원천 계약, 도메인 의미, 의미 대응, 실행 의도를 분리한다. 같은 정보를 여러 Registry에 반복하지 않는 것이 핵심이다.

| Registry | 정의하는 것 | 정의하지 않는 것 |
|---|---|---|
| Source | 원천 API의 필드, 요청·응답, 인증 참조 | 기업정보의 표준 의미 |
| Data Type | 재사용 가능한 값의 형태와 제약 | 원천별 코드 목록 |
| Value Set | 표준 의미 코드와 값 | 원천 필드 경로 |
| Ontology | Object Type, Property, Link Type | API 호출 방법 |
| Mapping | Source 필드와 Ontology Property의 대응 | 속성 의미의 재정의 |
| Capability | 사용자 의도, 의미 입력, 실행 단계, 반환 타입 | Source 응답 스키마의 반복 |
| Reference metadata | Registry 작성 근거 문서와 출처 | 실행 시 사용하는 데이터 |

## 식별자와 참조

- Teoria가 정의하는 ID는 `snake_case`를 사용한다.
- Object Type은 단수 명사, Capability는 사용자 의도를 나타내는 동사구를 사용한다.
- Source 필드·요청 파라미터 ID는 원본 표기를 그대로 보존한다.
- Ontology Property 참조: `<ontology>.<object_type>.<property>`
- Ontology Object 또는 Link 참조: `<ontology>.<type>`
- Source Operation 참조: `<source>.<operation>`
- Source 필드 참조: `<source>.<operation>.(request|response).<path>`

## 값 모델링

- 범용 표현 형식과 검증 규칙은 `registries/core/data_types.yaml`에 둔다.
- 도메인 표준 코드 집합은 `registries/core/value_sets.yaml`에 둔다.
- 원천이 반환하는 코드와 라벨은 Source Registry에 보존한다.
- 원천 코드에서 표준 Value Set으로의 변환은 Mapping codec으로 처리한다.
- 빈 문자열, 날짜 형식, 숫자 변환 등 원천 표현의 의미를 임의로 Source Registry에서 바꾸지 않는다.

## 버전과 변경

각 YAML의 `registry.version`은 해당 정의의 내용 버전이다. 이미 외부에서 참조되는 ID는 의미를 바꾸지 않고, 호환되지 않는 개념은 새 ID로 추가한다. 운영 publication과 bundle version은 [Registry lifecycle](../architecture/registry-lifecycle.md)의 별도 계층이다.

작성 후에는 반드시 다음 명령을 실행한다.

```bash
teoria validate registries
```
