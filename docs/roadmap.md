# 구현 상태와 다음 작업

Teoria는 Metadata & Ontology 플랫폼, 물품·법령 도메인, FormatID 업무 앱으로 구성한다.
코드와 테스트는 이 경계를 따르며 Python 프로젝트는 하나다.
플랫폼은 데이터·Ontology·향후 AI와 별도 MLOps 영역으로 구분한다.
AI/AIP는 예약 폴더만 있으며 미구현이다. 기존 기능별 LLM 호출과 MLOps를 AIP로 표시하지 않는다.

## 현재 구현

| 영역 | 제공하는 기능 |
|---|---|
| 데이터 운영 | Connector 검증·수집 기반·원본·checkpoint, Prefect 실행·스케줄 관리 |
| 메타데이터 | OpenMetadata 자산 조회·AI 진단·Suggestion 검토·적용 |
| Ontology | Draft·검토·승인·게시·버전 artifact·공개 publication 조회 |
| 의미 연결 | 개념과 용어·자산·API·Capability의 Binding 검토·승인 |
| Runtime | Source·Mapping·Capability·artifact·Context·HTTP/MCP 기반; 문서 요구조건 고정 조회 계약은 validated 상태 |
| 물품 | 규격서 추출·프로파일/표현 연결의 별도 승인·고정 snapshot 적용·문서 해석·감사·단계별 평가 연결 |
| 법령 | 전용 Worker의 수집·시점 검색·진단 근거 조회 |
| FormatID | 문서 입력·실행·결과·원문 근거·재처리·단계 상태·검증된 평가 근거 연결 |
| 프런트엔드 기반 | Shell·라우트 분리, 소유 모듈별 API, TanStack Query·요청 취소·세션별 캐시 초기화 |
| 별도 선택형 MLOps | 외부 이미지 공통 실행 계약·MLflow 조회·모델별 서빙·중지·이전 설정 재배포; Compose Docker와 Kubernetes 실행 구현, K3s 실운영 미검증 |

플랫폼 내장 Image Registry 배포를 제거하고 기존 Registry 연결로 전환했다.
로컬 k3d는 플랫폼·모델 이미지에 공용 Registry 하나를 사용하며 운영은 기존 Registry를 연결한다.
MLflow 화면 인증은 Registry 계정 대신 Prefect 운영 계정을 사용한다.
내장 Registry가 배포 결과에서 제외되는 검사, 외부 Registry 실컨테이너 연동,
MLflow 인증 프록시와 Kubernetes API의 server dry-run을 검증했다.
MLflow 서버 이미지는 `teoria-mlflow`로 분리하고 서버 전용 의존성만 설치한다.
고객 이탈 샘플은 `pyproject.toml`·`uv.lock`으로 의존성을 관리하며 Python 모듈 명령으로 실행한다.
플랫폼 이미지 prefix·릴리스 게시·pull과
Admin의 repository·tag·digest 조회를 추가했다. 격리 Docker에서 TLS·인증·이미지 게시·조회·보존을 검증했다.
공통 학습·서빙 실행 계약을 구현했다. Compose 실컨테이너 검증과 K3s 운영 배포 검증은 구분하며,
K3s 클러스터의 실제 배포·GPU·다중 노드 장애 복구는 별도 검증 대상이다.
고객 이탈 전용 API·Flow·화면 연결과 이미지 빌드 target을 제거하고
기존 전용 구현·테스트 보관본은 제거했다.
현재 이미지 실행 계약을 따르는 독립 학습·서빙 샘플과 Dockerfile은
[archive/customer_churn](../archive/customer_churn/README.md)에 보관한다.

MLOps의 특정 예제 파라미터 목록·단일 모델 기본값·구형 추론 서비스 화면 연결을 제거했다.
모델 레지스트리와 배포 목록의 조회를 분리하고 업무 앱·도메인·모델 운영의 책임 기준을 명시했다.
실제 운영 배포 검증과 향후 AI 실행 기반 구현은 별도 범위다.

## 다음 순서

1. **물품 2.0.0 Draft 검토**: 서버·메모리 업무 정의와 실제 규격서 근거를 대조하고 승인·게시한다.
2. **게시 정의 기반 적용 검증**: 개념 연결·프로파일의 품목 확장과 실제 문서 회귀 평가를 진행한다.
3. **물품 Runtime 운영 전환**: 승인된 실제 연결·프로파일로 조회 view를 생성하고 새 bundle에 고정한다. 격리 HTTP·FormatID 통합 경로는 구현했으며 운영 Capability 활성화·배포는 남아 있다.
4. **운영 환경 검증**: 역할별 권한·객체 저장소·Worker·게시 artifact를 실제 배포에서 확인한다.

실제 서버 문서의 [네 항목 검토 준비](../backend/authoring/specification_examples/server_memory_review.yaml)는
보존된 객체 저장소의 원문·결과·검토 해시와 네 관찰 ID를 재확인했다. 운영 Draft 재조회와 의미 승인이 필요하다.
소유 대상·scope·구성 수량의 문서별 승인·별도 적용·Runtime 제공 경로는 구현했다.
표준 워크플로우는 프로파일과 표현 연결 승인을 구분하며, 고정 적용과 단계별 재개·평가 경로를 연결했다.
후보·연결 판단은 소유 모듈에 두고, 표준 구축 Flow·Task는 I/O·순서·대기·재개를 조립한다.
격리 PostgreSQL에서 migration·동시 승인·불변 재적용·감사를 검증했으며 실제 문서의 의미 승인·운영 배포는 남아 있다.

구조 변경의 단위 테스트·빌드·Compose 템플릿 검증과 실제 배포 성공은 구분한다.
현재 물품 Draft 준비의 실제 검증 범위는 [11월 9일 기록](verification/goods_native_draft_preparation_2026_11_09.md)에 있다.

## 유지하는 범위

공고·계약·낙찰·개찰·업종 수집과 기업 분석은 `archive/procurement_services/`에 비활성 보관한다.
구형 첨부 자동 수집과 참가자격 판단도 재활성화하지 않는다.
기존 게시·DB·migration 이력을 유지하며, 새 업무 정의는 Ontology에서 작성한다.
v1 사전 쓰기는 과거 평가·재현을 위한 호환 영역에 둔다.

[아키텍처](architecture/overview.md) · [사용 안내](platform-guide.md) · [검증 기록](roadmap.md)

Kubernetes 리소스·Prefect 정책을 배포판 독립 base로 옮기고 generic·K3s overlay를 분리했다.
generic의 표준 Ingress·공유 스토리지 선택·UI 프록시와 공통 진입점의 K3s overlay를 검증한다.
운영 클러스터별 Ingress·CSI·장애 복구 검증은 별도 범위다.

K3s 별도 배포 폴더와 호환 스크립트를 제거하고 EC2 workflow·설치 설정·Secret 예시를 공통 Kubernetes 경로로 통합했다.

로컬 k3d 클러스터·개발 Registry·TLS·보존 스토리지와 k3d overlay를 추가했다.
공통 Kubernetes 배포와 이미지를 재사용하며 Compose와 EC2 운영 K3s 경로를 유지한다.
2026-11-11 배포·문서 검사 25개와 실제 k3d 검사 1개가 통과했다.
Registry pull·로컬 DNS/TLS 서비스 응답·클러스터 재생성 후 데이터 재접속을 확인했다.
전체 서비스·규격서 처리와 운영 검증 여부는 [k3d 안내](deployment/k3d.md)의 범위와 구분한다.
