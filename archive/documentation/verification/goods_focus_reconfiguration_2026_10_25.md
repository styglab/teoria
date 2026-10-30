# 규격서·물품 Ontology 중심 재구성 검증

검증일: 2026-10-25 UTC. 저장소 재구성과 운영 수집 중단을 구분한다.

## 변경 범위

Ontology·Binding·Source·Mapping·Capability·Runtime·Context·OPA·MCP·OpenMetadata·Prefect 기반은 유지했다.
규격서 파싱·정보 추출·표준 후보 관리·고정 표준 적용과 평가 CLI는 기존 소유 패키지에서 유지했다.
기존 기업·조달·법령 업무 구현, Registry·Connector 계약과 전용 테스트는
`archive/procurement_services/`에 비활성 보관했다. 코어 검증 일부는 이전 계약을 명시적인 fixture로 읽는다.
이전 기록의 테스트 수를 현재 활성 기능의 테스트 수로 사용하지 않는다.

- 활성 Registry: 공통 타입 11개·값 집합 15개. Source·Mapping·Capability·Runtime 계약은 0개.
- 기존 Runtime 객체 38개의 비활성 분류 manifest를 새 pending 이관에 추가했다.
- 물품 Ontology blueprint는 `goods` namespace의 규격서·물품 항목·요구조건 3개 Object와 관계 4개다.
  파일과 Draft 생성 경로를 검증했으며 운영 Application DB에 생성하거나 게시하지 않았다.
- 활성 Deployment 선언은 명시 manifest를 받는 규격서 작업 2개와 OpenMetadata 동기화 1개다.
  규격서 작업은 cron이 없고 전용 `documents` queue를 사용한다.
- Compose Worker에는 별도 parser 환경, 고정한 모델 CLI, 입력·산출물·인증 volume을 구성했다.
  기존 Provider credential 주입과 조달 질문 UI를 제거했다.

## 운영에서 확인한 상태

기존 `teoria-ingestion` pool과 해당 Deployment 22개를 일시정지했다.
마지막 확인에서 이 Deployment들의 Running·Pending·Scheduled·Cancelling 실행은 0개였다.
OpenMetadata 동기화는 중단 대상에 포함하지 않았다.
DB·볼륨·수집 데이터·체크포인트·게시 Ontology·Runtime artifact는 삭제하거나 변경하지 않았다.

## 검증 결과

| 검사 | 결과 |
|---|---|
| Platform 전체 테스트 | 216 passed, 25 skipped |
| Pipelines 전체 테스트 | 175 passed, 7 skipped |
| Admin UI 테스트 | 45 passed |
| Admin UI production build | 통과 |
| Compose 설정·지속 볼륨·인증·Worker 검사 | 5 passed |
| 문서 검사기 회귀 | 7 passed |
| 문서 링크 | 401개 링크·95개 문서, 오류 0 |
| 활성 Registry 검증 | 통과 |
| Pipeline·Platform 계약 교차 검증 | 통과 |
| 명시 manifest의 Ontology 이관 보고서 | valid, 기존 객체 38개 DEPRECATED |
| 규격서 Worker 이미지 | 실제 빌드 성공, 두 Flow import·DOCX 파싱·모델 CLI 버전 확인 |
| Platform authoring 이미지 | 실제 빌드 성공, Registry·blueprint load·Admin 앱 생성 확인 |

격리 DB 환경변수 등이 필요한 검사는 skipped로 남았다. 이번 검증에서 실제 모델 추론을
실행하거나 새 Worker·Admin·Runtime 이미지를 운영에 교체하지 않았다.
검증 이미지 태그는 `teoria-specification-review:20261025`, `teoria-platform-review:20261025`다.

## 남은 연결

추출 결과→Ontology Suggestion·검토·승인, 물품 데이터 materialization·Source·Mapping,
물품 검색·비교 Capability와 Context query handler는 후속 구현이다.
초안 파일이나 추출 표준 자동 채택을 Published Ontology 또는 완성된 AI 질의로 간주하지 않는다.
운영 전환에는 필요한 DB migration·모델 인증 구성과 새 Registry를 사용하는 Runtime bundle 발행·검증이 필요하다.
이전 조달 artifact를 새 코드에 그대로 연결해 기능이 제거되었다고 판단하지 않는다.
