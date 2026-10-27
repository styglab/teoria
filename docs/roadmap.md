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
- 물품 Ontology 작성 입력: `backend/authoring/ontology_blueprints/goods.yaml`; 서버·메모리 등은 유형 사전 항목으로 작성·검토
- 프로파일 작성: 새 Draft의 의미·값 계약을 검토한 뒤 작성; 기존 서버 프로파일은 삭제

사용자의 초기화 요청으로 기존 물품 모델·후보·프로파일·Binding·서버 전용 조회 및 관찰을 운영에서 삭제했다.
현재 `goods` 1.0.0 Draft에는 규격서 버전·규격 물품 항목·속성 명세·구성 명세·기타 요구 명세·원문 근거를 작성했다.
분류체계·분류항목·분류 판정·물품 유형·표준 특성·서비스 항목을 추가했다.
납품 범위·공급 역할·적용 문맥·납품자료·물품 연계 명세와 네 샘플 대표 그래프를 추가했다.
객체 17개·속성 93개·관계 50개이며 구조 검증을 통과했다. 운영 bundle `2026.10.27.3`에는 물품 Capability가 없다.
원본 규격서, 법령·OpenMetadata·물품 외 Ontology와 데이터는 유지했다.
[초기화와 재작성 기록](verification/specification_goods_reset_2026_10_27.md)을 따른다.

## 우선 실행 순서

발전 목표는 규격서의 물품·구성품·속성·조건·관계와 근거를 일관되게 표현하는 운영 Ontology다.
[규격서 물품 모델 설계안](architecture/specification_goods_model.md)을 후속 검토 기준으로 사용한다.
검색·표준화·검토·문서 변경 확인·비교와 AI 질의는 이 모델의 활용이다.
현재 namespace 이관과 서버·메모리 조회 경로를 전체 모델의 완성으로 표시하지 않는다.
다음 검증은 대상의 정체성, 문서 계층과 구성의 구분, 다양한 속성값·관계 문맥, 복수·상충 근거와 검토·재처리다.

대표 규격서에서 대상·구성·속성·관계·근거를 탐색할 수 있는 경로를 우선 완성한다.
아래 순서는 구현 우선순위이며 각 항목의 완료를 뜻하지 않는다.

| 순서 | 작업 | 완료 기준 |
|---|---|---|
| 1 | 회귀 테스트 독립화 | 보관 Registry 경로 의존을 없애고 필요한 최소 계약을 테스트 fixture로 유지한다. 은퇴 기능만 검증하는 테스트를 정리하고 전체 검사를 정상화한다. |
| 2 | 규격서 물품 모델·의미 매핑 검증 | 원문에서 대상·구성·속성·관계·조건·근거를 구분하고 ID·역할·범위·문서 버전·매핑 이력을 검증한다. 누락·귀속·단위·개념 연결은 각각 측정한다. |
| 3 | 의미 사전·문서 명세·근거 연결 | 검토·승인된 개념과 프로파일로 문서별 대상·구성·속성 명세를 정규화하고 read-only Source·Mapping으로 근거와 함께 연결한다. |
| 4 | 물품 구조 탐색과 활용 Capability | 물품 전체 구성·대상별 속성·관계와 원문 근거를 탐색한다. 검색·변경 확인·비교는 각각 이 모델을 사용하는 기능으로 검증한다. |
| 5 | 게시 전 변경 영향 확인 | 개념·프로파일 변경의 영향 문서·매핑·재처리 범위와 이전 버전 대비 결과 차이를 확인한다. |

1번은 합성 API·DB fixture로 회귀 검사를 독립화하고 은퇴 기능 전용 검사를 정리했다.
기존 서버·메모리 전용 구현은 초기화로 제거했다. 현재 3·4번은 새 모델의 검토 후 구현할 범위다.
문서별 명세와 원문 근거를 함께 탐색하는 경로를 먼저 만들며, 실행 상태·파일 URI 저장만으로
물품 그래프 조회가 완성됐다고 표시하지 않는다. Pipeline은 Runtime을 직접 호출하지 않는다.

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
기존 프로파일 소비 계약을 새 명세 모델에 그대로 적용하지 않는다. 새 모델의 실제 원문 검증·게시·명세 계약·프로파일 작성은 후속 범위다.

Platform이 저장된 추출 산출물의 checksum과 원문 근거를 확인해 기존 개념 연결 또는 신규 개념을
Suggestion으로 제안한다. Pipeline이 Platform Runtime을 직접 호출하지 않는다.
새 의미는 사람의 검토·승인을 거쳐 새 Draft에서 게시한다.
OpenMetadata 연결은 entity 본문 복제 없이 MetadataTargetRef를 사용한다.

### 3. 물품 검색·비교 Capability

기존 서버 관찰 materialization·Source·Mapping·검색·비교·근거 조회는 제거했다.
새 규격서 물품 모델의 대상·구성·속성·조건·근거를 연결한 뒤 구조 탐색과 활용 기능을 작성한다.
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


## 선택형 모델 운영 검증

- 합성 고객 Data DB 테이블과 명시적인 Prefect 데이터 준비·학습·고정 버전 배포 Flow.
- 기존 메타데이터 동기화에 샘플 스키마를 포함하고 AI 진단은 별도 검토 초안으로 유지.
- MLflow 실험·모델 버전, MinIO 산출물, 전용 추론 프로세스와 관리 화면을 연결하는 Compose 예제.
- 모델 운영은 이름 있는 `model_operations` 기능이며 Teoria의 Metadata·Ontology 권위 경계를 유지.
- 후속: K3s 전용 배포 어댑터, 일반 모델 승인 정책·모델별 격리 권한, 확장·운영 모니터링.
  현재 예제의 모델 배포는 정해진 합성 고객 모델에 한정하며 범용 무중단 서빙으로 간주하지 않는다.


관리 화면은 데이터·의미, 거버넌스, 모델 운영, 워크플로와 하단 플랫폼 관리로 구분한다.
모델 레지스트리와 추론 서비스를 독립 화면으로 제공하며 선택 기능의 활성화 상태에 맞춰
탐색 메뉴와 플랫폼 현황의 바로가기를 표시한다.
