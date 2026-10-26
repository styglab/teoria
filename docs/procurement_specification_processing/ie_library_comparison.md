# IE 라이브러리 비교 검토

2026-10-26. 대상은 Parser 이후, 표준화 이전의 엔티티·계층·관계·속성·요구조건 추출이다.
공식 문서·배포 wheel 소스를 검토하고 격리 환경에서 입력 변환과 원문 위치 연결을 시험했다.
동일 Parser의 세 구간과 실제 Codex를 사용한 제한된 추출 시험도 수행했다.
문서 전체의 정확도·재현율·비용·지연시간 대조 평가는 수행하지 않았다.
기존 서버 2건의 관측도 라이브러리 간 비교 결과로 사용하지 않는다.

## 도입 판단

- **현재 IE를 즉시 교체하지 않는다.** 실제 작은 시험은 세 방법 모두 고정 수치 조건을 보존했지만
  복잡한 제품 계층·관계 정확도와 비용의 우열을 판단하기에는 부족하다.
- **LangExtract는 요구조건 추출의 부분 후보로 먼저 확대 비교**한다. 연결 범위가 작았지만
  단위 대소문자·동명 항목 귀속·enum 검증은 기존 로직을 유지해야 한다.
- **Docling Graph dense는 전체 IE 대체 후보**로 유지한다. 실제 코어 연결에서 입력·스키마를
  맞추는 작업이 필요했다. 요구조건을 값 객체로 정의한 구성에서 고정 수치 조건을 보존했다.
- **Microsoft GraphRAG는 이번 IE 대체 실험에서 제외**한다. 그래프·커뮤니티·요약을 이용한
  질의가 주 용도이며 커뮤니티 계층은 제품 구성 트리와 다르다. 향후 검색·질의에서 검토한다.
- 새 라이브러리를 운영 의존성에 추가하거나 기존 엔진을 삭제하지 않았다.

## 현재 구현과 겹치는 부분

현재 `backend/src/teoria/features/specification_processing/extraction/`에는 다음이 있다.

1. `entity_relation_extraction.py`: 공급 목록·장비 구성 목록을 우선 식별한 뒤 하위 항목·관계를 찾는다.
2. `requirement_extraction.py`, `attribute_extraction.py`: 요구조건 후보와 원문 수치·단위·조건을 추출한다.
3. `attribute_resolution.py`: 대상·납품/지원/기보유 역할·적용 범위를 별도로 판별한다.
4. 원문 위치·필드 검증과 귀속 후 중복 정리.

모델 호출은 `integrations/codex/runner.py`의 비동기 Codex subprocess 실행을 사용한다.
기존 파서는 Kory Parser를 별도 프로세스로 실행하며 제목·문단·표 셀·부모·원문 위치를 보존한다.
따라서 새 라이브러리 도입은 단순히 LLM 호출을 붙이는 작업이 아니라 이 기능 중 어느 책임을
위임할지 선택하는 일이다. Pydantic 객체·그래프 생성 자체는 이미 구현되어 있다.

## 기능·연결 비교

| 기준 | 현재 IE | Docling Graph | LangExtract |
|---|---|---|---|
| 기존 Parser 출력 | node·표·계층을 직접 사용 | DoclingDocument 등으로 변환 필요 | 텍스트와 원문 node/셀 위치 매핑 필요 |
| 제품 골격·하위 항목 | 공급/구성 목록 우선의 도메인 프롬프트 | dense의 skeleton→fill 구조가 가깝다 | Extraction 레코드·attributes로 표현하고 계층 해석을 추가해야 한다 |
| 관계 | 별도 ID·관계 종류·방향·근거 | Pydantic 모델과 그래프 변환 지원 | 관계 레코드 표현은 가능하지만 업무상 귀속은 별도 |
| 속성·요구조건 | 원문 값·단위·연산·한정자·역할·범위 | 해당 요구 스키마와 지시를 작성해야 한다 | 예시·속성 스키마로 작성 가능하나 같은 도메인 정의가 필요하다 |
| 원문 근거 | node·셀·필드 위치와 원문 비교 | verbatim/observed/document/unresolved를 구분 | char/token span 및 alignment status 제공 |
| Codex CLI | 이미 연결됨 | custom llm_client 연결 지점 존재 | custom model provider 연결 지점 존재 |
| 재사용할 기존 기능 | 전체 | 원문·업무 검증, 결과 계약, 역할·범위 해석 | 구조 청킹, 대상·관계 해석, 단위·원문 검증 |
| 추가 의존성 | 현재 잠금 유지 | Docling·docling-core·LiteLLM 등 | Google SDK·pandas·numpy 등도 기본 의존성에 포함 |

Docling Graph의 외부 파일·일반 텍스트 입력은 Docling 변환 경로를 거치며,
DoclingDocument JSON/DocLang은 변환을 건너뛴다. **기존 Parser를 고정하는 비교에서는
원본 PDF를 Docling Graph에 바로 넣지 않는다.** 그러면 Parser와 IE가 동시에 바뀐다.
기존 Parser 결과를 DoclingDocument로 바꾸는 입력 bridge를 먼저 검증한다.
[공식 입력 계약](https://docling-project.github.io/docling-graph/fundamentals/pipeline-configuration/input-formats/)

Docling Graph dense는 구조에 따라 골격을 식별한 뒤 내용을 채우지만 해당 모드의 structured output은
문서상 legacy prompt-schema 방식이다. API-level schema 강제가 기본적으로 같다고 가정하지 않는다.
[공식 dense 문서](https://docling-project.github.io/docling-graph/fundamentals/extraction-process/dense-extraction/)

## 격리 환경에서 실제 확인한 사항

Python 3.12, LangExtract **1.7.1**, docling-core **2.104.0**을 임시 환경에 설치했다.
Docling Graph **1.9.1**은 배포 wheel의 원본 dense 코어도 실제 Codex로 실행했다.
고수준 패키지 전체 설치·문서 변환·최종 graph export는 검증하지 않았다.
백엔드의 `pyproject.toml`·lock·활성 패키지는 변경하지 않았다. 아래 위치 정렬·형식 검사는 고정 fixture다. 실제 Codex 시험은 별도 절에서 구분한다.

### LangExtract

| 확인 항목 | 실제 결과 | Teoria 적용 시 조건 |
|---|---|---|
| `16 core 이상` 원문 구절 연결 | 정확한 문자 범위 반환 | 원문 field 검증과 함께 사용 가능 |
| 원문 `64 GB`, 추출 문자열 `64 Gb` | fuzzy를 꺼도 `MATCH_EXACT`, source slice는 `64 GB` | alignment 상태를 문자·단위 동일성의 증명으로 쓰지 않는다 |
| 같은 청크에 서버 A CPU와 서버 B CPU가 있을 때 한 개의 `CPU`와 `owner=서버 B` 제공 | 앞쪽 서버 A CPU 범위 `[6,9)`에 연결. 서버 B CPU는 `[27,30)` | owner 속성만으로 위치가 결정되지 않는다. 구조별 분리·node/셀 위치 대조가 필요 |
| 원문에 없는 `128 TB` | span 없음 | 근거 미확정을 실패/보류로 기록 |
| 잘못된 JSON 응답, 기본 설정 | 경고 후 해당 청크 결과 0개 반환 | 청크 누락을 성공·무요구조건으로 처리하지 않는다 |
| 같은 응답에 `suppress_parse_errors=False` | `ResolverParsingError` 발생 | 평가에서는 실패를 명시적으로 집계 |

대소문자·동명 항목 시험은 **grounding API의 성질**을 확인한 것이다. 라이브러리가 의미를
잘못 추론했다는 정확도 측정이 아니다. 제공한 ambiguous 문자열에 span이 있어도 대상 귀속이
맞다는 보장은 없다는 뜻이다. 원문 일치에는 Teoria의 대소문자를 보존한 검증이 필요하다.
구조 청킹·원문 위치 맵 없이 긴 문서를 문자열 하나로 연결하는 도입은 권장하지 않는다.

공식 resolver도 토큰 위치 정렬을 구현하며, 단순 원문 위치 연결을 업무 의미 판정으로 보지 않는다.
[공식 resolver 소스](https://github.com/google/langextract/blob/main/langextract/resolver.py)
[공식 extraction 구현](https://github.com/google/langextract/blob/main/langextract/extraction.py)

### DoclingDocument 입력 bridge

원래 Parser 형식의 `{document_id, nodes}`를 DoclingDocument로 직접 검증하면 실패했다.
명시적으로 변환한 시험에서는 제목을 부모로 두는 표와 2행 병합 셀을 구성하고 JSON으로
저장·복원했을 때 부모 참조와 `row_span=2`가 보존됐다.

이는 **문서 모델 변환의 가능성**을 보인 것이며 Docling Graph dense 추출·청킹·그래프 근거가
보존된다는 검증은 아니다. Docling 참조 `#/texts/0`, `#/tables/0`와 기존 node ID·표 셀 좌표의
명시적 매핑이 필요하다. 원문에 없는 페이지·좌표는 합성하지 않는다.

Graph의 provenance도 모두 정확한 위치인 것은 아니다. dense에는 batch 수준 observed 근거가 있고,
문서 전체 fallback이나 unresolved도 있다. 평가에서 이들을 정밀한 field span과 구분해야 한다.
[공식 provenance 문서](https://docling-project.github.io/docling-graph/fundamentals/graph-management/provenance/)

## Codex 연결과 실행 구조

두 라이브러리에 Codex CLI를 기본 모델명처럼 지정하는 연결은 확인하지 못했다.
사용자 정의 연결 지점은 확인했다.

- Docling Graph: `PipelineConfig.llm_client`와 `LLMClientProtocol.get_json_response(...)`.
- LangExtract: `BaseLanguageModel.infer(batch_prompts)`와 pre-configured `model` 인자.

둘 다 검토한 인터페이스가 동기식이다. 기존 async API/Flow 안에서 blocking 라이브러리를
직접 실행하거나 무조건 `asyncio.run()`을 추가하지 않는다. 제한된 별도 worker/process에서 실행하고
현재 Codex의 timeout·동시 실행·취소·인증정보 분리 정책을 유지해야 한다.
OpenAI API provider 지원은 Codex CLI 연결과 같은 뜻이 아니다.
[Docling Graph 프로토콜](https://github.com/docling-project/docling-graph/blob/main/docling_graph/protocols.py)
[LangExtract provider 인터페이스](https://github.com/google/langextract/blob/main/langextract/core/base_model.py)

Docling Graph를 비교할 때는 backend 전체를 자체 추출기로 대체하지 않고 **LLM client 연결만**
Codex로 바꿔 라이브러리의 dense 알고리즘이 실제 실행되게 한다. Pydantic 추출 결과를
기존 관찰 계약으로 변환하고 관계·근거 검증을 적용한다. 생성된 NetworkX 그래프를
곧바로 authoritative BOM이나 Ontology로 채택하지 않는다.

## 다음 실제 품질 비교의 계약

```text
동일 원본 → 동일 Parser 결과
 ├─ 현재 IE
 ├─ DoclingDocument bridge → Docling Graph dense + Codex client
 └─ 구조별 텍스트/위치 맵 → LangExtract + Codex provider
                 ↓
동일 extracted 관찰 계약 → 기존 동결 사례 평가기
```

첫 실험은 서버 3~5개로 adapter와 오류 유형을 확인하고, 그 뒤 분류·중복·공고/양식군과
과거 노출을 관리한 문서군으로 확대한다. 공급 목록, 병합 표, 반복 CPU/메모리, 긴 조건문,
지원 한계와 기보유 품목을 포함한다. 정답은 실행 전에 원문에서 고정한다.

비교 지표:

- 원문에 명시된 항목·요구조건 재현과 누락, 중복.
- 상위 물품 연결·관계 종류·방향의 정확성. 물리적 포함과 조달 범위를 구분.
- 속성 대상·owner, 납품/지원/기보유 역할, per_module/system_total의 정확성.
- 값·단위 대소문자·연산·한정자 보존, precise/approximate/unresolved 근거 비율.
- 실패 청크·문서를 포함한 성공률, 모델 호출·토큰·시간·재시도 비용.

Parser와 Codex 모델을 고정하고 각 도구의 구조·예시 스키마에는 동등한 작성 예산을 준다.
추출 알고리즘이 달라 호출 수를 같게 강제하지 않고 실제 비용·시간을 함께 측정한다.
기존 표준 적용률을 IE 관계 정확도로 재사용하거나, 고정 응답 연결 시험을 LLM 정확도로 발표하지 않는다.
신규 개념의 과도한 세분화는 IE와 별도인 표준관리 후보 통합 문제이므로 평가를 분리한다.

## 근거 자료

- [Docling Graph 1.9.1 배포](https://pypi.org/project/docling-graph/1.9.1/), [의존성·설정](https://github.com/docling-project/docling-graph/blob/main/pyproject.toml)
- [LangExtract 1.7.1 배포](https://pypi.org/project/langextract/1.7.1/), [공식 사용법](https://github.com/google/langextract)
- [GraphRAG 공식 개요](https://microsoft.github.io/graphrag/): 그래프 추출·커뮤니티·요약·질의의 목적

임시 환경·wheel·시험 코드·캐시는 검토 후 삭제하고 이 문서만 남긴다.

## 실제 Codex 발췌 시험

서버 원본 HWPX를 Parser 0.9.13으로 읽고, 서버 명칭·CPU·DIMM의 세 구간을 고정했다.
원본 SHA-256은 `c1aa62fd442c726980bf1fddffc90d8c89b6e049b6b85eb39a6c7ec3452487e4`다.
원본과 저장 parse의 checksum을 확인했다. 첫 구간은 서버 명칭 첫 줄이며 나머지 두 구간은 원문이다.
기존에 노출된 자료의 발췌로서, 신규 문서나 문서 전체 평가가 아니다.

실행 전에 CPU `64 Core`, `128 Thread`, DIMM `256 GB`, `64 GB`의 값·단위·대상 조건 4개를 고정했다.
단위 대소문자는 보존하며, 원문 node에서 값·단위를 확인했다. 연산·모든 한정자·scope·관계 종류는
전체 정답으로 주석하지 않았으므로 이 시험의 일치 수를 의미 정확도나 전체 재현율로 해석하지 않는다.

| 방법 | 엔티티 | 요구조건 후보 | 고정 값·단위·대상·node 근거 조건 | 모델 호출 |
|---|---:|---:|---:|---:|
| 현재 IE 실제 단계 | 3 | 22 | 4/4 | 4 |
| Docling dense 코어: 요구조건을 값 객체로 둔 스키마 | 3 | 21 | 4/4 | 4 |
| LangExtract + Codex provider | 3 | 22 | 4/4 | 1 |

모델은 모두 `gpt-6.1-sol`이다. 현재 IE는 실제 엔티티·요구조건·대상/역할/범위 해석 함수를 사용했다.
LangExtract는 실제 extract와 정렬을 실행했다. Docling은 배포 wheel의 수정하지 않은 dense
skeleton·fill 코어를 실행했지만, 변환/export 진입점을 우회하는 실험용 모듈 로딩을 사용했다.
알고리즘을 재구현하거나 모델 응답을 mock하지 않았다. 정식 public API 통합 성공으로 해석하지 않는다.

### 결과 해석

- 위 요구조건 후보 수는 정확도가 아니다. 작은 수치 시험의 동률만으로 우열을 결정할 수 없다.
- 현재 IE의 관계는 해석된 `component_of` 2개였고, 외부 엔진의 최종 시험에서는 관계가 0개였다.
  발췌에는 물리적 포함을 직접 선언한 문장이 없고 관계 정답도 동결하지 않았다. 이를 관계 정확도나
  라이브러리의 관계 기능 부재로 해석하지 않는다. 복잡한 계층 시험은 남아 있다.
- 총 256GB에 현재 IE는 `system_total`, Docling은 `per_component`를 부여했다.
  모듈당 64GB는 모두 `per_module`로 보존했다. 대상 모델과 적용 범위의 정의를 더 검증해야 한다.
- LangExtract는 scope에 `procurement`, `dimm_configuration`처럼 Teoria 계약 밖의 값을 3개 만들었다.
  수치·원문 위치가 있어도 그대로 운영 계약에 넣을 수 없으며 enum과 후속 검증이 필요하다.
- LangExtract의 1회 호출은 모든 관계·scope 검증을 마친 운영 비용이 아니다. 모델 대기·cache 재실행이
  섞여 있어 실행 시간을 성능 순위로 제시하지 않는다.

### Docling 스키마 연결 과정

첫 시도에서는 요구조건을 독립 ID가 있는 엔티티 목록으로 정의했다. 42개 레코드에 수치는 있었지만
`value_raw="64Core"`처럼 단위가 분리되지 않고 대상 ID도 어긋나 기존 관찰 계약에서는 0/4였다.
이 결과를 원문 수치 4개를 모두 놓쳤다고 해석하지 않는다. 참조 모델만 바꾼 중간 시도에서는
요구조건 목록이 비어 반환됐다.

이후 물품은 엔티티, 그 물품의 요구조건은 `is_entity=False`인 값 객체 목록으로 정의했다.
owner는 포함된 엔티티에서 결정하고, 숫자·단위 분리 규칙을 필드에 명시했다. 이 방식에서
21개 요구조건과 고정 4/4 조건을 얻었다. 문서용 container ID는 필요한 곳에서 입력 document ID로
보완했으며 원문 사실을 추가하지 않았다.

Docling의 component/value object는 물리적인 CPU·RAM 구성품이라는 업무 개념과 다르다.
스키마 보정은 입력·출력 계약 개발이다. 독립 평가에서 추출 품질이 향상됐다는 주장으로 사용하지 않는다.
실패한 초기 연결을 숨기거나 최종 결과만으로 라이브러리의 일반 성능을 주장하지 않는다.

## 실제 시험 후 최종 권고

문서 검토상 Docling은 전체 IE 구조에 가장 가깝지만, 실제 연결 작업에서는 입력·업무 스키마를
맞추는 비용이 컸다. **현재 IE를 기준선으로 유지하고, LangExtract를 요구조건 추출의 부분 후보로
먼저 확대 비교하는 것이 현실적**이라는 판단이다. Docling도 정합한 스키마에서는 수치를 보존했으므로
전체 IE 대체 후보로 유지하되, 입력 bridge와 원문 위치 맵을 갖춘 다음 비교한다.
두 라이브러리를 동시에 운영 체인에 추가하지 않는다.

백엔드 운영 코드·의존성·상위 Flow·표준관리·승인·배포는 변경하지 않았다.
다음 시험은 같은 운영 계약을 대상으로 표·여러 물품·동명 구성품·지원 한계를 포함해야 한다.
