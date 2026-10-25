# Teoria product roadmap

현재 제품 범위는 규격서의 물품·구성품·요구조건 추출과 물품 Ontology를 통한 AI 활용이다.
기존 기업·공고·계약·낙찰 분석과 조달 API 수집은 비활성 보관했다.
법령 수집·조회와 AI 메타데이터 진단의 법령 근거 연결은 별도 활성 기능이다.

## 유지하는 기반

- Pipelines: 규격서 파싱·정보 추출·표준 후보 관리·고정 표준 적용과 평가 CLI
- Prefect: 명시 입력의 두 Flow와 OpenMetadata 동기화
- 저장: 산출물 본문은 파일/S3, 실행·문서별 상태와 참조는 Data DB
- Platform: Ontology 작성·검토·게시, Stable Concept와 Semantic Binding
- 실행: Source·Mapping·Capability, Context 주입, immutable Runtime artifact, OPA와 MCP
- OpenMetadata: 기술·거버넌스 metadata의 authoritative source
- 물품 Ontology 초기 Draft blueprint: `platform/ontology_blueprints/goods.yaml`

현재 활성 Registry에는 기존 업무 Capability가 없다. 물품 실행 기능의 연결을 완료한 상태로 간주하지 않는다.

## 다음 결과

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
의미 판정의 독립 정확도 평가, 실제 goods 게시와 물품 Runtime 조회 연결은 후속 범위다.

Platform이 저장된 추출 산출물의 checksum과 원문 근거를 확인해 기존 개념 연결 또는 신규 개념을
Suggestion으로 제안한다. Pipeline이 Platform Runtime을 직접 호출하지 않는다.
새 의미는 사람의 검토·승인을 거쳐 새 Draft에서 게시한다.
OpenMetadata 연결은 entity 본문 복제 없이 MetadataTargetRef를 사용한다.

### 3. 물품 검색·비교 Capability

대표 물품군의 데이터 materialization과 read-only Source·Mapping을 구현한다.
조건 검색·규격 비교 결과에 문서 근거, 표준 버전과 Ontology artifact를 제공한다.
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
