# 법령 수집·조회 복구 검증

검증일: 2026-10-25 UTC. 사용자의 법령 기능 재개 요청에 따라 현재 Compose 환경에 배포했다.
이전 [물품 중심 전환](goods_focus_deployment_2026_10_25.md) 이후 법령 기능만 복구한 기록이다.
조달 수집·Backfill은 재개하지 않았다.

## 복구 범위

- Pipelines `domains/legal_information/laws/`: 원문·연혁 수집·파싱·저장·checkpoint와 law CLI
- 법제처 Connector `moleg_law_api`, 수집 정의·원문 Reference·Operation별 검증 입력
- `prefect.legal_information.yaml`: 일일 변경 동기화와 일요일 전체 연혁 보정
- Platform `domains/legal_information/`: 인증된 Admin 검색·문서 원문 조회
- AI 자산 진단 Worker의 `LawSearchReader` 주입과 법령 snapshot 근거 연결
- 관련 단위·저장·프로젝트 간 계약 테스트와 현재 운영 문서

법령은 Runtime Source나 업무 Capability로 등록하지 않는다. 현재 Runtime bundle
`2026.10.25.1`과 업무 Capability 0개 상태는 그대로다. Ontology·Binding 승인 상태를 변경하지 않았다.
이전 archive의 법령 사본은 당시 snapshot이고 활성 코드는 원래 소유 프로젝트에 복구했다.

## 실행 격리

법령 전용 Compose `prefect-law-worker`는 `teoria-pipelines-law:latest`의 `law-worker` target이다.
parser·모델 CLI를 설치하지 않으며 법제처 credential만 환경변수로 받는다.
규격서 Worker에 법제처 credential을 추가하지 않았다.

| 항목 | 상태 |
|---|---|
| 법령 pool·queue | `teoria-legal-information` / `laws`, READY |
| 동시 실행·자원 상한 | 1개, CPU 1, 메모리 2GiB |
| `moleg-law-daily` | 활성, 월~토 04:15 Asia/Seoul |
| `moleg-law-weekly-reconciliation` | 활성, 일요일 04:15 Asia/Seoul |
| 기존 조달 pool | PAUSED |
| 기존 조달 Deployment | 20개, 전부 일시정지 |
| 규격서 pool | READY, 변경 없음 |

기존 법령 Deployment 2개의 ID·실행 이력은 유지하고 전용 pool로 이동했다.
일요일 법령 버전 보정은 법령 근거 저장소의 작업이며 조달 Backfill을 재개하는 작업이 아니다.
K3s에는 별도 dispatcher·pool·법령 전용 Secret 구성을 반영했다. 실제 K3s 운영 배포를 검증한 것은 아니다.

## Provider와 실제 수집 검증

`list_law_versions`, `get_law_version` 모두 Build·Live 검증을 통과했다.
공개 법령의 검증 입력만 사용했고 credential·전체 Live 응답을 보고서에 기록하지 않았다.

실제 Prefect 실행 ID: `00e8e9f0-88fe-471e-b18f-334ee5fd7b30`.
실행은 2026-10-25 12:42:06~12:42:20 UTC에 Completed로 종료했고 Data DB 완료 상태도 일치했다.

| 지표 | 결과 |
|---|---:|
| 대상 법령·시행령 | 6 |
| 확인한 버전 목록 | 118 |
| 이번 실행에서 처리한 버전 | 8 |
| 처리한 조문 구조 항목 | 5,208 |
| 실패 대상 | 0 |
| checkpoint | 2026-10-25 |

처리 건수는 재조회·갱신을 포함하며 새 고유 항목 수가 아니다.
기존 원본·snapshot·데이터·checkpoint를 삭제하거나 임의로 앞당기지 않았다. 새 DB migration은 필요하지 않았다.

## 조회·AI 근거 연결 검증

- 인증된 `POST /v1/admin/legal-information/search`: HTTP 200, 공개 법령 근거 3건 반환
- 해당 snapshot·path의 원문 조회: HTTP 200, 본문 존재·잘림 없음
- 인증 없는 검색 요청: HTTP 401
- 실제 Data DB reader와 고정 검색어 모델 대역으로 자산 진단의 근거 수집 경로 검증:
  법령 snapshot 근거 5건, partial false, 진단 오류 0건, snapshot ID·hash·기준일 provenance 보존
- Admin API와 메타데이터 진단 Worker 교체 후 정상 기동

마지막 검사는 검색어 생성 모델을 대역으로 사용했다. 실제 AI의 법률 해석 품질이나
개방 적합성 판정을 검증한 것이 아니다. 결과는 검토 초안이며 자동 Tag·Published Ontology 변경을 하지 않는다.

## 자동 검사

- Platform 전체: 223 passed, 25 skipped
- Pipelines 전체: 196 passed, 12 skipped
- 법령·기존 배포 등록 회귀: 12 passed, 1 skipped
- 프로젝트 간 법령 DB 통합 검사: 격리 DB 환경변수 미설정으로 6 skipped
- Compose 설정·credential 격리 검사: 6 passed
- 활성 Connector·Pipeline 정적 및 Platform 교차 계약 검사 통과
- 배포 목록 생성·일치 검사, 문서 링크 검사, K3s shell 문법 검사 통과

격리 DB 검사 skip을 실제 저장 검증 성공으로 계산하지 않았다. 실제 운영에서는 공개 법령 수집의
Data DB 완료·checkpoint와 인증된 조회를 별도로 대조했다.
현재 절차는 [법령 수집](../../../docs/pipelines/domains/legal_information.md), [진단용 조회](../../../docs/platform/metadata/law_evidence.md),
[Prefect](../../../docs/pipelines/prefect.md), [Compose](../../../docs/deployment/compose.md)를 따른다.
