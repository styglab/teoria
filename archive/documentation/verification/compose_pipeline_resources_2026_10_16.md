# Compose 수집 Worker 재배포 검증: 2026-10-16

로컬 `teoria` Compose 프로젝트에 공통 Prefect 등록·Queue 정책과 수집 Worker 자원
상한을 실제 반영했다. 기준은 당시 로컬 작업 트리와 빌드한 이미지이며 GitHub CD나
EC2 K3s 배포를 검증한 결과는 아니다.

## 반영과 기존 작업 보존

- 수집·Metadata work pool의 새 실행 제출을 일시정지했다.
- 실행 중이던 공고 수집·최신 개찰 보강·과거 개찰 보강 3개가 모두 Completed가 된 뒤 교체했다.
  강제 취소하거나 실행 중인 프로세스를 종료하지 않았다.
- `prefect-deploy`, `prefect-metadata-deploy`는 새 등록 명령으로 실행해 exit code 0을 확인했다.
- `prefect-worker`, `prefect-metadata-worker`만 새 이미지로 재생성했다.
- 나머지 25개 컨테이너의 ID·이미지·볼륨 연결이 재배포 전과 동일했다.

## 실제 확인 결과

| 확인 | 결과 |
|---|---|
| 수집 Worker CPU | cgroup quota 400000 / period 100000 = 4코어 |
| 수집 Worker 메모리 | cgroup limit 8589934592 bytes = 8GiB |
| 수집 pool 전체 동시 실행 상한 | 2 |
| `latest` Queue | 우선순위 1, 동시 실행 상한 2 |
| `backfill` Queue | 우선순위 10, 동시 실행 상한 1 |
| Metadata pool | 동시 실행 상한 1 |
| 현재 정의의 Deployment 22개 | pool·Queue 배치 일치 |
| 새 Worker 실행 검증 | 임시 Flow의 첫 실행을 의도적으로 실패시킨 뒤 두 번째 시도에 Completed 확인 |
| UI·nginx health·Admin 인증 session·Runtime health | 모두 HTTP 200 |

검증 Flow는 Provider API를 호출하거나 Data DB를 변경하지 않았다. 완료 후 임시 Flow,
Deployment, 실행 기록과 검증 파일을 삭제했다. Metadata Worker에 OpenMetadata ingestion
라이브러리가 포함되지 않은 것도 확인했다.

기존 월간 업종 수집 `pps-industry-monthly`는 현재 주간 배포와 중복되므로 예약을
일시정지하고 이력을 보존했다. 현재 수집 배포가 사용하지 않는 `default` Queue도
일시정지했다. 두 work pool은 재배포 전과 같은 실행 가능 상태로 복원했고 두 새 Worker는
Running·재시작 0회 상태를 확인했다.

## 범위와 한계

이는 자원 상한 적용·등록 정책·실제 Process Worker 실행·재시도 검증이다. CPU·메모리를
한도까지 소모시키는 부하 시험이나 장기간 처리량 측정은 수행하지 않았다.
EC2 K3s 실배포·노드 장애 복구 검증도 이 결과에 포함하지 않는다.
현재 설정과 재배포 순서는 [Compose 배포](../../../docs/deployment/compose.md), Queue 정책은
[Prefect 운영](../../../docs/pipelines/prefect.md)을 따른다.
