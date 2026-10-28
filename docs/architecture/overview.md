# 시스템 아키텍처

Teoria는 데이터 자산·업무 의미·AI 실행을 연결한다. 첫 업무 앱은 규격서 분석이다.
코드는 한 저장소에 두고 API·Runtime·MCP·각 Worker는 역할별로 실행한다.
구체적인 코드 위치는 [저장소 구조](repository-structure.md)를 따른다.

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
| Application DB | Business Ontology·Binding·사전·프로파일·제안·승인 이력·Context 설정 |
| Data DB | 실행 상태·문서별 요약·산출물 참조·수집 raw·checkpoint |
| 파일/S3 | 규격서 원문·추출 본문·표준 적용 결과·보고서 |
| Prefect | 실행 순서·Task 상태·스케줄·재시도 |
| Runtime artifact | 게시 Ontology·승인 Binding·실행 Registry를 고정한 스냅샷 |

## 지켜야 할 경계

- 추출 관찰과 AI 제안은 게시된 업무 의미가 아니다. 승인·게시는 별도 단계다.
- 원문 표현 등록, 표준 개념 정의, 원문과 개념의 매핑은 따로 관리한다.
- Pipeline의 의미 작성 요청은 인증된 Admin HTTP API를 사용한다. Capability·Mapping Runtime을 직접 호출하지 않는다.
- MCP는 Runtime HTTP API만 호출하고 DB에 직접 접근하지 않는다.
- OpenMetadata entity 본문은 Teoria DB에 복제하지 않는다. MetadataTargetRef로 연결한다.
- Runtime Mapping은 원본 레코드→실행 객체, Semantic Binding은 업무 개념↔용어·자산·기능 연결이다.
- Published version과 Runtime artifact는 직접 수정하지 않는다. 새 Draft를 승인·게시해 새 artifact를 만든다.

## 현재 구현과 후속 작업

규격서는 추출·검증·사전 연결·결과 저장까지 실행한다. goods 업무 모델은 Draft다.
새 물품 모델의 게시·Runtime 연결과 물품 검색·비교는 후속 작업이다.
법령 수집, OpenMetadata 동기화, 선택형 모델 운영은 전용 Worker에서 실행한다.

사용법은 [사용 안내](../platform-guide.md), 구현 상태는 [로드맵](../roadmap.md),
로컬 실행은 [Compose](../deployment/compose.md), 실제 결과는 [검증 기록](../verification/index.md)을 참고한다.
