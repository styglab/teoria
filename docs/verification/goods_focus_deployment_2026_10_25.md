# 규격서·물품 Ontology 운영 배포 검증

검증일: 2026-10-25 UTC. 대상은 현재 실행 중인 `teoria` Docker Compose 스택이다.
EC2 K3s 배포·실제 문서 추출 품질의 완료를 뜻하지 않는다.
이전 [저장소 재구성 기록](goods_focus_reconfiguration_2026_10_25.md) 이후 실제 운영 전환을 수행했다.

## 배포 결과

- Runtime·Admin API·UI·규격서 Worker·Metadata Worker·선택적 진단 Worker를 새 이미지로 교체했다.
- 기존 MCP 컨테이너를 재시작해 새 discovery를 적재했다.
- Data DB migration `090_specification_processing_runs.sql`, `091_specification_processing_schema_usage.sql`을 적용했다.
- 규격서 작업 2개를 `teoria-specification` / `documents`에 등록했다. pool은 READY,
  각 작업은 필수 `manifest` 입력을 받고 자동 cron은 없다.
- 이전 수집 pool과 Deployment 22개는 일시정지를 유지한다. 마지막 확인에서 실행·대기 작업은 0개다.
- 입력·산출물·모델 인증은 별도 named volume에 두었다. 인증정보를 이미지·문서·로그에 넣지 않았다.
- 모델 CLI 인증 확인과 합성 입력의 실제 추론 호출이 성공했다. 전체 문서 품질 검증과 구분한다.
- OpenMetadata의 실제 Prefect 동기화 실행이 Completed로 종료했다.

## Runtime artifact와 의미 이력

| 항목 | 값 |
|---|---|
| 이전 active version | `2026.10.16.90` |
| 새 active version | `2026.10.25.1` |
| 새 bundle checksum | `sha256:907356fe1bc90b4f0a44fcf8eb670c2f10a73827dd6fa7e920cc9da697e5a5f6` |
| Registry checksum | `sha256:e2cdb2e2459438d524bbc36469a209be4862218b133a91d076a621982de82884` |
| Published Ontology snapshot | 기존 `teoria 0.1.4` 1개 |
| 승인 metadata Binding snapshot | 16개 |
| 활성 Source·Mapping·Capability | 각 0개 |

제거된 Capability를 가리키는 승인 Binding 22개는 새 snapshot에서 제외했다.
Application DB의 기존 승인·검토 이력은 수정하지 않았다. 유지된 대상의 version·호환성 검사는 계속 수행한다.
Registry는 변경 중인 작업 트리에서 발행했음을 명시적인 `worktree:<HEAD>:<content digest>` provenance로 기록했다.
기존 artifact directory를 수정하지 않고 새 version을 만들고 checksum 검증 후 active pointer를 교체했다.
발행 작업만 일회성 쓰기 mount를 사용했으며 운영 API의 artifact mount는 계속 읽기 전용이다.

## 물품 Ontology Draft

인증된 Admin API를 통해 `goods 0.1.0` Draft를 생성했다.
Object 3개·Relationship 4개이며 구조·Binding 영향 검사는 `valid`, 충돌 0개다.
Draft ID는 `2c1376f8-18f5-4c23-87f1-2c2bd27d050c`이다.
변경 주체는 인증 principal `system:admin`으로 기록했다. 검토·승인·게시를 수행하지 않았다.
기존 Published `teoria 0.1.4`와 과거 deprecated version은 보존했다.

## 실제 요청과 준비 상태

| 검사 | 결과 |
|---|---|
| nginx·Runtime·Admin health와 UI 공개 경로 | HTTP 200 |
| 인증된 Runtime version | `2026.10.25.1` |
| Runtime Capability discovery | 빈 목록 |
| 기존 `get_bid_notice` 실행 요청 | HTTP 404 `unknown_capability` |
| 기존 계약금액 Context 계획 | HTTP 422 `context_not_resolved` |
| 인증 없는 Runtime·Admin session 요청 | HTTP 401 |
| Admin overview | Source·Mapping·Capability·Runtime Object 각 0개 |
| OpenMetadata 연결 | enabled·available |
| MCP 실제 STDIO 초기화·tools/list | 성공, Tool 0개 |
| Data DB schema·Runtime SELECT·Pipeline INSERT 권한 | 확인 |
| 모델 CLI 인증·합성 추론 | 성공 |

새 규격서 상태·문서·산출물 참조 테이블 3개의 OpenMetadata 자산을 동기화 후 각각 HTTP 200으로 확인했다.
MCP는 시작할 때 Tool 목록을 고정하므로 외부 클라이언트가 따로 실행하는 Gateway는 재연결해야 한다.
이전 도구 이름으로 Runtime을 호출해도 은퇴한 기능은 실행되지 않는다.

## 이미지와 복구

| 서비스 | 배포 image ID 앞 12자리 | 이전 image ID 앞 12자리 |
|---|---|---|
| Admin·진단 Worker | `1677ddd3d540` | `1a54547a1809` |
| Runtime | `1bf96656eda7` | `2aad7a359f22` |
| 규격서 Worker | `f4539d262872` | `a5505207fc98` |
| Metadata Worker | `753efe503502` | `3dae4b209fb4` |
| Admin UI | `22c0b20978fc` | `0773ca62d591` |

기존 DB 컨테이너·데이터·볼륨·checkpoint·이미지·artifact는 삭제하지 않았다.
복구 시 이전 이미지와 해당 bundle을 함께 선택한다. 새 코드에 과거 조달 bundle만 적재하지 않는다.
과거 수집의 일시정지 상태는 복구 과정에서도 유지한다. schema는 과거 SQL로 덮어쓰지 않는다.

## 검증 범위와 남은 기능

Platform 전체 검사는 218 passed·25 skipped, UI는 45 passed다.
이미지 빌드·실제 기동·인증·정책 경계·등록·artifact 전환을 확인했다.
전체 Pipeline 검사는 실제 배포 이미지의 소스 snapshot에서 175 passed·7 skipped다.
운영 컨테이너의 설치된 패키지를 별도 임시 디렉터리로 복사하고 pytest의 pythonpath를 그 snapshot으로 고정했다.
Compose 설정 회귀는 5개, 문서 검사기 회귀는 7개가 통과했다.
검증 시점에 동시에 진행 중인 추출 평가의 baseline 작업 트리에는 단위 보완·중복 병합을 끈 실험 변경이 있어
그 상태의 회귀 실패를 배포 이미지의 동작으로 해석하지 않는다. 평가 코드는 변경하지 않았다.

물품 Ontology 게시, 추출 결과→개념 Suggestion·검토·승인 연결,
물품 데이터 Source·Mapping·검색·비교 Capability·AI query handler는 후속 구현이다.
이번 합성 추론 성공을 실제 규격서의 전체 추출·표준 적용 품질이나 운영 문서 처리 완료로 기록하지 않는다.
현재 실행 절차는 [Compose](../deployment/compose.md), [Prefect](../pipelines/prefect.md),
[시작 안내](../platform-guide.md)를 따른다.

## 문서 정리

문서 목차·Compose·Prefect·Platform/Pipelines 개발·Context·Data DB 안내를 현재 활성 범위로 다시 작성했다.
Ontology·Runtime·Admin UI·MCP·환경 설정·로드맵도 실제 배포 상태와 맞췄다.
이전 조달·법령·입찰체크 문서는 원래 URL에서 과거 구현 자료로 표시하고 현재 작업 안내와 구분했다.
기존 검증 기록의 당시 관찰은 덮어쓰지 않았다.
