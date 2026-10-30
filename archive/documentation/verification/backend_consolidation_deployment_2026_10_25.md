# 통합 백엔드 운영 재배포 — 2026-10-25

검증한 단일 Python 백엔드·별도 프런트엔드 구조를 기존 Compose project `teoria`에 실제 배포했다.
기존 Data/Application DB·네트워크·artifact·모델 인증 volume을 유지했다. K3s 운영 배포 결과는 아니다.
소스 구조와 배포 전 검증은 [구조 통합 기록](backend_consolidation_2026_10_25.md)을 따른다.

## 교체와 보존

- 실행 중인 Prefect 작업과 AI 진단 claim이 없는 상태에서 활성 pool 3개를 일시정지했다.
- API·UI·MCP·Worker·Policy Control Plane 9개 서비스를 새 이미지로 교체했다.
- 역할별 credential, Admin bearer 인증, Worker 자원 제한과 parser 환경 분리를 유지했다.
- 활성 Prefect 배포 6개를 새 `teoria.features.*` 경로로 등록했다. 기존 배포 5개의 ID를 보존했고 수동 표준관리 workflow 1개를 추가했다.
- 예정 실행 9개의 입력 경로도 새 `/app/backend` 기준임을 확인했다.
- Worker heartbeat를 확인한 뒤 법령·metadata·규격서 pool 3개를 원래대로 열었다.
- 기존 수집·AI 추출 pool은 중단 상태다. 은퇴한 수집 배포 20개는 계속 paused이며 규격서 배포 3개에는 자동 스케줄이 없다.

## DB와 복구 자료

전환 전 Application DB 전체 dump와 Data DB schema를 `backups/teoria/backend_redeploy_20261025T164151Z/`에 보관했다.
파일은 소유자 전용 권한이며 checksum 목록, 이전 이미지 태그와 Prefect 전환 전 상태를 함께 보관한다.
이전 이미지는 `teoria-rollback-<service>:20261025T164151Z` 태그로 보존했다. 복구 시 같은 버전의 Prefect 선언을 함께 선택해야 한다.

배포에 필요한 미적용 migration만 실행했다. 기존 적용 SQL은 수정하지 않았다.

| DB | 새로 적용한 migration |
|---|---|
| Application | `017_goods_normalization_profiles.sql`, `018_ontology_relationship_descriptions.sql`, `019_goods_semantic_operations.sql` |
| Data | `092_specification_standard_workflows.sql` |

기존 Ontology 상태 건수(published 1·draft 1·deprecated 11), Binding 이력(approved 38·deprecated 279),
자산 진단 이력(completed 4·partial 2)은 전환 전후 동일하다. 새 Ontology 게시나 자동 승인은 수행하지 않았다.

## 실제 동작 검증

| 대상 | 결과 |
|---|---|
| 새 서비스 이미지 | 9개 모두 새 image ID, running, restart count 0; 정의된 healthcheck 정상 |
| 관리 화면·API·Runtime | nginx를 통한 UI·health·관리 조회 HTTP 200 |
| 인증 | Admin session·물품 프로파일·Runtime의 토큰 없는 요청 HTTP 401 |
| 작성·표준관리 DB | Ontology 목록 HTTP 200; 미존재 profile·semantic operation은 인증 후 예상 HTTP 404 |
| 법령 조회 | 인증 검색 HTTP 200 |
| OpenMetadata | Admin metadata status: enabled=true, available=true |
| Prefect Worker | 법령·metadata·규격서 pool 각각 ONLINE Worker 1개, 최종 READY |
| 규격서 parser | 새 Worker에서 synthetic DOCX 실제 파싱, evidence node 1개와 원본 checksum 검증 |
| 모델 CLI | Admin·규격서 Worker 모두 기존 인증 준비 상태 확인 |
| MCP | 새 운영 이미지로 실제 STDIO initialize·Runtime HTTP discovery·tools/list 성공, 도구 0개 |

아래 두 작업은 새 배포 선언을 사용해 실제 운영 Worker에서 실행했다.

| 작업 | Flow run ID | 시작–종료 UTC | 결과 |
|---|---|---|---|
| `moleg-law-daily` | `65bf42f6-0c0f-4b8e-840d-1928dbd5c618` | 2026-10-25 16:47:30.499388+00:00 – 2026-10-25 16:47:44.930823+00:00 | Completed |
| `openmetadata-postgres-metadata-sync` | `9052502c-ab7b-4744-afdc-42741303171f` | 2026-10-25 16:47:24.440049+00:00 – 2026-10-25 16:47:42.583927+00:00 | Completed |

법령 작업은 대상 6개·버전 목록 118개·본문 처리 8개·구조화 조문 5,208개·실패 0개를 기록했다.
OpenMetadata 작업은 전용 Worker가 allowlist의 공식 ingestion image를 ephemeral Job으로 실행해 완료했다.
실제 사용자 규격서의 전체 AI 추출이나 모델 정확도 평가를 수행한 결과로 해석하지 않는다.

## Runtime artifact

- version: `2026.10.25.1`
- checksum: `sha256:907356fe1bc90b4f0a44fcf8eb670c2f10a73827dd6fa7e920cc9da697e5a5f6`
- 활성 Capability: 0

운영 Runtime에서 위 bundle을 checksum 검증해 적재했다. 기존 게시 artifact와 active pointer를 바꾸지 않았다.
외부에서 이미 열린 STDIO 세션은 재연결 시 새 MCP 이미지를 사용한다. 기존 외부 클라이언트 세션을 강제 종료하지 않았다.

## 배포 이미지

아래는 검증 당시 실행 중인 image ID다.

| 서비스 | Image ID |
|---|---|
| `runtime-api` | `sha256:2e2956fbd9c16ef7a77b92944fe532265baef67f543c98539f1607b9c18c77b9` |
| `admin-api` | `sha256:5e62ec5e7f595caca06b29079ff2f520de0aa116b25caa64b23d4ab85968eecb` |
| `admin-ui` | `sha256:f5ad6c0ef0a683c27af18fd894a6b6e3d814c1f5eaaea11cda5c48b9a315d073` |
| `prefect-worker` | `sha256:b7bd3dc6d216e8d1b42726bb601763be686d8a9ccd0b392bd577f6996fe23d51` |
| `prefect-law-worker` | `sha256:fddc7fc430cfbf61ba43e0cc5aecf7a8ebce3c6b475b5eb8e07c3bd68b46f64b` |
| `prefect-metadata-worker` | `sha256:794dd3d0944b28d10b273c02d39e2bb7a641471056318c4791c289d40c233256` |
| `metadata-assessment-worker` | `sha256:5e62ec5e7f595caca06b29079ff2f520de0aa116b25caa64b23d4ab85968eecb` |
| `policy-control-plane` | `sha256:5e62ec5e7f595caca06b29079ff2f520de0aa116b25caa64b23d4ab85968eecb` |
| `mcp` | `sha256:ba62b8110d4772419c38cc9b207c5b939f7b7f336c2c746ecdb39ff639205e12` |

최종 기록: 2026-10-25 16:51:34 UTC
