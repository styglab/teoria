# 계약 구조 변경 운영 재배포 — 2026-10-26

계약·작성 입력·Prefect 배포 선언의 새 경로를 사용하는 검증 이미지를 기존 Compose 운영에 반영했다.
코드 이관은 [구조 정리 기록](backend_contract_structure_2026_10_26.md), 현재 위치는 [저장소 구조](../architecture/repository-structure.md)를 따른다.
K3s 클러스터 배포 결과는 아니다.

## 전환과 복구

- Runtime·Admin·Policy Control Plane·규격서·법령·Metadata·진단 Worker·MCP 서비스 8개를 새 이미지로 교체했다.
- 교체 전 Prefect 실행과 실행 중 AI 진단이 없음을 확인하고 활성 pool 세 개를 일시정지했다.
- 기존 이미지를 rollback tag로 보존하고 이전 Registry 경로 환경까지 포함한 복구용 Compose override를 기록했다.
- Worker heartbeat와 API 준비 상태를 확인한 뒤 기존 pool의 pause 상태를 복원했다.
- 이미지 7종의 Python 소스 digest가 검증한 작업 디렉터리와 같음을 확인했다. Check 이미지는 운영 상시 서비스가 아니다.
- DB migration·Ontology 게시·새 Registry release·Runtime artifact 전환은 하지 않았다.
- 기존 UI·PostgreSQL·OpenMetadata·Prefect Server·Redis·OPA 서비스는 교체 대상에 포함하지 않았다.
- 복구 자료: `backups/teoria/backend_contracts_redeploy_20261026T074949Z/`. credential이 없는 상태·이전 이미지 참조·복구 override를 owner-only 파일로 보관한다.

## 실제 검증

| 대상 | 결과 |
|---|---|
| 컨테이너 | 변경 서비스 8개 running, restart 0, 정의된 healthcheck healthy |
| API | nginx 경유 UI·Admin·Runtime health·인증 조회·법령 검색 성공 |
| 인증 | 보호된 Admin·Runtime 익명 요청 401, 인증된 요청 200, 없는 자원 404 |
| OpenAPI | Admin 71개 path 확인 |
| Parser | 배포 Worker에서 synthetic DOCX 파싱·원본 checksum 검증 성공 |
| MCP 단위 테스트 | 11 passed |
| MCP STDIO | 현재 Codex 설정으로 initialize·tools/list 성공, 현재 구성에 맞는 Tool 수 0 |
| Prefect | 기존 배포 26개 ID·entrypoint·pause·schedule 보존, 활성 6개 |
| 예약 입력 | 기존 예정 Run 9개의 pipeline_root가 `/app/backend`임을 확인 |
| 권위 상태 | Ontology·Binding·진단 상태별 건수 전환 전후 동일 |
| 사전 검증 | 전체 553 passed·격리 DB/S3·이미지 7종 build·법령 Build/Live 성공 |

법령·metadata 실제 실행은 아래 두 Run에서 Completed를 확인했다. 규격서의 실제 사용자 문서 전체 AI 정확도 평가를 수행한 것은 아니다.

| 작업 | Flow run ID | 시작 UTC | 종료 UTC | 상태 |
|---|---|---|---|---|
| `moleg-law-daily` | `af4e8746-baed-436e-9ed9-726b84773ae5` | 2026-10-26 07:53:02.138653+00:00 | 2026-10-26 07:53:16.500063+00:00 | Completed |
| `openmetadata-postgres-metadata-sync` | `56078cd1-5b78-4463-bd1e-376211dc47b6` | 2026-10-26 07:53:01.315601+00:00 | 2026-10-26 07:53:20.665936+00:00 | Completed |

## MCP 클라이언트 보완

실제 STDIO 검증에서 `.codex/config.toml`에 통합 전 `--package teoria-mcp` 실행 명령이 남아 있음을 발견했다.
이를 `--project backend --extra mcp`로 수정하고 같은 설정으로 protocol 초기화와 Tool discovery를 재검증했다.
현재 조달 Capability는 비활성 상태이므로 저장소 [검증 Skill](../../.agents/skills/test-teoria-mcp/SKILL.md)에
`--discovery-only` 검증을 추가했다. 기존 조달 Tool 실행 검증은 해당 Capability가 활성이고 사용자가 요청한 경우에만 적용한다.
기존에 열린 외부 STDIO 세션을 강제로 종료하지 않았으며 새 연결은 갱신한 이미지와 명령을 사용한다.

## 불변 상태

- Runtime version: `2026.10.25.1`
- Runtime bundle checksum: `sha256:907356fe1bc90b4f0a44fcf8eb670c2f10a73827dd6fa7e920cc9da697e5a5f6`
- 은퇴한 조달·AI 추출 pool과 배포 20개는 계속 paused다. 규격서 배포 세 개는 수동 실행을 유지한다.

| 서비스 | 새 image ID |
|---|---|
| `runtime-api` | `sha256:507d6021396096b45bd2cbac81d6928f1ddeb3a9f27b87b740b4ae77a5f0786d` |
| `admin-api` | `sha256:25321dd56947c73067e4bd79b2d36c553b8b08e02ac5aa78e1a30e652dd8d04a` |
| `policy-control-plane` | `sha256:25321dd56947c73067e4bd79b2d36c553b8b08e02ac5aa78e1a30e652dd8d04a` |
| `prefect-worker` | `sha256:6ed176673456bb523b4c5db80e352d178bc90fbf8f3b686b963b175554f1b3cb` |
| `prefect-law-worker` | `sha256:49f3bbc8231490f3600b559977d909f2fedea561bb074f98d8940bbdf06dd93b` |
| `prefect-metadata-worker` | `sha256:8e9e27b39b7b13d2ed66f3ae3cf9242019266a3a3ff7b7550444fbc94b3d9034` |
| `metadata-assessment-worker` | `sha256:25321dd56947c73067e4bd79b2d36c553b8b08e02ac5aa78e1a30e652dd8d04a` |
| `mcp` | `sha256:6e46a25b4dd9da2152fef23889e0ceda6f670072499bd0781f9e265259270aa0` |

기록: 2026-10-26T07:54:49.768473+00:00
