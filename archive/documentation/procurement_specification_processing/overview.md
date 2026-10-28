> **과거 자료·비활성**: 아래 설계·명령·건수는 작성 당시의 기록이다. 현재 사용 안내는 [문서 목차](../../../docs/index.md)를 따른다.

# 조달 규격 인텔리전스 서비스 설계 초안

서비스명은 **조달 규격 인텔리전스**이며 상태는 **설계 제안**이다.
나라장터 일반 물품의 첨부 규격서를 품목별 요구조건으로
구조화하고, 근거가 보이는 검색과 규격 비교를 제공한다. 실제 제품 구성의 기술조건
평가는 후속 단계에 추가한다. 모든 물품의 속성을 먼저 정의하지 않고 문서에서 발견한
조건과 승인된 속성 의미를 분리해 점진적으로 확장한다.

서비스의 핵심 사용자 기능은 물품 규격 검색·공고 간 규격 비교이며, 제품 구성의
기술조건 평가와 조달 관계 분석·업무 Action으로 확장한다. Ontology는 속성 의미·
구성요소·업무 관계를 관리하는 기반이다. Teoria 안에서는 공공조달 Domain의 이름 있는
서비스 기능으로 설계하고, 수집·의미·실행·Metadata의 기존 소유권을 유지한다.

현재 첨부 다운로드·문서 처리·참가자격 판단은 보류되어 있다. 이 설계는 그 정책을
해제하거나 보관 코드를 활성 경로로 복구하지 않는다. 구현 시작 시 기능 범위와
관련 지침을 별도 변경하고, 운영 준비 조건을 충족한 단계만 활성화한다.

기준은 [전체 아키텍처](../../../docs/architecture/overview.md), [저장소 소유권](../../../docs/architecture/repository-structure.md),
[Ontology 경계](../../../docs/platform/ontology.md),
[공식 조달 분류 정책](../platform/domains/public_procurement/procurement_classification.md)이다.
이 문서의 테이블·API·패키지 이름은 구현할 계약의 제안이며 현재 제공 기능이 아니다.

## 단계별 검토 기준

사용자 검토는 [1단계 도메인 모델 검토안](domain_model.md)부터
진행한다. 현재 그 문서는 검토 중이며, 이 전체 초안의 저장소·API·처리·평가 제안은
확정 사항이 아니다. 단계별 검토 결과에 따라 이 초안을 갱신한다.

설계 순서는 도메인 모델 → 문서 파싱 → 문서 이해 → 요구조건 추출 → 속성 사전 →
검증 → 검색·비교 → 업무 Action이다. 문서 파싱은 독립 단계로 다루며 앞 단계의
사용자 검토 전에는 다음 단계의 상세 설계나 구현을 진행하지 않는다.

### 단계별 로직 문서 작성 기준

각 처리 단계는 기능명과 개념만 나열하지 않고 아래 항목을 작성해 검토한다. 작성한
규칙은 검토 대기 상태로 두고, 사용자 검토 후 구현 또는 다음 상세 설계로 진행한다.

| 항목 | 문서에 정할 내용 |
|---|---|
| 목표와 범위 | 해결할 문제, 초기 대상, 비용을 쓰지 않을 대상 |
| 입력 | 필수·선택 정보, 원본 보존, 누락 입력의 의미 |
| 대안과 권장안 | 가능한 처리 방식, 장단점, 권장 이유 |
| 처리 로직 | 실행 순서, 조건과 우선순위, 충돌·모호함의 처리 |
| 결과 | 다음 단계에 넘길 정보, 상태·사유·근거·버전 |
| 실패와 재처리 | 보류·오류 구분, 재시도·대체 처리·사람 검토 경계 |
| 자원 사용 | 네트워크·파서·LLM 호출 여부와 제한·후속 실행 예산 |
| 버전과 영향 | 입력·규칙 변경 시 결과 재현과 재처리 범위 |
| 예시와 검증 | 정상·반례의 기대 결과, 표본·평가 지표·완료 기준 |
| 결정 상태 | 제안·검토 대기·수정·확정 구분과 미해결 사항 |

첫 상세 문서는 [규격서 후보 식별 로직 검토안](verification/pipeline_cleanup_2026_10_20.md)이다.
이전 파일명 규칙 식별기·평가 코드는 삭제했다. 이후 사용자 요청으로 물품 공통
메타데이터 확인 우선순위를 구현하고 서버 문서의 최소 파싱을 검증했다.
[서버 검증 기록](computer_server_validation.md)에 실행 범위와 한계를 남긴다.
전체 Document JSON·문서 이해·운영 처리의 상세 계약은 후속 설계다. 검토하지 않은
단계의 빈 문서·코드 패키지를 미리 만들지 않는다. [과거 평가](evaluation_2026_10_20.md)는 삭제한 실험의 기록이다.

## 1 사용자 결과와 초기 범위

첫 결과는 다음 질문을 서버 규격서의 원문 근거와 함께 답하는 것이다.

1. CPU 두 개 이상과 장착 메모리 128GB 이상을 요구한 공고는 무엇인가.
2. 두 공고의 서버 요구조건에서 무엇이 추가되거나 달라졌는가.
3. 같은 공고에서 서버·스토리지·네트워크 요구조건이 어느 발주 품목에 속하는가.
4. 결과에서 해석되지 않았거나 사람이 확인해야 하는 조건은 무엇인가.

검색 대상은 공고 제목이 아니라 **특정 공고 차수의 특정 발주 품목에 적용되는
규격 스냅샷**이다. 추출 초안은 검토용 검색에 노출할 수 있지만 검토 상태를 표시한다.
신뢰 가능한 결과의 기본 검색 범위는 검토를 거친 스냅샷이다.

첫 검증 품목은 컴퓨터서버(4321150102)다. 처리 흐름과 데이터 계약은 모든 물품에
적용할 수 있게 설계하고 서버 속성·용어는 도메인 데이터로 관리한다. 단독 서버 문서부터
검증하되 다품목·다수 첨부·구성요소가 없는 물품도 공통 모델에서 표현한다.
두 번째 검증 품목은 아직 확정하지 않는다. 초기 첨부 선별 기준은 재설계 검토안에서
결정하며 현재 v3는 파일명으로 후보를 선정하고 원천 참조는 근거 기록에만 사용한다. 선별 파일의
내용 확인과 공고 전체의 문서 완전성은 별개이며, 초기 분석은 선택 문서 범위로 표시한다.
품목 선정은 공고 빈도만이 아니라 첨부 확보율, 문서 다양성, 비교 가능한 속성,
검토 비용과 사용자 질문으로 결정한다. 과거에 임의로 묶어 집계한 제품군은 공식
분류 계층이나 검증된 사업 우선순위로 승격하지 않는다.

초기에 포함하지 않는 결과는 입찰 참가 가능 확정, 납품 모델 추정, 전체 품목 자동
적합 판정, 자동 속성 승인, Graph DB 도입과 범용 Ontology 편집기다.

## 2 책임과 저장소 소유권

이 기능은 공공조달 Domain의 `specification_intelligence`라는 이름 있는 기능으로
소유한다. 다른 Domain에서 재사용이 확인되기 전에는 공통 파서·IE·규칙 엔진 패키지를
새로 만들지 않는다. 외부 라이브러리를 기능 내부에서 조합한다.

| 영역 | 소유 책임 | 쓰기 권한 |
|---|---|---|
| Pipelines | 원본 수집, 파싱, Open IE, 후보 매핑, 배치 검증, 임베딩 생성 | Data DB와 원본 Object Storage |
| Platform 의미 작성 | 속성·구성요소 의미 제안, 검토, 승인, 게시 | Application DB의 Business Ontology 의미 영역 |
| Platform 조달 기능 | 검색, 비교, 추출 검토, 사용자 제품 구성, 평가 | 별도 조달 Workspace DB |
| Runtime | 게시된 의미 artifact와 업무 스냅샷을 사용한 실행 | Data DB는 read-only, 업무 Action은 Workspace DB 전용 역할 |
| MCP | Runtime API의 검색·비교·허용된 Action 호출 | DB 및 Provider 권한 없음 |
| OpenMetadata | 기술·거버넌스 메타데이터의 권위 | 기존 OpenMetadata 변경 경로 |

기존 `teoria_app`에는 문서 본문·요구조건·제품 사양을 넣지 않는다. 사용자 제품과
업무 검토·평가 이력을 위해 **`teoria_procurement_workspace`라는 별도 논리 DB**를
제안한다. 이는 Platform 소유의 조달 기능 저장소이며 기존 App DB의 권위 범위를
확장하지 않는다. 초기에는 기존 Application PostgreSQL 인스턴스 안에서 database와
role을 분리하고, 물리 서버 추가는 요구하지 않는다. 이 논리 DB를 도입하는 migration과
설정·backup 계약은 해당 구현 단계의 별도 변경이다.

Data DB와 Workspace DB 사이에는 SQL join, DB trigger와 분산 transaction을 두지 않는다.
Platform Service가 제한된 async 조회로 불변 ID·checksum을 대조한다. 사용자가 승인한
해석은 Workspace에 저장하며 Pipeline 원 관찰을 수정하지 않는다. Pipeline은 Workspace
DB와 Platform Capability·Mapping Runtime을 호출하거나 직접 읽지 않는다.

속성 의미와 구성요소 정의는 Business Ontology에 속하는 도메인 의미 데이터다.
`AttributeDefinition`은 고정된 형식의 데이터 레코드로 관리한다. 속성 하나를 추가할
때마다 Ontology Object Type이나 SQL column을 추가하지 않는다. 기존 authoring 모델에
없는 레코드 저장·게시 기능은 명시적인 확장으로 구현하며 기존 구현이라고 가정하지 않는다.

### 모듈별 독립 실행 구현 원칙

9개 처리 기능은 **명시적인 입력·출력을 갖고 개별 호출 가능한 모듈**로 구현한다.
전체 파이프라인은 이 모듈을 조합하며, 개별 실행을 위해 전체 Flow를 시작할 필요가
없어야 한다. 이 원칙은 이후 구현의 기준이다. 단계별 상세 데이터 계약과 후속
모듈·CLI·운영 Flow가 이미 구현됐다는 뜻은 아니다.

| 경계 | 구현 기준 |
|---|---|
| 기능 모듈 | 해당 단계의 처리와 결과 생성만 담당한다. 앞뒤 단계를 내부에서 자동 실행하지 않는다. |
| 입력 계약 | 필요한 데이터·artifact 참조·schema 버전·설정을 명시한다. 누락·불일치는 보류 또는 오류로 반환한다. |
| 출력 계약 | 결과와 상태·근거·경고·실행 버전을 반환한다. 다음 단계를 호출하거나 검수 승인을 대신하지 않는다. |
| 저장·조회 | 소유 기능의 저장소 경계를 사용한다. 실행 진입점이 명시적으로 입력을 조회하고 결과를 보존한다. |
| 전체 실행 | Prefect Flow가 순서·분기·재시도·예산·중간 결과 저장·checkpoint를 조정한다. 주요 단계는 Task로 표시한다. |
| 단독 실행 | CLI·Job 등 필요한 진입점에서 같은 기능 구현을 호출한다. Flow와 별도의 처리 로직을 복제하지 않는다. |

독립 실행은 입력 의존성이 없다는 뜻이 아니다. 예를 들어 요구조건 추출에는 문서·
품목·구성요소 후보와 scope 근거가 필요하다. 미확정 귀속은 보류로 허용한다.
저장된 해당 결과를 제공하면 추출만 실행할 수 있어야
하며, 입력이 없다고 다운로드·파싱·품목 식별을 암묵적으로 다시 실행하지 않는다.
`document_parsing`도 확보된 원본으로 바로 실행할 수 있게 하고, URL 다운로드는
실행 진입점의 별도 단계로 둔다. 파서 비교는 동일 원본을 여러 설정으로 실행한다.

중간 결과는 다른 프로세스에서도 다시 읽을 수 있는 versioned artifact 또는 소유
저장소 레코드로 보존한다. 원본 hash, 입력 실행 ID·출력 checksum, 처리 코드·도구·
모델·프롬프트·설정·사전 버전 중 해당되는 항목을 연결한다. 문서 요소 ID는 해당
파싱 실행과 함께 참조하며, 다른 실행의 요소 ID를 같은 것으로 취급하지 않는다.
저장 위치나 완성되지 않은 공통 Document JSON schema를 이 원칙만으로 확정하지 않는다.

| 단독 실행·변경 사례 | 재사용할 입력 | 다시 처리할 범위 |
|---|---|---|
| 첨부 선별 규칙 변경 | 기존 첨부 메타데이터 | 후보 선별. 파일 내용 확인은 별도 |
| 동일 문서의 파서 비교 | 같은 hash의 원본 파일 | 파싱·품질 평가. 이후 분석은 새 파싱 결과를 명시적으로 선택 |
| 문서 적합성 판단 수정 | 저장된 파싱 결과 | qualification. 판정 변화가 품목 분석 범위에 주는 영향도 기록 |
| 품목 경계 수정 | 문서 구조와 수정 근거 | 품목 식별 및 영향을 받는 구성요소·요구조건·통합·매핑·검증 |
| 귀속·통합 규칙 변경 | 기존 요구조건·품목·구성요소 후보와 원문 근거 | 통합 및 영향을 받는 매핑·검증. 원문 추출 관찰은 보존 |
| 속성 사전 변경 | 기존 추출 요구조건과 새 게시 사전 artifact | 속성 매핑 및 관련 검증. 다운로드·파싱은 재사용 |
| 검증 규칙 변경 | 기존 원문 근거·scope·요구조건·매핑 결과 | 요구조건 검증 |

입력·schema·설정의 호환성과 checksum을 확인한 결과만 재사용한다. 앞 단계의 결과가
바뀌면 의존하는 후속 결과의 갱신 필요성을 기록한다. 재처리는 새 실행과 결과를
생성하고, 동일 실행의 retry는 중복 적재를 방지한다. 기존 결과와 승인된 snapshot을
자동으로 덮어쓰거나 최신이라는 이유만으로 다른 입력 버전과 섞지 않는다.

일반 계산·판단은 일반 함수로, HTTP·DB I/O는 native async 경로로 구현한다. 동기
파싱·CPU 작업은 제한된 별도 Task·Job으로 격리한다. 독립 실행을 위해 기능마다
서버·REST API·설치형 패키지를 만들지 않는다. 먼저 소유 프로젝트의 공공조달
`specification_intelligence` 기능 안에 구현하고 필요한 진입점만 추가한다.
Pipeline은 이 과정에서 Platform Capability·Mapping Runtime을 호출하지 않는다.

각 모듈 구현을 완료할 때는 단독 호출, 누락·호환되지 않는 입력 처리, 원문 근거의
보존, 저장된 결과를 이용한 필요한 범위의 재실행을 확인한다. 전체 Flow와 단독
실행이 같은 설정·버전의 기능 구현을 사용하는지도 검증한다.

## 3 전체 처리 경로

현재 구현은 **사전 초안 구축용 오프라인 배치 하나**다. 새 규격서를 기존 사전에
매핑하는 운영용 흐름은 아직 구현하지 않았다. 두 흐름의 단계·입출력·구현 상태는
[사전 구축 배치와 운영 처리 흐름](verification/retired_semantic_batch.md)을 기준으로 한다.
아래 실행 단계는 사전 구축 배치에 해당하며, 파싱 완료 결과를 입력으로 받는다.

현재 실행 기준은 [의미 분석 배치](verification/retired_semantic_batch.md)다. 이미 파싱된 결과를 입력으로
받아 구매 목적과 최상위 납품 대상을 이해하고 재귀 구성 트리를 식별·검토한 뒤 각 대상의 규격을 추출한다. 문서 전체의 동일 대상·귀속을
정리하고 원문 검증을 거친 뒤 문서 간 의미를 매핑한다. 이전 첨부 선정·문서 적합성·
구성 분석·사전 bootstrap 코드는 삭제했으며 운영 DB·API·배포에 연결하지 않는다.

| 처리 | 현재 구현 |
|---|---|
| 입력 확인·고정 | `semantic_batch.prepare`, 기존 원본·파싱 결과·실행 기록 검증 |
| 공고 이해·구성 식별 | identify, 구매 목적·최상위 대상·재귀 구성 트리와 원문 근거 |
| 구성 검토 | review_structure, 구매 범위·부모 관계 검토 후 속성 추출 허용 |
| 품목별 규격 추출 | extract, 품목별 작업과 공통·미귀속 구간 작업 |
| 동일 대상·관계 정리 | resolve, 원래 관찰을 보존한 동일성 연결과 조건 귀속 |
| 원문 검증 | validate, 품목·조건 누락·과분리·오귀속·오병합 검사, 오류 시 통합 차단 |
| 문서 간 의미 통합 | integrate, 공통 개념·속성·관계 후보와 매핑 |
| 결과 저장 | finalize, 검토 기록·그래프·사전 초안과 미해결 항목 보존 |
| Harness2 검색 평가 | `search_*.py`, 기존 고정 코퍼스·평가 경로 보존 |

### 현재 구성 판단

공급 목록과 별도 규격 절을 우선하고 표·목차·본문을 함께 확인한다.
제목 번호나 들여쓰기를 물리 구성 계층으로 복사하지 않는다. 장치뿐 아니라 별도
규격이 있는 공간·시스템·소프트웨어·부속품 묶음도 주요 단위가 될 수 있다.
하위 장치와 외부 제공품·시험 대상·서비스를 구별하고 해석 관계는 명시한다.

원문의 표·셀·문단 위치와 인용을 보존한다. 같은 대상의 여러 페이지 설명을 연결하되
동일 이름만으로 합치지 않는다. 규격은 실제 소유 대상에 연결하고, 주요 화면에
모아 보여준다는 이유로 인버터 출력을 차량 전체 속성으로 옮기지 않는다.

### 모듈별 독립 실행과 LLM

[Codex 분석 방식](verification/pipeline_cleanup_2026_10_20.md)에 따라 현재는 대화형 Codex가 의미 제안을 작성한다.
`prepare`는 지시문·원문·출력 스키마를, `validate`는 구조·근거 검사 결과를,
`evaluate`는 별도 주요 목록과의 대조 결과를 저장한다. 이 CLI가 모델을 자동 호출하지 않는다.
내부 Qwen·외부 모델 API·OCR은 사용하지 않는다.

각 모듈은 명시적 입력·출력을 받고 기존 산출물을 덮어쓰지 않는다.
향후 전체 조건 추출과 사전 구축도 독립 계약을 갖추되 단계별 LLM 호출을 강제하지 않는다.

### 검증과 승인

코드는 인용·값·참조·부모 역할·순환을 검사한다. 미배정 텍스트·미확인 이미지도 남긴다.
구조 검사 통과와 주요 목록 일치는 의미 귀속·완전성·학습 라벨 승인을 보장하지 않는다.
원문 의미 검토와 승인 상태를 구별하고 미해결 조건은 보류한다.

[네 표본 검토](verification/composition_review_2026_10_20.md)는 주요 목록 28개·대표 규격
27개의 개발 결과다. 정답을 이미 본 표본이므로 신규 문서 Precision·Recall이 아니다.
요구조건 관찰·사전 생성·최종 검토는 [새 구축 경로](verification/pipeline_cleanup_2026_10_20.md)를 따른다.
관찰의 의미 판단은 Codex가 수행하며 전체 문서 완전성을 코드만으로 보장하지 않는다.

## 4 핵심 식별자와 데이터 모델

| 모델 | 역할과 불변 조건 |
|---|---|
| `procurement_case_ref` | 기존 공고·낙찰·계약 연결을 참조한다. 기존 식별 체계를 복제하지 않는다. |
| `notice_revision_ref` | 기존 공고번호·차수를 고정한다. 별도 공고번호의 재공고는 근거 없이 합치지 않는다. |
| `document_version` | 첨부 참조, 파일 hash, 원본 URI, MIME, 원본 filename, 확보 시각을 보존한다. |
| `parse_run` | 원본 버전, parser·OCR·설정 버전, 상태와 출력 checksum을 고정한다. |
| `document_element` | 문단·표·셀·이미지와 문서 내 위치를 식별한다. ID는 parse run 안에서 안정적이다. |
| `extraction_run` | parse run, 모델·프롬프트·schema·사전 버전과 사용량을 고정한다. |
| `tender_line_item` | 공고 안에서 독립적으로 발주하는 품목과 수량·금액의 관찰이다. |
| `component_instance` | 한 품목 내부의 CPU·NIC 등 특정 구성요소 또는 구성요소 집합이다. |
| `requirement_candidate` | 미매핑을 허용하는 요구조건 관찰이며 재실행으로 덮어쓰지 않는다. |
| `requirement_expression` | 조건 leaf와 논리 node로 구성하는 유한 조건식이다. |
| `specification_snapshot` | 적용 문서, 품목 배정, 조건식과 검토 결정을 고정한 불변 해석이다. |
| `attribute_definition` | 승인할 수 있는 속성 의미와 타입·단위·적용 범위를 정의한다. |
| `product_model_version` | 제조사 모델 계열의 공식 지원 범위와 증빙 버전이다. |
| `product_configuration_version` | 사용자·조직이 등록한 실제 장착 구성과 그 증빙이다. |
| `compliance_assessment` | 특정 제품 구성과 규격 스냅샷의 기술조건 평가 기록이다. |

ID와 version을 분리한다. 변경되지 않는 업무 식별자와 특정 내용의 revision ID를 함께
사용한다. 모든 내용 hash에는 canonical serialization과 hash 알고리즘 버전을 기록한다.
같은 파일 hash라도 여러 공고의 첨부 참조와 접근권한은 각각 보존한다.

각 `specification_snapshot`은 하나의 공고 차수·발주 품목에 속한다. 공고 공통 조건은
별도 원본 조건으로 저장하고 snapshot에 적용 관계를 둬서, 모든 품목에 원문을 복제하지
않으면서도 평가 시 유효 조건을 재현한다. 한 발주 품목의 여러 첨부는 같은 snapshot에
포함할 수 있다. 복수 품목 간 호환성은 품목별 조건을 넘어서는 공고 수준 식으로 보존한다.
MVP는 그 존재를 표시하고 공고 전체 적합 판정은 보류한다.

### 공식 분류와 자체 분류

분류 참조에는 `system`, `code`, `version`, `label`, `source_ref`, `mapping_status`를
둔다. 공식 원천 코드·명칭과 자체 분류를 별도로 저장하고 자체 코드는 공식 코드처럼
표시하지 않는다. 상위 분류는 공식 master 또는 검토된 자체 관계로만 연결한다.
10자리 코드 접두어를 잘라 공식 계층을 추정하지 않는다.

물품분류·세부품명·물품식별에 사용하는 번호의 역할은 각각 원천 계약과 대조한다.
숫자의 길이나 명칭 유사성만으로 ProductModel을 확정하지 않는다. 공고의 구매대상물품
목록 한 행이 문서의 발주 품목 한 행과 항상 일대일이라고 가정하지 않는다.

### 발주 품목과 구성요소

`tender_line_item`은 `source_line_key`, `category_refs`, `quantity`, `quantity_unit`,
`unit_price`, `amount`, `currency`, `tax_basis`, `evidence_refs`, `alignment_status`를
갖는다. 미확인 값은 null이며 0으로 대체하지 않는다. 원문 품목 번호와 추출 순번을
분리하고 문서 사이 품목 연결은 근거가 있는 assertion으로 저장한다.

구성요소의 의미 유형인 `component_type`과 실제 규격 안의 `component_instance`를
분리한다. 같은 서버 안에서도 NIC A와 NIC B, 시스템 디스크와 데이터 디스크는 다른
instance가 될 수 있다. 구성요소가 없는 물품은 품목 자체에 조건을 연결한다.

## 5 요구조건과 속성 의미

`requirement_candidate`는 다음 필드를 갖는다.

| 필드 | 의미 |
|---|---|
| `requirement_id`, `extraction_run_id` | 추출 관찰의 식별자와 실행 |
| `target_ref`, `scope_kind` | 공고 공통·품목·구성요소 대상 |
| `component_ref`, `raw_component_path` | 해석한 구성요소와 원문 경로 |
| `attribute_id`, `attribute_version` | 매핑한 속성 의미. 미매핑이면 null |
| `raw_attribute_name`, `raw_text` | 원문 속성명과 요구조건 |
| `operator`, `typed_value` | 제한된 비교 연산자와 타입이 있는 값 |
| `raw_value`, `raw_unit`, `normalized_value`, `canonical_unit` | 원문과 정규값 |
| `aggregation_scope`, `quantifier` | 각각·합계·모두·최소 몇 개 등의 적용 범위 |
| `value_basis` | 장착·최대지원·정격·측정·불명 |
| `obligation` | mandatory·preferred·informational·unknown |
| `evidence_refs` | 원문 요소와 위치·인용문 |
| `mapping_status`, `validation_findings` | 매핑 결과와 검증 실패 이유 |
| `uncertainties` | 범위·논리·단위 등에 대한 미해결 해석 |

`typed_value`는 discriminated union으로 number, range, string, boolean, enum,
set, reference를 구분한다. 숫자는 decimal 문자열로 교환해 부동소수점 반올림을
피한다. 일반 문장이나 모델의 동등성 요구는 reference 또는 미해석 조건으로 남긴다.
모든 값을 문자열 하나나 JSON 한 column에만 넣지 않고 검색용 타입별 값을 함께 적재한다.

`attribute_definition`에는 stable `attribute_id`, definition version, 명칭·정의·alias,
데이터 타입, quantity kind, canonical unit, 허용 연산자, 적용 category·component,
허용 scope·value basis, 예시·반례, 상태, 승인·게시 이력을 둔다.
alias는 category·component·언어의 문맥을 갖는다. 이름이 같아도 의미가 다르면
독립 ID를 사용하고, 충돌하는 alias는 자동 확정하지 않는다.

속성 정의의 lifecycle은 `draft → in_review → approved → published → deprecated`다.
승인만으로 운영 Runtime에 노출하지 않고 checksum이 고정된 게시 artifact에 포함한다.
정의 병합은 대체 관계를 남기며 과거 definition과 평가 참조를 삭제하지 않는다.
승인된 속성 레코드와 Ontology Stable Concept의 연결은 version별 revision ID로 대체하지 않는다.

신규 발견은 `match`, `new_attribute`, `ambiguous`로 분류한다. `match`도 문서의
관찰·매핑 결과이며 사전의 권위 변경이 아니다. 새 alias·속성·구성요소는 Suggestion으로
제안하고 사람이 검토한다. 기존 Metadata Intelligence의 지원 enum과 applier를
조용히 확장하지 않고 도메인 제안 계약을 명시적으로 추가한다.

## 6 조건식과 서버 예시

조건식 node는 `all`, `any`, `not`, `implies`, `at_least`와 `requirement_ref`를
지원하도록 설계한다. MVP evaluator는 검증한 subset인 `all`, `any`와 정량 leaf만
실행한다. 나머지는 보존하되 `unsupported_expression`으로 판정을 보류한다.
순환 참조, 빈 그룹, 중복 child, 정의되지 않은 참조, 과도한 깊이와 node 수를 거부한다.
임의 Python·SQL·자연어 프로그램을 조건식으로 실행하지 않는다.

조건부 요구에는 전제조건과 결과조건을 각각 연결한다. 전제 미확인은 조건을 생략할
근거가 아니다. `not_applicable`은 명시적으로 적용 대상이 아님이 확인된 경우만 사용한다.

사용자가 제시한 서버 예시는 다음처럼 해석과 미해결 사항을 나눈다.

| 원문 | 저장할 해석 | 검토 사항 |
|---|---|---|
| 수량 23대 | line item quantity 23 | 문서 품목과 공고 품목의 연결 |
| 단가 26,300,000원 | unit price와 통화 | 부가세 포함 여부 |
| 총액 604,900,000원 | amount | 수량×단가 산술은 일치하나 원문 금액도 보존 |
| 2U 이하 | chassis height ≤ 2 U | 비교 프로파일에 U 정의 필요 |
| 2CPU 이상 | processor count ≥ 2 | CPU socket과 실제 장착 CPU 표현 확인 |
| 16Core 이상 2P 기준 | core count ≥ 16 후보 | CPU당인지 시스템 전체인지 미확정 |
| Clock Speed 2.9GHz 이상 | frequency ≥ 2.9 GHz 후보 | base·boost 구분 미확정 |
| 64GB 이상 DDR5 이상 | 용량과 memory technology 두 조건 | 장착 용량 확인, DDR 세대는 문자열 대소비교 금지 |
| SSD 960GB 이상 | SSD capacity ≥ 960 GB 후보 | 디스크당·합계·수량과 GB·GiB 구분 |
| 1Gbps TX 2Port 1개 이상 | 속도·포트·NIC 수량 분리 후보 | TX 해석과 장치당 포트 범위 확인 |
| PSU 800W 이상 | PSU rated power ≥ 800 W | PSU당인지 합계인지 확인, 소비전력으로 사용 금지 |
| 핫스왑 지원 | 해당 SSD 또는 PSU의 boolean | 수식 대상 구성요소와 전체 적용 범위 |

기준 CPU 모델 두 개와 ‘동등 이상’은 모델 reference와 비교 근거 요청으로 남긴다.
원문 `및`을 근거 없이 `any`로 바꾸거나 모델명·클럭만으로 성능 순서를 만들지 않는다.
동등성 판정은 지표·시험 조건·근거가 승인된 별도 비교 프로파일이 있을 때만 수행한다.

## 7 문서 파싱과 근거

파서 선정의 근거는 [OCR 제외 비교 결과](parser_evaluation_2026_10_20.md),
독립 모듈의 입출력·검사·공통 JSON 최소 계약은 [문서 파싱 설계](document_parsing.md)에
정리한다. 현재 권장안은 kordoc 기본 구조 파싱과 형식별 원본 검사·근거 연결이다.

이전 선별 평가는 **kordoc 4.22.15**, 옵션 `ocr: false`, `images: false`로 고정했다.
이후 [파서 평가 기준서](parser_evaluation_criteria.md)에 따라 선정 후보의 동일 원본으로
여러 도구·설정을 비교했다. 현재는 kordoc을 우선 사용하고 OCR은 제외한다. 전체 파싱 모듈의 공통 Document JSON
변환은 비교 결과에 따라 확정한다. 지원 형식·구조·
위치 정보의 실제 확보 범위는 고정 버전과 샘플로 확인하며, 확장자나 라이브러리의
출력 필드 존재만으로 원문 구조가 완전하게 보존됐다고 판단하지 않는다.

Document JSON은 다음을 보존한다.

- heading·section·paragraph·table·row·cell의 계층과 읽기 순서
- 제목 수준·부모 section·소속 블록, 명시적 계층과 추정한 계층의 구분 및 추정 근거
- 셀의 row span·column span, 반복 헤더와 페이지를 넘는 표 연결
- 페이지 번호·bbox 또는 문서 내부 anchor, 원문 문자열과 문자 범위
- OCR 여부, parser 경고, 인식하지 못한 영역, 원본 파일 hash

페이지 좌표가 없는 형식은 section·paragraph·table·cell anchor를 사용한다. 변환 PDF를
추가하면 원본 anchor와 변환 페이지의 대응 근거를 별도로 보존한다. 파서를 바꾸면
element ID가 달라질 수 있으므로 과거 `parse_run`을 남기고 새 근거로 재연결한다.
Markdown·HTML은 LLM용 파생물이며 근거 좌표의 기준 저장소로 사용하지 않는다.
제목 계층은 품목·구성요소·요구조건의 scope 판단에 사용한다. 파서가 반환하지 않은
page·bbox·outline을 임의 생성하지 않으며, 구조가 누락된 구간은 품질 진단에 남긴다.

규격 조건은 여러 문단·표 헤더·셀에 걸칠 수 있어 evidence를 복수 참조한다.
품목 경계는 시작·종료 위치 하나뿐 아니라 비연속 element 집합을 허용한다.
첨부 내 공통 조건과 품목별 조건을 함께 표시하고 근거 없는 상속·우선순위는 만들지 않는다.

첨부 manifest에는 확보·실패·암호화·손상·미지원 상태를 각각 기록한다. 관련 첨부가
미확보됐거나 ‘별첨 참조’를 해소하지 못한 경우 전체 규격 coverage를 complete로
표시하지 않는다. 문서에 없는 조건을 ‘요구하지 않음’으로 바꾸지 않는다.

외부 문서 내용은 데이터로만 취급한다. 문서 안의 지시문이 LLM의 도구 실행·권한·
프롬프트를 변경하지 못하게 한다. 다운로드는 크기·형식·redirect·압축 해제 상한과
접근 대상 정책을 적용하고, 비공개 사용자 사양서는 외부 모델 전송 허용 범위를 확인한다.

## 8 추출과 검토

파이프라인 순서는 다음과 같다.

1. 첨부 manifest와 원본 checksum을 확정한다.
2. 형식별 파싱을 실행하고 누락 영역을 기록한다.
3. 공통 조건·품목 목록·품목별 범위를 추출하고 연결 후보를 만든다.
4. 작은 근거 묶음마다 Open IE를 실행한다. 표 헤더와 단위·공통 조건을 함께 전달한다.
5. 게시 사전에서 exact·alias·keyword·vector 순으로 후보를 검색한다.
6. 의미·scope·unit·value basis를 대조해 mapping 결과를 만든다.
7. 타입·단위·연산자·근거 일치·논리·중복·품목 연결을 검증한다.
8. 후보 결과와 진단을 원자적으로 적재한다. 실패는 실패 상태로 남긴다.

Structured Output schema 통과는 원문 충실성이나 조건 완전성의 증거가 아니다.
LLM confidence만으로 자동 승인하지 않는다. 검토자는 최소한 품목 배정, 필수조건,
수치·단위·범위, 논리와 evidence를 확인한다. 일괄 승인도 검토한 정확한 후보 ID와
hash 집합을 기록하며 프로파일 승인으로 미래 추출을 포괄 승인하지 않는다.

검토 상태는 `draft → in_review → accepted/rejected`로 관리한다. 수정은 원 관찰을
덮어쓰지 않고 `review_amendment`를 만든다. accepted snapshot은 불변이며 새 원본·
재추출·의미 변경의 반영은 새 snapshot을 생성한다. 승인 후 원본이 바뀌면 기존 결과는
stale로 표시하되 과거 시점 조회에는 보존한다.

구조·mapping·추출 검토와 completeness는 별도 축이다. `coverage_status`는
`complete_for_scope`, `partial`, `unknown`이고 적용 문서·품목 범위를 명시한다.
MVP의 complete 판정은 manifest·파싱 진단·참조 해소와 사람의 범위 검토를 요구한다.

## 9 저장 테이블과 검색 인덱스

다음은 역할을 확정하기 위한 논리 테이블 목록이다. 실제 migration은 구현 단계에서
소유 프로젝트에 새 순번으로 추가하며 기존 SQL을 수정하지 않는다.

| 저장소 | 테이블 또는 artifact | 주요 내용 |
|---|---|---|
| Object Storage | 원본·Document JSON·렌더링·추출 원문 | checksum으로 식별하고 공고·조직 권한 참조를 분리 |
| Data DB | `specification_documents`, `specification_parse_runs`, `specification_extraction_runs` | 원본·처리 이력과 진단 |
| Data DB | `specification_line_items`, `specification_components`, `specification_requirement_candidates` | 불변 추출 관찰과 typed value |
| Data DB | `specification_evidence`, `specification_candidate_expressions`, `specification_candidate_vectors` | 근거·조건식·검색용 파생값 |
| App DB 의미 영역 | 도메인 속성·구성요소 정의와 proposal·review | Business Ontology 의미와 승인·게시 |
| Workspace DB | `document_review_cases`, `requirement_amendments`, `specification_snapshots` | 검토와 승인된 해석 |
| Workspace DB | `specification_search_requirements`, `specification_search_vectors` | 승인된 해석에서 재생성 가능한 검색 projection |
| Workspace DB | `product_models`, `product_configurations`, `product_evidence` | 조직별 제품과 실제 구성 버전 |
| Workspace DB | `compliance_assessments`, `assessment_findings`, `action_events` | 평가·실행 상태와 감사 기록 |
| Artifact Store | 버전형 속성·단위·비교 프로파일 | 게시된 의미의 checksum 검증 가능한 실행 계약 |

Workspace migration의 제안 위치는
`backend/database/procurement_workspace_migrations/`이며 App DB migration runner와
명시적으로 분리한다. 도메인 저장 구현·async connection 경계는 Platform이 소유한다.
같은 PostgreSQL 인스턴스여도 Runtime Data DB role에 쓰기 권한을 주지 않는다.

수치 projection에는 attribute version, numeric value·lower·upper, 단위,
operator, scope, value basis, component ref와 evidence ref를 보존한다.
JSON에는 복합 표현을 남기고 자주 검색하는 값은 타입별 column으로 둔다.
아직 검증되지 않은 속성을 운영 검색 인덱스의 확정 속성으로 승격하지 않는다.

초기 인덱스는 품목·snapshot·attribute·scope의 B-tree, 원문·alias의 full text,
pgvector를 사용하는 임베딩 인덱스 조합으로 설계한다. 실제 pgvector 설치·버전·
인덱스 방식은 데이터량과 정확도 측정 후 확정한다. 임베딩에는 모델·차원·입력 hash와
버전을 저장하고 서로 다른 모델의 벡터를 직접 비교하지 않는다.

조직 범위와 접근권한은 SQL·vector 후보 생성 단계부터 적용한다. 권한 없는 문서를
Top-K에 포함한 뒤 화면에서만 지우는 방식은 허용하지 않는다. 검색 projection에는
OpenMetadata entity 본문을 복제하지 않는다.

## 10 자연어 검색 계약

검색 intent는 다음을 구분한다.

| Intent | 의미 |
|---|---|
| `search_requirements` | 문서가 무엇을 요구했는가 |
| `find_similar_specifications` | 비교 가능한 규격 중 무엇이 유사한가 |
| `compare_specifications` | 특정 두 규격의 요구조건 차이는 무엇인가 |
| `find_compatible_opportunities` | 제품 구성과 비교해 충족 여부를 평가할 후보 공고는 무엇인가 |
| `analyze_requirement_trends` | 같은 의미·범위의 요구조건이 기간별 어떻게 달라졌는가 |

LLM은 자유 SQL 대신 schema가 고정된 DSL을 생성한다. 서버가 attribute·operator·
단위·권한·시간 범위·비용 상한을 검증한 뒤 parameterized SQL로 변환한다.
동일 품목·동일 구성요소 조건을 서로 다른 line item이나 NIC에서 모아 만족시키지 않는다.
질문의 속성이나 적용 범위가 모호하면 `clarification_required`와 후보 의미를 반환하고
자의적으로 선택하지 않는다. 기본값을 적용할 때는 사용한 기본 의미를 결과에 표시한다.

```json
{
  "intent": "search_requirements",
  "category_ref": {"system": "pps_detail_product", "code": "4321150102"},
  "snapshot_state": "accepted",
  "notice_version_policy": "latest_as_of",
  "as_of": "2026-10-20T00:00:00Z",
  "line_item_predicate": {
    "all": [
      {"attribute_id": "cpu_quantity", "condition": "entails", "predicate": {"gte": "2"}},
      {"attribute_id": "memory_capacity", "value_basis": "installed", "aggregation_scope": "system_total", "condition": "entails", "predicate": {"gte": "128", "unit": "GB"}}
    ]
  },
  "limit": 20
}
```

여기서 `entails`는 공고 조건을 만족하는 모든 구성이 질의 조건도 만족한다는 뜻이다.
RAM ≥ 256GB와 RAM = 128GB는 RAM ≥ 128GB 질의를 만족하지만, RAM ≥ 64GB는
그 자체로 만족하지 않는다. 단순히 저장된 숫자 128과 비교하는 검색으로 구현하지 않는다.
일부 구성만 겹치는 `overlaps`와 특정 제품 구성을 대입하는 `evaluate`는 별도 연산이다.

정량 조건은 후보 축소와 최종 평가에 모두 적용한다. vector similarity가 필수 수치
조건이나 품목 범위 조건을 무효화하지 않는다. 미매핑 조건의 원문 검색은 허용하되
정확한 속성 검색 결과와 구분하고 필터 완전성을 반환한다.
`search_requirements`의 정확 검색에는 필수조건을 SQL로 먼저 적용해 vector Top-K가
충족 결과를 잘라내지 않게 한다. 유사 검색은 제한된 후보를 평가하므로 후보 수와
검색 누락 가능성을 표시하고 전수 검색으로 표현하지 않는다.

결과는 notice revision, line item, snapshot ID, matched requirement IDs,
원문 인용·위치, 검토·coverage 상태, artifact version과 후보 검색 제한을 포함한다.
Top-K 검색 결과의 `total`을 전체 충족 공고 수로 표시하지 않는다. 전체 집계는
별도 exact count 쿼리로 수행한다. pagination cursor는 질의·권한·snapshot 기준을 고정한다.

## 11 규격 비교와 제품 평가

규격 비교는 category·component 역할·attribute 의미·scope·value basis·단위를
맞춘 뒤 실행한다. 서로 다른 구성요소를 이름 유사성만으로 정렬하지 않는다.
품목·구성요소 정렬도 후보와 근거, 미확정 상태를 보존한다.

수치가 큰지보다 허용되는 구성의 집합이 어떻게 달라졌는지 비교한다.

| 비교 | 결과 |
|---|---|
| RAM ≥ 64GB → RAM ≥ 128GB | 새 조건이 기존 허용 집합의 부분집합이므로 강화 |
| 높이 ≤ 4U → 높이 ≤ 2U | 상한 감소에 의한 강화 |
| 용량 ≥ 128GB → 용량 ≤ 256GB | 단순 강화·완화 관계가 아니므로 조건 변경 |
| 서로 다른 CPU 모델의 동등 이상 | 승인된 근거 없이는 비교 보류 |
| 기존 조건을 새 추출에서 찾지 못함 | 새 문서 coverage 확인 전 삭제 확정 금지 |

내부 결과는 `equivalent`, `tightened`, `relaxed`, `added`, `removed`, `changed`,
`incomparable`, `review_required`다. OR·조건부 식의 포함관계를 지원하지 못하면
leaf 차이를 보여주되 그룹 전체 강화·완화를 확정하지 않는다.

제품 평가는 모델 계열의 최대 지원 사양이 아닌 **특정 제품 구성 버전**을 대입한다.
제품 관찰에는 주장 주체, 증빙, 관찰·검증 시각과 유효기간을 기록한다. 판매자 주장과
제조사 사양이 충돌하면 둘을 보존하고 authority policy 없이 한쪽을 채택하지 않는다.
판정에 필요한 제품 정보가 없거나 결과에 영향을 주는 미지원 비교·미해결 조건이
있으면 unknown이다. 이미 만족이 확인된 OR의 다른 선택지가 불명이라는 이유만으로
그 그룹의 충족 근거를 무효화하지 않는다.

| 필수조건식 평가 | 전체 기술조건 결과 |
|---|---|
| 적용되는 필수조건식의 root가 근거 있게 미충족 | `not_satisfied` |
| root가 미확인 또는 coverage 결손으로 전체 충족을 확정할 수 없음 | `unknown` |
| root 충족, 승인된 입력·완전한 대상 범위·판정에 영향을 주는 충돌 없음 | `satisfied` |
| 명시적으로 평가 범위 밖임이 확인됨 | `not_applicable` |

원문 필수 여부가 unknown이면 이를 권장조건으로 낮추지 않는다. 선택조건은 별도
평가하고 가중 점수로 필수조건 실패를 상쇄하지 않는다. 아래 순서로 그룹을 평가한다.
`not_applicable`인 자식은 적용 대상 집합에서 제외하되 제외 근거를 보존한다.

| 그룹 | 적용되는 자식의 상태 | 그룹 결과 |
|---|---|---|
| `all` | 하나 이상 `not_satisfied` | `not_satisfied` |
| `all` | 미충족은 없고 하나 이상 `unknown` | `unknown` |
| `all` | 하나 이상 적용되며 모두 `satisfied` | `satisfied` |
| `any` | 하나 이상 `satisfied` | `satisfied` |
| `any` | 충족은 없고 하나 이상 `unknown` | `unknown` |
| `any` | 하나 이상 적용되며 모두 `not_satisfied` | `not_satisfied` |
| 두 그룹 | 모든 자식이 근거 있게 적용 제외 | `not_applicable` |

원래 child가 없는 식은 validation 실패이며 제외 집합과 구분한다. `not`, `implies`,
`at_least`는 MVP에서 항상 미지원으로 반환하며 자식을 펼쳐 임의 평가하지 않는다.
후속 evaluator가 지원할 때 별도 version으로 진리표와 적용 범위를 게시한다.
필수 leaf가 없는 문서는 공집합 논리로 만족 처리하지 않고 평가 범위를 검토한다.

결과에는 `technical_requirements_only` 범위, 평가 기준 시각, 필수조건 수,
충족·미충족·미확인 수, coverage와 증빙을 표시한다. ‘입찰 가능’, ‘참가자격 충족’,
‘실제 납품 모델 확인’으로 확대하지 않는다. 실제 납품·검수는 독립 증거가 있을 때만 연결한다.

## 12 검색 통계와 조달 관계 연결

품목 수, 품목별 공고 수, 고유 공고 수와 계약 수를 분리한다. 한 공고의 여러 품목이
같은 분석군에 들어오면 공고 수는 한 번만 센다. 재공고·변경·취소·최신 차수 정책과
수집 기간·시점은 모든 결과에 함께 반환한다.

수량×단가와 총액은 원문 금액과 계산값을 나눠 검증한다. 공고 예산·품목 금액·낙찰
금액·계약 가족 유효금액은 다른 값이다. 총액계약의 공고·계약 금액을 구성 품목마다
전액 복제하거나 근거 없는 비율로 배분하지 않는다.

업체 연결은 기존 공고·참여·낙찰·계약 식별자와 집계 정책을 따른다. ‘해당 규격 공고에
참여한 업체’와 ‘해당 사양 제품을 공급할 수 있는 업체’를 별도 관계로 반환한다.
참여 수집의 표본 제한·최종낙찰 보존 정책 등 기존 데이터 coverage도 함께 표시한다.

추세 분석은 같은 의미 version·scope의 비교 가능한 조건만 사용한다. 문서 미확보와
미매핑을 요구조건 부재로 세지 않는다. 연도별 대상 공고·문서 확보·추출·검토·속성
관측 수를 함께 반환하고, 사전 변경으로 관측률이 달라진 경우 재처리 cohort를 분리한다.
원문 snapshot의 과거 해석과 최신 사전으로 재해석한 분석을 섞지 않는다.

## 13 API와 업무 Action

아래 Capability ID와 입력은 제안이다. 기존 Runtime의 인증·OPA·artifact 계약을
사용하며 공개 전에 Domain Registry와 입출력 계약을 추가한다.

| Capability | 주요 입력 | 반환 |
|---|---|---|
| `search_tender_specifications` | 검증한 DSL, 기간·상태·권한 | 품목·요구조건·근거와 pagination |
| `get_tender_specification` | snapshot ID 또는 공고·품목·시점 | 문서·구성·조건식·검토 상태 |
| `compare_tender_specifications` | 두 snapshot ID, alignment 정책 | 조건 차이와 비교 불가 사유 |
| `find_similar_specifications` | snapshot ID, 범위·필수조건 | 유사 후보와 필수조건 검사 결과 |
| `analyze_specification_trends` | 속성·기간·cohort 정책 | 분포와 단계별 coverage |
| `evaluate_product_configuration` | 제품 구성·snapshot ID | 버전 고정된 기술조건 평가 |

업무 Action은 별도로 `request_specification_processing`, `submit_specification_review`,
`propose_attribute_definition`, `publish_specification_snapshot`,
`register_product_configuration`, `record_compliance_assessment`를 제안한다.
정의된 것만 노출하고 API body의 actor·reviewer를 권위 정보로 사용하지 않는다.

Action은 인증 principal, 조직 범위, OPA action·resource, idempotency key, 입력 hash,
expected revision과 감사 이력을 갖는다. 같은 key에 다른 payload를 보내면 충돌로
거부한다. 동일 revision의 중복 승인과 stale review는 transaction에서 차단한다.
검색·계산의 실행과 결과 저장 Action을 분리하되 입력 snapshot은 동일하게 고정한다.

Prefect 요청 같은 외부 실행은 DB transaction과 원자적이지 않다. Workspace에
실행 요청을 먼저 영속화하고 재시도 시 correlation key로 기존 실행을 확인한다.
접수·외부 실행 요청·결과 확보·실패를 분리해 timeout을 성공이나 미실행으로 단정하지 않는다.

비공개 제품 구성과 업로드는 organization ID가 모든 참조·캐시·객체 URI에 적용된다.
문서 원본 다운로드는 서버가 권한을 확인한 뒤 만료되는 접근 수단으로 제공한다.
MCP는 동일 Runtime 계약만 호출하고 파일·DB·Provider credential을 직접 갖지 않는다.

## 14 버전과 재현성

평가와 검색 설명에는 다음 참조를 고정한다.

```text
notice_revision_ref
document_version_ids + file_hashes
parse_run_ids + parser_versions
extraction_run_ids + model_prompt_schema_versions
attribute_dictionary_release + ontology_stable_concepts
specification_snapshot_id + review_revision
product_configuration_version + evidence_versions
comparison_profile_version + evaluator_version
runtime_artifact_version + checksum
as_of + observation_cutoff + authorization_scope
```

문서 변경과 해석 변경은 다른 lineage다. 원본이 같고 모델·사전만 바뀐 재추출은
원문 변경으로 표시하지 않는다. 새 결과를 기존 승인 결과와 자동 교체하지 않는다.
검색 projection은 원천 snapshot과 release ID가 일치할 때만 활성화한다.

게시 의미 artifact에는 속성 정의·alias·component·단위·비교 프로파일을 고정한다.
기존 artifact compiler와 manifest의 확장으로 배포하며 별도의 비검증 YAML 적재
경로를 만들지 않는다. Pipeline은 이 게시 JSON 계약을 읽고 Platform Python을 import하지
않는다. 두 소비자의 schema·checksum 호환성은 프로젝트 간 계약 검사로 검증한다.

## 15 실행 안정성과 배포

Prefect Flow는 manifest 확보와 후보 선별, 다운로드, 파싱, 문서 적합성 판정,
품목 후보 식별, 구성요소 후보 식별, 요구조건 추출, 귀속·통합, 속성 매핑,
요구조건 검증과 결과 적재를
조정하며 주요 단계는 Task로 드러낸다. 모듈을 순서대로 호출하는 책임은 Flow에 두고,
개별 모듈을 전체 Flow 없이도 사용할 수 있게 한다. Task 결과에는 문서·실행 ID와
상태를 남긴다. 같은 입력·
실행 설정에 대한 retry는 중복 관찰을 만들지 않도록 idempotency key를 사용한다.
의도적인 재실험은 별도 run ID를 가진다. 원본 보존·정규 적재 성공 후에만 checkpoint를
전진시키고 실패 문서의 복구 큐를 별도로 유지한다.

외부 HTTP·DB는 native async, 파싱 같은 동기 CPU 작업은 별도 Prefect Task·Job으로
격리한다. 다운로드·parser·LLM·DB의 동시 실행 상한을 각각 정하고 같은 transaction의
순서는 유지한다. 모델별 timeout·retry·rate limit과 비용 상한을 설정한다.

K3s 제안 배치는 다음과 같다. 기존 단일 노드 배포에서 추가할 사항이지 현재 적용
설정은 아니다.

| CPU 노드 | GPU 노드 또는 별도 작업 노드 |
|---|---|
| Control Plane, API·UI·Ingress | 파싱·OCR·배치 IE·임베딩 Job |
| PostgreSQL·Redis, Prefect Server | 로컬 추론 엔진과 작업 캐시 |
| MLflow 선택 사용, Object Storage | GPU를 요구하는 Job만 GPU resource 요청 |

GPU가 필요 없는 parser Job에는 GPU를 예약하지 않는다. 상시 API와 배치 작업은
node label·affinity·resource 예산으로 분리한다. 스토리지·DB 쓰기 경합을 측정하고
문서 동시 처리량을 제한한다. 노드 두 대가 Control Plane HA나 데이터 복제를 뜻하지 않는다.

초기에는 Object Storage가 원본·파생 파일을 보관하고 DB는 URI·hash·권한을 보관한다.
로컬 파일 저장도 같은 reference 계약을 구현할 수 있지만 노드 이동·복구 제약을
명시한다. backup은 DB와 객체 manifest의 복구 시점을 연결하고 실제 restore로 검증한다.
MLflow 사용 여부와 관계없이 실행 provenance의 필수 필드는 도메인 DB에 남긴다.

## 16 구현 위치

현재 코드 배치는 단일 백엔드의 기능 소유권을 따른다. 아래 기능에서 실제 구현을 추가하며
후속 조회·비교를 위해 빈 패키지나 별도 프로젝트를 먼저 만들지 않는다.

```text
backend/src/teoria/features/specification_processing/
  flows.py, tasks.py, parsing/, extraction/, normalization/, storage/
backend/src/teoria/features/goods_normalization/
  candidates/, profiles/, contracts/
backend/src/teoria/features/semantic_modeling/
  ontology/, binding/, authoring/, registry/
backend/tests/features/specification_processing/
backend/tests/features/goods_normalization/
backend/migrations/data/<next>_specification_observations.sql
backend/migrations/application/<next>_goods_authoring.sql
backend/contracts/runtime/domains/<domain>/
tests/integration/<feature_contract_case>.py
```

파일은 책임이 생길 때 추가하고 공통 `utils`나 `shared`를 만들지 않는다. 위 이름은
배치 예시이며 구현 시 같은 책임을 기존 기능에 합칠 수 있는지 확인한다. Provider
wire 처리는 기존 provider_api 라이브러리를 사용하고 Source·Connector 계약을
변경할 때는 각각의 작성 절차와 검증을 수행한다.

## 17 평가와 단계별 완료 조건

사람이 만드는 gold set에는 문서 전체의 품목 범위·필수조건·값·단위·scope·논리·근거를
포함한다. 같은 문서의 변경본이나 유사 템플릿이 train/dev/test에 걸쳐 들어가지 않도록
기관·문서 계열 단위로 분리한다. 먼저 100~300개 문서를 확보하는 것을 가설로 두되
형식·기관·실패 유형의 다양성에 따라 조정한다.

| 단계 | 결과 | 다음 단계로 진행할 조건 |
|---|---|---|
| 0 설계와 평가 준비 | 원본 corpus, gold, 형식별 parser 비교, 권한·저장 계약 | 확보·파싱 실패를 포함한 coverage 파악, 보류 정책과 새 범위 정리 |
| 1 서버 검색과 비교 | 후보 추출, 검토 화면, 게시 사전, accepted snapshot, 검색·차이 | 다품목·단위·scope·근거 평가, 미지원 조건의 unknown 처리 |
| 2 두 번째 품목 검증과 재처리 | 구성요소·속성 제안, 타입 추가 없는 사전 확장, 재처리. 품목은 미정 | 물품에 독립적인 처리 계약과 두 번째 품목의 비교 실행 |
| 3 제품 구성 기술평가 | 조직별 제품 버전, 증빙, 조건별 판정, 평가 이력 | 필수조건 누락·범위 불명·문서 불완전 시 satisfied 차단 검증 |
| 4 추세와 조달 관계 | cohort 분석, 참여·낙찰·계약 연결 | 수집 편향·버전·사건 키·금액 배분·관측 범위를 보존한 재현 |

평가 지표는 parser 성공률 외에 품목 배정, 필수조건 recall, 수치·단위·scope·논리
정확도, 근거 추적률, 미지 속성 발견 정밀도, 검색 precision/recall, 비교 오류율,
false satisfied, unknown 비율, 검토 시간과 처리 비용을 포함한다. LLM 자체 평가를
정답으로 사용하지 않고 실패 사례를 사람이 판정한다.

다음 수치는 계획상 수용 목표이며 실측이나 운영 품질 보장이 아니다. 단계1의 고정된
test set에서 필수조건 recall 95% 이상, 품목 배정 정확도 98% 이상, 지원하는 수치·단위·
scope의 엄격한 일치 정확도 98% 이상, 근거 참조 무결성 100%를 가설로 둔다. 미지원·
모호한 조건도 recall 분모에 포함하고 수치 정확도의 지원 범위와 coverage를 병기한다.
단계3은 사람이 판정한 평가 세트에서 false satisfied 0건을 gate로 삼고 사례 수·분모·
불확실성을 보고한다. 0건은 새로운 문서에서의 오판정이 없다는 뜻이 아니다.

공통 조건과 다른 품목의 혼선, NIC 수와 port 수, CPU당과 전체, GB와 GiB, base와 boost,
정격 출력과 소비전력, AND/OR, 별첨 누락, 문서 변경, 원문에 없는 조건 생성,
미지 속성, 조직 간 접근, stale review를 필수 회귀 사례에 포함한다.

프로젝트별 단위·DB 통합·프로젝트 간 계약 검증을 수행한다. Data DB·App DB migration,
Flow, Source, Connector, MCP·Compose를 변경하는 단계에서는 AGENTS.md의 해당 필수
검증을 실행한다. 설계 문서만 변경할 때는 링크·목차·자동 생성 문서의 일치를 검증한다.

## 18 구현 시작 시 확정할 판단

이 제안은 초기 품목을 서버, 기본 검색 대상을 accepted snapshot, 의미 계약을 게시
artifact, 사용자 업무 상태를 별도 논리 Workspace DB, 첫 evaluator를 제한된 결정적
비교로 정한다. 다음 비교·운영 프로파일은 실제 시험으로 확정한다.

| 판단 | 확정에 필요한 근거 |
|---|---|
| HWP·HWPX adapter와 OCR fallback | 실제 표·병합 셀·위치 추적 평가, 실행·배포 조건 |
| 서버 초기 사전 | gold 문서의 후보와 의미 충돌·적용 범위 검토 |
| 동등 이상 비교 | 제조사 증빙·시험 조건과 승인된 비교 프로파일 |
| 단위와 enum 비교 | GB/GiB, interface, DDR, CPU scope의 명시 규칙 |
| 외부 모델 전송 | 문서 구분, 조직 설정, 이용 조건, 로그·보존 정책 |
| 처리량과 저장 비용 | 문서 크기·페이지·형식 구성·도착량, 모델 지연 측정 |

단계0 결과와 단계1 구현 차이를 확인한 뒤 기능을 활성화한다. 현재 기본 배포에
새 서비스를 먼저 추가하거나 기존 archive를 자동 복원하지 않는다.

## 19 사용자 화면과 검토 흐름

초기 화면은 별도 범용 Ontology 편집기 대신 다음 작업에 집중한다. React UI와
일반 사용자용 API는 기존 인증·권한 경계를 사용하고 의미 게시 같은 관리자 작업만
Admin 권한으로 분리한다.

| 화면 | 사용자가 확인하고 결정하는 내용 |
|---|---|
| 규격 검색 | 자연어를 해석한 조건, 품목·기간, 검토된 결과와 추출 초안의 구분 |
| 공고 품목 상세 | 공고 공통 조건, 품목별 규격, 구성요소, 미해결 조건과 변경 차수 |
| 근거 검토 | 왼쪽 원문 위치와 오른쪽 추출 조건을 대조하고 품목·값·범위·논리를 수정 |
| 규격 비교 | 같은 의미·범위의 조건을 정렬하고 추가·삭제·강화·완화·비교 불가를 표시 |
| 속성 검토 | 기존 속성과의 차이, 후보 alias, 적용 범위, 예시·반례를 보고 승인 |
| 제품 구성과 평가 | 실제 장착값과 최대 지원값을 구분하고 조건별 증빙·판정·미확인을 표시 |

검색 결과마다 문서 전체 coverage와 매칭 조건의 확실성을 분리해 보여준다.
초안 결과를 선택해 검토할 수 있지만 초안이라는 이유를 숨긴 확정 배지를 주지 않는다.
근거를 선택하면 해당 문단·표·셀로 이동하며 파싱 실패 영역도 원문에서 확인할 수 있다.

검토는 문서 범위 확인, 품목 연결, 조건·논리 수정, 속성 매핑 확인, snapshot 승인
순서다. 의미 사전에 없는 속성은 미매핑 상태로 보존하면서 별도의 속성 제안을 만든다.
사전 승인과 문서 해석 승인을 한 버튼으로 묶지 않는다. 기존 사전·문서가 바뀐 경우
무엇이 오래됐는지 표시하고 재처리·재검토 대상만 선택할 수 있게 한다.
