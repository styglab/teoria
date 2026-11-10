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
| 물품 | 규격서 추출·근거 검증·표현 연결·프로파일 승인·문서별 해석 승인·별도 적용·감사 |
| 법령 | 전용 Worker의 수집·시점 검색·진단 근거 조회 |
| FormatID | 문서 입력·실행·결과·원문 근거·재처리·단계 상태·검증된 평가 근거 연결 |
| 프런트엔드 기반 | Shell·라우트 분리, 소유 모듈별 API, TanStack Query·요청 취소·세션별 캐시 초기화 |
| 별도 선택형 MLOps | 공통 모델·버전 조회; 합성 고객 학습·배포·추론은 `examples/customer_churn/`에서 연결 |

## 다음 순서

1. **물품 2.0.0 Draft 검토**: 서버·메모리 업무 정의와 실제 규격서 근거를 대조하고 승인·게시한다.
2. **게시 정의 기반 적용 검증**: 개념 연결·프로파일의 품목 확장과 실제 문서 회귀 평가를 진행한다.
3. **물품 Runtime 운영 전환**: 승인된 실제 연결·프로파일로 조회 view를 생성하고 새 bundle에 고정한다. 격리 HTTP·FormatID 통합 경로는 구현했으며 운영 Capability 활성화·배포는 남아 있다.
4. **운영 환경 검증**: 역할별 권한·객체 저장소·Worker·게시 artifact를 실제 배포에서 확인한다.

실제 서버 문서의 [네 항목 검토 준비](../backend/authoring/specification_examples/server_memory_review.yaml)는
보존된 객체 저장소의 원문·결과·검토 해시와 네 관찰 ID를 재확인했다. 운영 Draft 재조회와 의미 승인이 필요하다.
소유 대상·scope·구성 수량의 문서별 승인·별도 적용·Runtime 제공 경로는 구현했다.
격리 PostgreSQL에서 migration·동시 승인·불변 재적용·감사를 검증했으며 실제 문서의 의미 승인·운영 배포는 남아 있다.

구조 변경의 단위 테스트·빌드·Compose 템플릿 검증과 실제 배포 성공은 구분한다.
현재 물품 Draft 준비의 실제 검증 범위는 [11월 9일 기록](verification/goods_native_draft_preparation_2026_11_09.md)에 있다.

## 유지하는 범위

공고·계약·낙찰·개찰·업종 수집과 기업 분석은 `archive/procurement_services/`에 비활성 보관한다.
구형 첨부 자동 수집과 참가자격 판단도 재활성화하지 않는다.
기존 게시·DB·migration 이력을 유지하며, 새 업무 정의는 Ontology에서 작성한다.
v1 사전 쓰기는 과거 평가·재현을 위한 호환 영역에 둔다.

[아키텍처](architecture/overview.md) · [사용 안내](platform-guide.md) · [검증 기록](roadmap.md)
