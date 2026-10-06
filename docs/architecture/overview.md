# Teoria architecture

Teoria는 수집 시스템, metadata catalog, 업무 의미와 실행 계약을 분리한다.
이 문서는 현재 구조의 기준이며 프로젝트별 파일 소유권은
[Repository structure](repository-structure.md)를 따른다.

Teoria의 제품 경계는 특정 조달 서비스가 아니라 여러 업무 도메인의 데이터와
의미를 연결하는 AI-native metadata/ontology platform이다. 공공조달은 Source,
Ontology, Binding, Capability와 Context 실행을 끝까지 검증하는 첫 vertical
domain이다. 조달 고유 규칙은 Domain Registry와 기능 패키지 안에 두고 Platform
공통 계층으로 끌어올리지 않는다.

```text
Provider API ─▶ Pipelines/Prefect ─▶ Teoria Data DB
                                          │
                         ┌────────────────┴──────────────┐
                         ▼                               ▼
                  OpenMetadata                    Platform Runtime
             technical/governance        Source·Mapping·Capability
                         │                               │
                         └──── Semantic Binding ─────────┘
                                         │
                                  Runtime API ─▶ MCP
```

## 권위 경계

| 시스템 | 권위 데이터 | 두지 않는 것 |
|---|---|---|
| Prefect | workflow, schedule, retry, checkpoint | Ontology와 metadata 의미 |
| Teoria Data DB | raw 관찰과 정규화된 업무 데이터 | governance metadata |
| OpenMetadata | asset, schema, glossary, owner, lineage, quality, usage | Business Ontology |
| Teoria App DB | Ontology, Binding, Suggestion, Review, context 설정 | OpenMetadata entity 본문 |
| Runtime Registry | Source, Mapping, Capability 실행 계약 | authoring 상태와 수집 workflow |

OpenMetadata entity는 복제하지 않고 `MetadataTargetRef`의 system, entity ID,
entity type, FQN과 필요한 version만 저장한다. Capability는 독립된 knowledge
source이며 `CapabilityTargetRef` Binding으로 Ontology와 연결한다.

## 실행과 데이터 흐름

- Pipeline은 Provider API를 지속 수집하고 raw와 정규 데이터를 모두 저장한 뒤
  checkpoint를 갱신한다.
- Runtime은 직접 호출 Source 또는 Data DB의 read-only relation을 Mapping으로
  runtime object에 변환하고 Capability를 실행한다.
- MCP는 Runtime HTTP API만 호출하며 DB 권한이나 Provider credential을 갖지 않는다.
- Provider wire 계약과 HTTP 실행은 `teoria-provider-api`만 담당한다.
- Pipeline 실행 코드는 Platform Capability나 Mapping Runtime을 호출하지 않는다.

## 저장소와 배포

로컬 Compose는 Data Plane인 `teoria_data`를 별도 PostgreSQL에 두고,
`teoria_app`, `prefect`, `openmetadata_db`는 database와 role을 분리해
Control/Application PostgreSQL에 둔다. database 간 SQL join은 허용하지 않는다.
부하, 장애 격리 또는 backup 정책이 달라지면 connection URL을 변경해 별도
인스턴스로 분리한다.

OpenMetadata ingestion 일정과 재시도는 Prefect가 소유한다. 공식 ingestion
image를 ephemeral Job으로 실행하며 일반 Prefect Worker에 ingestion dependency를
설치하지 않는다. Compose에서는 격리된 Docker worker를, k3s에서는 전용
Kubernetes work pool을 사용한다.

## 변경 불변식

- AI 결과는 Suggestion이며 review, approval, 적용 성공 전에는 권위 정보가 아니다.
- Admin 쓰기는 인증 principal을 actor로 기록한다.
- Published Ontology revision은 직접 수정하지 않는다.
- Runtime은 Published version에서 생성한 checksum 검증 가능한 immutable
  artifact를 사용한다. 운영 환경은 authoring Registry 경로를 직접 읽지 않으며
  `TEORIA_RUNTIME_ARTIFACT_PATH` 또는 atomic active pointer를 사용하는
  `TEORIA_RUNTIME_ARTIFACT_STORE`를 반드시 설정한다.
- Application DB와 Data DB migration은 이미 적용된 파일을 수정하지 않고 새 순번을 추가한다.
- Source와 Connector를 같은 API에 중복 등록하지 않는다.
- 운영에서는 Admin과 Runtime에 별도 bearer credential을 사용한다.

Ontology 모델은 [Ontology](ontology.md), Registry 계약은
[Registry guide](../registry/README.md), 배포 방법은 [Deployment](../../deploy/README.md)를
참고한다.
