# Teoria

데이터 자산과 업무 의미를 연결하는 **AI-Native Metadata & Ontology Platform**이다.
공공조달 물품은 첫 업무 영역이고, **FormatID**는 규격서를 구조화하는 업무 앱이다.

## 구조

| 구분 | 하는 일 | 코드 위치 |
|---|---|---|
| 데이터 | 수집·처리 기반·메타데이터 관리 | `backend/src/teoria/platform/data/` |
| Ontology | 업무 의미 작성·게시·연결·Runtime | `backend/src/teoria/platform/ontology/` |
| AI (예정) | 향후 AIP 예약 폴더; 실행 기능 미구현 | `backend/src/teoria/platform/ai/` |
| MLOps | 공통 모델 목록·버전·운영 API | `backend/src/teoria/platform/mlops/` |
| 도메인 | 물품·법령의 업무 규칙과 처리 | `backend/src/teoria/domains/` |
| 앱 | 플랫폼과 도메인을 이용하는 사용자 업무 | `backend/src/teoria/apps/formatid/` |
| 예제 | 합성 고객 이탈 학습·배포·추론 | `archive/customer_churn/` |
| 연결·조립 | 외부 서비스 연결, API·Worker 프로세스 구성 | `integrations/`, `entrypoints/` |

OpenMetadata가 자산·스키마·용어를, Teoria가 업무 Ontology와 승인 이력을,
Prefect가 실행·스케줄을 관리한다. 문서 본문과 처리 산출물은 객체 저장소에 둔다.
AI의 제안과 승인된 정의를 구분한다.

## 시작하기

- [아키텍처](docs/architecture/overview.md): 데이터·Ontology·앱의 관계
- [저장소 구조](docs/architecture/repository-structure.md): 코드를 수정할 위치
- [사용 안내](docs/platform-guide.md): 화면에서 할 수 있는 일
- [개발 안내](docs/development.md): 설치와 검증 명령
- [k3d 실행](docs/deployment/k3d.md): 로컬 Kubernetes·이미지 빌드·배포·데이터 보존
- [Compose 실행](docs/deployment/compose.md): 기존 로컬 구성·실행·종료
- [구현 상태](docs/roadmap.md): 구현한 것과 남은 일

전체 참고 자료는 [문서 목차](docs/index.md)에 있다.
