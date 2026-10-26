# Teoria product roadmap

현재 제품 범위는 규격서의 물품·구성품·요구조건 추출과 물품 Ontology를 통한 AI 활용이다.
기존 기업·공고·계약·낙찰 분석과 조달 API 수집은 비활성 보관했다.
법령 수집·조회와 AI 메타데이터 진단의 법령 근거 연결은 별도 활성 기능이다.

## 코드와 배포 구조

Python 코드는 `backend/src/teoria/`의 기능별 모듈, 관리 UI는 `frontend/`로 통합했다.
의존성은 `backend/pyproject.toml`과 `backend/uv.lock`에서 관리하며 Worker별 이미지와 권한은 유지한다.
폴더 통합은 기존 서비스의 운영 이미지 교체나 물품 Runtime 기능 완성을 의미하지 않는다.
[구조와 소유권](architecture/repository-structure.md)을 따른다.
FastAPI 앱·라우터·서비스/저장소와 HTTP client lifespan을 정리하고 기능 간 의존성 검사를 추가했다.
[검증과 운영 반영](verification/backend_cleanup_2026_10_26.md)을 확인한다.

## 유지하는 기반

- Pipelines: 규격서 파싱·정보 추출·표준 후보 관리·고정 표준 적용과 평가 CLI
- Prefect: 명시 입력의 두 Flow와 OpenMetadata 동기화
- 저장: 산출물 본문은 파일/S3, 실행·문서별 상태와 참조는 Data DB
- Platform: Ontology 작성·검토·게시, Stable Concept와 Semantic Binding
- 실행: Source·Mapping·Capability, Context 주입, immutable Runtime artifact, OPA와 MCP
- OpenMetadata: 기술·거버넌스 metadata의 authoritative source
- 서버 Ontology 작성 입력: `backend/authoring/ontology_blueprints/computer_server.yaml`
- 서버 프로파일 작성 입력: `backend/authoring/normalization_profiles/computer_server_memory.yaml`

작성 Registry에는 서버 검색·비교·원문 근거 조회와 내부 요구조건 조회를 추가했다.
고정 프로파일 관찰의 Data DB 적재부터 OPA·불변 bundle을 통한 Runtime HTTP까지 격리 환경에서
검증한다. 운영은 기존 bundle을 유지하며 새 의미 게시와 전환은 아직 수행하지 않았다.
[서버 Capability](procurement_specification_processing/server_capabilities.md)를 따른다.

과거 조달 운영 데이터와 미사용 goods Draft·실험 산출물은 [정리했다](verification/retired_data_cleanup_2026_10_26.md).
법령·게시 Ontology·승인 이력과 현재 bundle은 유지한다. 새 서버 문서의 추출·검토·게시부터 재개한다.

## 우선 실행 순서

구조 정리와 임시 검토 보고서 확장보다, 대표 물품군 하나의 추출 결과가 실제 조회까지
이어지는 경로를 우선 완성한다. 아래 순서는 구현 우선순위이며 각 항목의 완료를 뜻하지 않는다.

| 순서 | 작업 | 완료 기준 |
|---|---|---|
| 1 | 회귀 테스트 독립화 | 보관 Registry 경로 의존을 없애고 필요한 최소 계약을 테스트 fixture로 유지한다. 은퇴 기능만 검증하는 테스트를 정리하고 전체 검사를 정상화한다. |
| 2 | 추출·의미 매핑 품질 측정 | 사람이 확인한 원문 사례로 엔티티 누락·관계·속성 귀속·단위·개념 연결을 나눠 측정한다. 시간 초과와 비용은 의미 정확도와 구분한다. |
| 3 | 대표 물품 Ontology 게시·관찰 데이터 연결 | 컴퓨터 서버를 첫 대상으로, 검토·승인된 개념과 프로파일로 정규화한 관찰을 조회용 Data DB에 적재하고 read-only Source·Mapping을 연결한다. |
| 4 | 첫 물품 Capability | 조건 검색·두 규격서 요구조건 비교·원문 근거 조회를 구현하고 실제 요청에서 근거와 적용 버전을 반환한다. |
| 5 | 게시 전 변경 영향 확인 | 개념·프로파일 변경의 영향 문서·매핑·재처리 범위와 이전 버전 대비 결과 차이를 확인한다. |

1번은 합성 API·DB fixture로 회귀 검사를 독립화하고 은퇴 기능 전용 검사를 정리했다.
3·4번은 서버·메모리 의미 작성 입력, 승인 프로파일 적용, 조회용 관찰 적재와 Capability를
구현하여 격리 환경에서 검증한다. 운영 게시·배포와 2번의 독립 모델 정확도 평가는 남아 있다.
[구현과 검증 기록](verification/server_capabilities_2026_10_26.md)을 확인한다.

3·4번은 컴퓨터 서버 한 물품군의 데이터 적재부터 조회까지 하나의 경로로 검증한다.
Ontology에는 지속 가능한 물품·구성·속성의 의미를 두고, 개별 규격서의 값·연산·조건은
원문 근거와 버전이 있는 관찰 데이터로 관리한다. 실행 상태·파일 URI 저장만으로 검색 데이터
적재를 완료했다고 표시하지 않는다. Pipeline은 Platform Runtime을 직접 호출하지 않는다.

첫 검색 질문은 “메모리 64GB 이상을 요구하는 서버 규격서”다. 실제 납품 요구와 최대 지원 용량,
기보유 사양을 구분하고 모듈당·시스템 전체 범위 및 GB·GiB의 차이를 보존해야 한다.
응답에는 값·단위·연산·적용 범위·원문 근거·프로파일과 Ontology 버전을 함께 제공한다.
그다음 두 규격서의 같은 범위·같은 의미에 연결된 요구조건을 비교한다.

## 현재 구현과 남은 결과

### 1. 물품 Ontology 검토

규격서·물품 항목·구성 관계·요구조건의 identity와 의미를 실제 문서로 검증한다.
문서별 관찰과 추출 표준 draft를 Published Ontology 개념과 구분한다.
원문 근거 없는 BOM·동일 물품 병합·속성 귀속을 만들지 않는다.

### 2. 추출 결과와 Ontology 연결

Published 개념을 참조하는 물품 정규화 프로파일의 Draft·검토·승인·불변 패키지 내보내기와
Pipeline의 엔티티·관계·요구조건 적용 경로를 구현했다.
[프로파일 계약](procurement_specification_processing/normalization_profiles.md)을 따른다.
미해결 후보의 문맥별 묶기·문서 중복 제거와 기존 개념의 문자열 검색·문맥 필터,
선택한 제안의 새 프로파일 Draft 생성과 입력 checksum 감사 기록도 구현했다.
Codex 의미 판정·신규 개념 초안 작성·프로파일 연결과 평가용 자동 승인 cycle을 추가했다.
상위 Prefect Flow와 작성 operation 체크포인트·실행 lease를 연결하여 전달·승인 대기·재시도를 자동화했다.
의미 판정의 독립 정확도 평가와 운영 goods 게시·bundle 전환은 후속 범위다. 서버 관찰의 Runtime 조회 경로는 격리 검증을 추가했다.

Platform이 저장된 추출 산출물의 checksum과 원문 근거를 확인해 기존 개념 연결 또는 신규 개념을
Suggestion으로 제안한다. Pipeline이 Platform Runtime을 직접 호출하지 않는다.
새 의미는 사람의 검토·승인을 거쳐 새 Draft에서 게시한다.
OpenMetadata 연결은 entity 본문 복제 없이 MetadataTargetRef를 사용한다.

### 3. 물품 검색·비교 Capability

서버 관찰 materialization과 read-only Source·Mapping, 검색·비교·근거 조회를 구현했다.
문서 근거·프로파일·Ontology·Runtime artifact 버전을 반환하며 적용 범위·단위·역할을 구분한다.
검증된 질문 handler만 Context에 등록하고 범용 AI planner의 완료로 표시하지 않는다.

### 4. 전용 실행의 확장 검증

Compose의 migration·Worker·모델 인증·합성 추론·새 bundle 배포는 완료했다.
실제 문서의 전체 추출·표준 저장·실패 재개와 K3s 실행은 별도 검증 대상으로 남긴다.
[운영 배포 결과](verification/goods_focus_deployment_2026_10_25.md)를 따른다.
기존 데이터의 폐기·WAL·디스크 회수는 별도 결정이며 이 변경에 포함하지 않는다.

### 5. 독립 품질 평가

원문 수치의 단위 보존과 최종 귀속 후 동일 관찰 병합을 구현했다. 고정 사례 회귀 검증과
실제 모델의 신규 문서 품질 평가는 구분하며, 전체 재현율·관계 정확도는 별도 평가 대상으로 남긴다.
평가 중 Parser 구현·의존성 변경을 감지해 무효 비교를 중단한다. 개발 설치와 분리된 실행 환경에서
유효한 신규 문서 비교를 완료하는 작업이 남아 있다.

추출 누락·계층·속성 귀속과 물품 비교 결과를 원문 기반 사례로 평가한다.
AI 검토 결과를 사람 정답이나 독립 정확도 측정으로 사용하지 않는다.
현재 절차는 [규격서 평가](procurement_specification_processing/index.md)를 따른다.

계약·운영 입력·작성 자료·Prefect 배포 선언의 현재 위치는
[저장소 구조](architecture/repository-structure.md)를 따른다. Python 기능 모듈과 역할별 실행 프로세스는 유지한다.
