# 아키텍처

Teoria는 데이터 자산과 업무 의미를 연결하는 플랫폼이다.
플랫폼 위에 물품·법령 도메인이 있고, FormatID는 그 기능을 사용하는 업무 앱이다.
플랫폼의 주 영역은 데이터(`data/`)·Ontology(`ontology/`)·향후 AI(`ai/`)다.
MLOps(`mlops/`)는 별도로 제공한다. AIP·Agent·Tool 실행 계층은 현재 미구현이며,
`ai/`에는 예약 목적을 설명하는 README만 둔다. 기존 Codex 연결과 기능별 AI 처리는 소유 위치에 유지한다.

## 데이터·Ontology·앱

| 영역 | 책임 | 대표 코드 |
|---|---|---|
| 데이터 운영 | 수집 계약, 원본 저장, 재실행·checkpoint | `platform/data/operations/` |
| 메타데이터 | OpenMetadata 조회, 진단 제안, 검토·적용 | `platform/data/metadata/` |
| Ontology | 업무 개념·속성·관계의 작성, 검토, 게시 | `platform/ontology/authoring/` |
| 의미 연결 | 개념과 용어·자산·API·Capability 연결 | `platform/ontology/bindings/` |
| 실행 계약 | Source·Mapping·Capability 검증과 artifact 생성 | `platform/ontology/contracts/` |
| Runtime | 게시 artifact를 이용한 조회·실행·Context | `platform/ontology/runtime/` |
| 업무 도메인 | 물품 추출·정규화·표현 연결, 법령 수집·검색 | `domains/` |
| AI (예정) | 향후 AIP 예약 영역; 현재 실행 기능 없음 | `platform/ai/` |
| MLOps | 공통 모델 목록·버전·운영 API | `platform/mlops/` |
| 예제 | 합성 고객 이탈 데이터·학습·배포·추론 | `examples/customer_churn/` |
| 업무 앱 | 사용자 입력·권한 확인·업무 결과 제공 | `apps/formatid/` |

```mermaid
flowchart TB
    F[FormatID 업무 앱] --> G[물품 도메인]
    G --> D[데이터 처리: 파싱·추출·저장]
    G --> N[의미 제안·프로파일 적용]
    N --> O[Ontology 작성·승인·게시 API]
    N --> B[표현과 게시 개념 연결]
    O --> P[불변 게시 artifact]
    P --> R[Runtime]
    M[메타데이터 관리] --> OM[OpenMetadata]
    M --> SB[Semantic Binding]
    SB --> O
    W[Prefect] --> D
```

폴더는 코드 소유권이고 API·Worker·DB는 실행·저장 경계다.
현재는 Python 프로젝트 하나를 유지하면서 API·MCP·역할별 Worker를 별도 프로세스와 이미지로 실행한다.

## 물품 처리의 경계

1. `domains/goods/data_processing/`이 원문에서 엔티티·관계·속성·조건과 근거를 추출한다.
2. `domains/goods/normalization/meaning_proposals/`가 게시 정의와 비교하고 의미 후보를 만든다.
3. `platform/ontology/authoring/`가 새 업무 정의의 검토·승인·게시를 맡는다.
4. `domains/goods/expression_links/`가 원문 표현과 게시 개념을 연결한다.
5. `domains/goods/normalization/application/`이 고정된 프로파일·규칙을 적용한다.
6. `apps/formatid/`가 결과를 업무 화면에 제공한다.

이 순서는 책임 구분이다. 모든 실행이 새 Ontology를 게시하는 것은 아니다.
추출 표준 자동 채택은 draft이며, Published Ontology 승인이 아니다.
Worker의 의미 쓰기는 인증된 Admin HTTP API를 거친다.

## 저장 권위

| 저장소 | 소유하는 내용 |
|---|---|
| OpenMetadata | 자산·스키마·설명·Owner·Tag·Glossary·물리 lineage·quality·usage |
| Application DB | Business Ontology·Binding·진단 제안/검토/적용·Context·물품 프로파일/표현 연결/승인 이력 |
| Data DB | 수집·처리 실행 상태·문서별 요약·산출물 URI와 checksum |
| 객체 저장소 | 원본·문서별 관찰 본문·추출/적용 결과·불변 게시 artifact |
| Prefect | Workflow 실행·스케줄·재시도·pool·queue |

OpenMetadata entity 상태를 Teoria DB에 복제하지 않는다. 외부 자산은 `MetadataTargetRef`로 참조한다.
기본 의미 경로는 `Physical Asset → Glossary Term → Ontology`다.

## 지켜야 할 경계

- `platform`은 `domains`·`apps`·`examples`를 import하지 않는다. 도메인 연결은 `entrypoints/composition/`에서 주입한다.
- 앱은 SQL과 업무 규칙을 소유하지 않는다. 도메인 서비스가 처리와 저장을 맡는다.
- Ontology에는 지속 가능한 업무 의미를 둔다. API 응답·Runtime projection을 업무 개념으로 만들지 않는다.
- Mapping은 `source record → runtime object`, Binding은 `concept ↔ 의미 대상`이다.
- AI 출력은 Suggestion이다. 승인·적용 성공 전에는 authoritative metadata가 아니다.
- 게시 revision은 수정하지 않는다. Runtime은 checksum을 검증한 버전 artifact만 적재한다.

## Palantir에서 참고한 점

공개 Foundry 문서의 [데이터 통합](https://www.palantir.com/docs/foundry/data-integration/overview/),
[Ontology](https://www.palantir.com/docs/foundry/ontology/overview/),
[Workshop](https://www.palantir.com/docs/foundry/workshop/overview/)에서 데이터 준비·업무 의미·앱의
역할 분리를 참고했다. 이 저장소 구조는 Teoria의 구현 선택이며 Palantir 내부 코드 구조를 뜻하지 않는다.

구체적인 변경 위치는 [저장소 구조](repository-structure.md), 현재 범위는 [로드맵](../roadmap.md)을 읽는다.
