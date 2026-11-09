# 시스템 아키텍처

Teoria는 데이터 자산·업무 의미·AI 실행을 연결한다. 첫 업무 앱은 FormatID(규격서 기반 물품 구조화·분석)다.
코드는 한 저장소에 두고 API·Runtime·MCP·각 Worker는 역할별로 실행한다.
구체적인 코드 위치는 [저장소 구조](repository-structure.md)를 따른다.

## Data·Ontology·연결·실행의 책임

API·DB·파일은 입력 방식이다. 업무 의미를 소스마다 새로 정의하지 않는다.
아래는 기능 소유권이며 별도 서비스나 공통 엔진을 추가하는 배포 구분이 아니다.

| 영역 | 소유하는 것 | 소유하지 않는 것 |
|---|---|---|
| Data | 수집·파싱·추출, 원본 버전, 문서/레코드 내 대상·값·조건·관계·근거, 실행·산출물 참조 | 업무 개념의 승인·게시 |
| Ontology | 소스에 독립적인 유형·속성·관계·자료형·단위 정책, Stable Concept ID, 검토·게시 | 문서별 값·추출 상태·원천 entity 본문 |
| 연결·적용 | 원본 필드/표현과 게시 개념의 연결, 검토 이력, 값 변환·적용 범위 | 독립된 업무 정의 원장 |
| Runtime | 게시 artifact의 Source·Mapping·Capability로 조회·계산·판단·실행 | 작성 DB 조회·의미 자동 게시·지속 수집 |

```text
API·DB → 레코드 해석 ─┐
파일 → 파싱·관찰 추출 ─┴→ 게시 개념 연결·변환 → 업무 객체·관찰 조회 → Capability
                              ↑                                  ↓
                       Ontology 게시 정의                 실행·반영 근거 → 다음 관찰
```

Data의 원본 관찰과 의미 해석은 분리한다. 연결을 바꾸면 새 해석·실행 결과를 남기며 원본 관찰을
덮어쓰지 않는다. 동일 개념 연결은 동일 실물/제품의 식별이 아니다. 문서 대상 ID·Source record ID와
Stable Concept ID는 별도로 유지하고, 소스 간 대조에는 근거 있는 대상 연결이 필요하다.

게시 정의의 공개 값 계약은 `semantic_modeling/ontology/publication_contracts.py`다.
인증된 Admin의 `GET /v1/admin/ontology-authoring/versions/{version_id}/publication`이
현재 게시된 원본 artifact와 참조를 제공한다. 정의 조회에 사전 등록은 필요하지 않다.
사전은 표현 예시·승인 연결을 보완하며 프로파일은 문서 적용 정책을 고정한다.
API Mapping·문서 프로파일은 같은 게시 참조·수치/단위 정책·`SemanticObservation`을 사용한다.
운영 Runtime은 이 Admin API를 호출하지 않고 기존의 checksum 검증 bundle을 사용한다.

규격서의 선택형 Ontology 연결 비교는 고정 관찰에 대한 Suggestion이다. 게시 정의 참조만으로
실행할 수 있으며, 기존 사전 snapshot 입력은 표현 예시를 위한 호환 경로로 유지한다.
비교 제안은 승인 연결·프로파일이나 Published Ontology를 자동 변경하지 않는다.
명시적 문서 처리의 `use_expression_dictionary: false`는 원문 표현 등록을 생략하는 선택이다.
게시 의미 적용의 승인 조건을 완화하지 않으며 미연결 관찰·제안은 그대로 보류·저장한다.

## 두 작업 공간과 공통 운영

| 영역 | 소유하는 기능 | 현재 범위 |
|---|---|---|
| Ontology·업무 실행 (`semantic`) | Metadata·Ontology·Semantic Binding·Source·Mapping·Runtime Contract·Capability·Runtime·MCP | 의미 작성·검토·게시와 실행 기반; 활성 업무 Capability 연결은 후속 |
| 모델 개발·운영 (`mlops`, 선택형) | 학습·평가·모델 등록·추론 배포 | 합성 데이터·고정 데모 모델 중심; 범용 모델 승인·배포와 운영 모니터링은 후속 |
| 공통 운영 | Prefect 실행·스케줄·취소·재시도, 인증·권한·감사·실행 추적과 저장소 기반 | 공통 기반을 사용하되 역할별 Worker·credential·자원 정책 유지 |
| 업무 앱 (`formatid`) | 규격서 입력·구조화·결과 탐색·비교 | 물품 도메인의 사전·표준 작성 경로를 이용하며 별도 선택 실행 가능 |

모델 개발·운영은 OpenMetadata나 Semantic Runtime을 필수로 요구하지 않는다.
Ontology·업무 실행도 로컬 학습이나 MLflow를 필수로 요구하지 않는다.
두 영역의 연결은 배포 모델의 명시적 입출력·버전을 Capability에 연결하는 방향으로 발전시키며,
현재 이 연결을 제공하는 활성 업무 processor는 없다. 모델 승인·배포는 모델 운영이,
업무 의미·Capability 게시와 실행 정책은 의미 관리·Runtime이 소유한다.

공통 오케스트레이션은 실행 방법을 공유하는 경계다. Ontology 게시와 모델 채택을 같은
승인 생명주기로 합치지 않는다. Pipeline은 Capability Runtime을 직접 호출하지 않으며,
의미 작성은 Admin HTTP API, 모델 등록·배포는 소유 모델 운영 경로를 사용한다.
OpenMetadata metadata, MLflow 모델·실험 상태와 Prefect 실행 상태는 각 원천에서 조회하며
공통 운영을 위해 복제하지 않는다.

물품 사전·프로파일은 도메인별 작성 도구다. 사전이 필요한 문서 경로와 사전 없이
Ontology·Source·Mapping을 작성하는 경로를 모두 지원한다. 표준관리와 고정 표준 적용은
물품의 작성·적용 흐름이며 플랫폼 전체에 강제하는 단계가 아니다. 물품 사전은 게시 Ontology 참조만 저장하며 과거 로컬 정의는 이력으로 보존한다. 물품 사전은 도메인 관리,
표준·사전을 함께 고정한 규격서 처리 기준은 FormatID에 둔다. 데이터·용어 연결은 Ontology 개념에서 관리한다.

## 작업은 어떤 시스템을 거치나

```text
관리 화면 → Admin API → Ontology·Binding·제안·승인
                      → OpenMetadata 자산·거버넌스 정보
                      → Prefect 실행·스케줄

규격서 → 파서·Codex 추출 → 파일/S3 결과 + Data DB 상태
                        → Admin API로 원문 사전·승인 매핑 조회

AI Client → MCP → Runtime API → 게시된 실행 artifact
```

## 누가 무엇을 저장하나

| 시스템 | 책임 |
|---|---|
| OpenMetadata | 데이터 자산·Schema·설명·Owner·Tag·Glossary·품질·사용·물리 계보 |
| Application DB | Business Ontology·Binding·사전·프로파일·표준/사전 적용 버전 참조·제안·승인 이력·Context 설정 |
| Data DB | 실행 상태·문서별 요약·산출물 참조·수집 raw·checkpoint |
| 파일/S3 | 규격서 원문·추출 본문·표준/사전 불변 스냅샷·표준 적용 결과·보고서 |
| Prefect | 실행 순서·Task 상태·스케줄·재시도 |
| Runtime artifact | 게시 Ontology·승인 Binding·실행 Registry를 고정한 스냅샷 |

## 지켜야 할 경계

- 추출 관찰과 AI 제안은 게시된 업무 의미가 아니다. 승인·게시는 별도 단계다.
- 업무 정의는 Ontology가, 원문 표현·근거와 게시 개념 연결은 물품 사전이, 적용 규칙은 프로파일이 관리한다. 새 독립 사전 정의를 작성하지 않는다.
- Pipeline의 의미 작성 요청은 인증된 Admin HTTP API를 사용한다. Capability·Mapping Runtime을 직접 호출하지 않는다.
- MCP는 Runtime HTTP API만 호출하고 DB에 직접 접근하지 않는다.
- OpenMetadata entity 본문은 Teoria DB에 복제하지 않는다. MetadataTargetRef로 연결한다.
- Runtime Mapping은 원본 레코드→실행 객체, Semantic Binding은 업무 개념↔용어·자산·기능 연결이다.
- 의미를 선언한 API Mapping은 같은 bundle의 게시 Ontology와 승인 API Field Binding을 검증한다. 문서 프로파일과 같은 수치·단위 정책을 쓰며 요구조건·제품 명시값·측정값과 출처를 구분한다.
- Published version과 Runtime artifact는 직접 수정하지 않는다. 새 Draft를 승인·게시해 새 artifact를 만든다.

## 현재 구현과 후속 작업

규격서는 추출·검증·사전 연결·결과 저장까지 실행한다. goods 업무 모델은 Draft다.
새 물품 모델의 게시·Runtime 연결과 물품 검색·비교는 후속 작업이다.
법령 수집, OpenMetadata 동기화, 선택형 모델 운영은 전용 Worker에서 실행한다.

사용법은 [사용 안내](../platform-guide.md), 구현 상태는 [로드맵](../roadmap.md),
로컬 실행은 [Compose](../deployment/compose.md), 실제 결과는 [검증 기록](../verification/index.md)을 참고한다.
