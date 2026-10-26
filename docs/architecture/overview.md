# Teoria architecture

Teoria는 AI-Native Metadata & Ontology Platform이다. 현재 활성 업무는 명시 입력 규격서의
파싱·물품 정보 추출·표준 후보 관리다. 법령 수집·조회는 메타데이터 진단의 근거 저장소로 별도 운영한다. 기존 조달 이력·기업 분석과 조달 API 수집은
`archive/procurement_services/`로 이동했으며 운영 실행 경로에서 import하지 않는다.
소스는 `backend/`의 기능별 모듈과 `frontend/`로 통합한다. API·MCP·규격서·법령·메타데이터
Worker는 별도 프로세스·이미지·권한을 유지한다. 기능 소유권은 [저장소 구조](repository-structure.md)를 따른다.

```text
Platform Ontology 작성·검토·게시
  ├─ Published 개념 → 정규화 프로파일 작성·검토·승인 → 고정 JSON 패키지
  │                                                       │
  │                                                       ▼
  │       명시 입력 규격서 → Pipelines / Prefect → 파일·S3 산출물
  │                                             + Data DB 실행·참조
  │
  ├─ Semantic Binding ↔ OpenMetadata의 Glossary·Asset 참조
  └─ versioned Runtime artifact → Runtime API → MCP
                                      │
                                     OPA
```

물품 정규화 프로파일은 Published 개념을 참조하여 작성·승인하고 고정 JSON 패키지로 Pipeline에 전달한다.
Pipeline은 이를 오프라인 적용하고 새 의미 후보를 산출물로 보존한다. 프로파일을 Business Ontology로 저장하지 않는다.
미해결 후보의 문맥별 묶기·기존 개념 검색과 선택 결과의 새 프로파일 Draft 작성을 지원한다.
Codex가 의미 연결·신규 개념 초안을 제안하고 기존 작성 절차로 Draft를 만드는 경로도 제공한다.
서버 관찰의 Source·Mapping·검색·비교·근거 조회는 격리 환경에서 검증했으며 운영 bundle 전환은 남아 있다.
파일·S3의 추출 결과가 자동으로 Ontology나 Runtime Object가 되는 것은 아니다.

## 권위와 실행 경계

| 시스템 | 소유하는 정보 |
|---|---|
| Prefect | workflow 실행·schedule·retry |
| Data DB | 실행 상태·문서별 결과 요약·산출물 URI·checksum |
| 파일/S3 | 규격서 원문·추출 결과·표준 draft·Markdown |
| OpenMetadata | 기술·거버넌스 metadata·Glossary·품질·lineage |
| Teoria Application DB | Business Ontology·Semantic Binding·Suggestion/Review/Application·Context 설정·물품 정규화 프로파일 |
| Runtime artifact | 게시 Ontology·승인 Binding·실행 Registry·CapabilityVersion의 불변 snapshot |

OpenMetadata entity 본문을 Teoria DB에 복제하지 않고 MetadataTargetRef로 연결한다.
Runtime Mapping은 source record→Object·Link, Semantic Binding은 개념↔자산·용어·기능 연결이다.
Pipeline은 Platform Capability나 Mapping Runtime을 직접 호출하지 않는다.
MCP는 Runtime HTTP API만 호출하며 DB 권한·Provider credential을 갖지 않는다.

## 변경과 운영

AI 결과와 추출 표준 자동 채택은 draft다. 승인 전 Published Ontology를 변경하지 않는다.
Ontology 변경은 새 Draft에서 검토·승인·게시하고 Runtime은 checksum 검증 bundle만 적재한다.
Admin 쓰기의 actor는 인증 principal이다. 운영은 별도 bearer credential과 OPA를 사용한다.
HTTP·DB I/O는 native async이며 승인·transaction·체크포인트 순서를 보존한다.
적용된 migration·게시 artifact·이관 이력은 수정하지 않는다.

Compose는 Data DB와 Control/Application PostgreSQL을 분리하고,
후자는 Application·Prefect·OpenMetadata database와 role을 나눈다.
추출·적용 Flow와 이를 작성 API에 연결하는 상위 표준관리 Flow는 수동 manifest로 제출한다.
metadata ingestion은 Prefect가 관리한다.
OpenMetadata ingestion dependency는 전용 ephemeral Job에 둔다.
현재 구성과 완료 조건은 [시작 안내](../platform-guide.md)와 [로드맵](../roadmap.md)을 따른다.

과거 조달 운영 데이터와 미사용 goods Draft는 [백업 검증 후 정리했다](../verification/retired_data_cleanup_2026_10_26.md).
법령·게시 Ontology·승인 이력과 현재 Runtime bundle은 보존한다.
