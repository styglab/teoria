# 운영 컨테이너 정리 — 2026-10-26

Teoria 관련 실행 컨테이너를 **24개 → 19개**로 줄였다.
확인 시점 기준 운영 Compose 서비스 18개와 개발 환경 1개다.
MCP 연결이 열리면 연결별 임시 컨테이너가 추가되고 연결 종료 시 자동 제거된다.

## 제거한 컨테이너

| 이름 | 용도 |
|---|---|
| `teoria-mcp-1` | 연결 클라이언트 없이 상시 대기하던 STDIO MCP |
| `youthful_kalam` | 구버전 MCP 세션 |
| `trusting_blackwell` | 구버전 MCP 세션 |
| `affectionate_mestorf` | 구버전 MCP 세션 |
| `teoria-review-tests-20261014` | 접속이 없는 과거 검증 PostgreSQL |

구버전 MCP 연결은 종료했으며 클라이언트 재연결 시 현재 이미지를 사용한다.
검증 PostgreSQL은 실행 중인 client backend가 0임을 확인한 후 `pg_dumpall` 압축 덤프와
체크섬을 owner-only 파일로 보관하고 종료했다. 운영 DB·볼륨은 제거하지 않았다.

복구 자료: `backups/teoria/container_cleanup_20261026T075957Z/`.

## MCP 수명주기

`.codex/run_teoria_mcp.py`는 `--rm -i`로 필요할 때만 컨테이너를 실행한다.
이름은 `teoria-mcp-session-<id>`, label은 `io.teoria.role=mcp-stdio`와
`io.teoria.lifecycle=client-session`이다. 상시 MCP 서비스는 일반 Compose 기동에 포함하지 않는다.
[Gateway 안내](../mcp/gateway.md)를 따른다.

## 검증

- 운영 Compose 18개 모두 running, 정의된 healthcheck 모두 healthy.
- nginx 경유 관리·Runtime health·인증 조회·법령 검색 확인.
- 저장소 [test-teoria-mcp Skill](../../.agents/skills/test-teoria-mcp/SKILL.md)의 discovery-only 검증으로 실제 initialize·tools/list 성공; 현재 Tool 수 0.
- 프로토콜 검증 종료 후 MCP 세션 컨테이너가 남지 않음을 확인.
- 검증 DB 덤프 SHA-256 일치, Compose 설정과 문서 링크 검증 성공.
