# 비동기 배포와 수집 상태 검증: 2026-10-16

현재 로컬 `teoria` Compose 프로젝트의 배포와 실제 수집을 확인한 기록이다.
문서 취합 기준일은 2026-10-16이며 수집 수치는 **2026-10-16 15:46 KST / 06:46 UTC**
관찰값이다. EC2 K3s 실배포·GitHub CD 성공이나 전체 데이터의 완전성을 뜻하지 않는다.

## 반영한 실행 기준

- Platform API → Service → Repository → PostgreSQL, Runtime reader와 Pipeline DB Task를
  native async로 연결했다. 계산·정규화·검증은 일반 함수로 유지한다.
- Platform·Pipeline DB 연결 상한은 각각 기본 10이며 event loop별·접속 URL별로 적용한다.
  성공 시 commit, 예외·취소 시 rollback 후 연결을 닫는다.
- 승인·선점·효과 기록·게시·정규 적재와 checkpoint의 순서를 보존한다.
- 첨부파일 다운로드·문서 추출·입찰요건 판단은 archive 상태를 유지한다.

## 배포와 실제 검증

| 확인 | 결과 |
|---|---|
| 배포한 서비스 | Runtime·Admin·Policy Control Plane·자산 진단 Worker·수집 Worker·Metadata Worker 6개 |
| 배포 소스 일치 | Platform 서비스별 Python 233개, Pipeline Worker별 76개 파일 대조 일치 |
| Prefect 등록 | 수집·Metadata 등록 서비스 모두 exit code 0 |
| 기존 수집 보존 | 새 제출을 일시정지하고 실행 중인 2개가 Completed인 것을 확인한 뒤 Worker 교체 |
| API | 인증된 조회 HTTP 200, 미인증 HTTP 401, 없는 Ontology version HTTP 404 |
| 실제 Runtime 조회 | 기관 검색·분류 목록·공고 검색·기관 조달 프로필·조달 활동 검색 정상 |
| 내부 분류 보강 | 실제 read-only Data DB에서 누락 분류 계층 조회 경로 실행 |
| Prefect 검증 Flow | 6개 Task Completed, 의도한 1회 실패 후 2번째 시도 성공 |
| DB 저장 | 실행 감사 `completed`, checkpoint 저장과 재시도 전 미갱신 확인 |
| 정책 감사 | 새 OPA decision·status의 Application DB 저장 확인 |
| 최종 프로세스 상태 | 대상 서비스 실행·재시작 0회, API health 정상, 두 Worker ONLINE |
| 최종 로그 | 미대기 코루틴·잘못된 `asyncio.run` 경고 없음 |

배포 검증에서 동기 등록 함수를 `asyncio.run()`으로 감싼 CLI 호출과 분류 보강 SQL의
`await` 누락을 발견해 수정·재빌드·재배포했다. 관련 회귀 테스트는 시장 분석 64개,
등록·entrypoint 16개가 통과했다. 실제 DB 통합·승인 동시성·게시 rollback·취소 검증은
전환 과정에서 별도로 수행했다.

Runtime artifact는 기존 `2026.10.16.90`을 사용한다. 이전·새 이미지가 같은
checksum 검증 artifact를 읽는 것을 확인했으며 코드를 배포하기 위해 새 artifact를
발행하지 않았다. 저장소 계약 46개 중 Runtime 공개 discovery는 30개다.

검증 Flow는 외부 Provider를 호출하지 않고 빈 정규 배치와 별도 검증용 실행 ID를
사용했다. 검증 DB 행·Flow·Deployment·marker는 완료 후 정리했고 work pool의
일시정지 상태를 원래 값으로 복구했다. 실제 Provider 수집은 아래 별도 관찰로 확인했다.

## 수집 관찰

수집·Metadata pool은 일시정지되지 않았고 각각 ONLINE Worker를 확인했다.
최근 24시간 Prefect의 Failed·Crashed 실행은 0건이며 10분 이상 늦은 Scheduled 실행은
0건이었다. 조회 시점에는 과거 개찰 참여업체 보강 1개가 실행 중이었다.

| 수집 | 마지막 DB 완료 시각 KST | 최신 checkpoint |
|---|---|---|
| 입찰공고 | 15:17:35 | 2026-10-16 |
| 계약 증분 | 12:05:51 | 2026-10-16 |
| 낙찰 증분 | 12:31:33 | 2026-10-16 |
| 최신 개찰 보강 | 15:45:47 | 공고별 보강 큐로 추적 |

계약·낙찰은 4시간 주기로 실행하므로 마지막 성공 시각을 현재 예약 간격과 비교한다.
계약·낙찰의 위 마지막 Provider 수집은 이번 Worker 교체 이전 실행이다.

새 Worker 배포 후 06:00 UTC부터 관찰 시점까지 공고 1,002건, 개찰 참여업체 6,111건,
공고 결과 561건을 처리·갱신했다. 개찰 참여업체는 최신 1,500건·과거 4,048건·
재시도 563건의 합계다. 이 수치는 실행별 처리 건수이며 신규 고유 레코드 수가 아니다.

## 남아 있는 데이터 결손

| 항목 | 관찰값·의미 |
|---|---|
| 개찰 보강 pending | 633,194건: 과거 607,818 + 증분 25,376 |
| 개찰 보강 retry_wait | 199,619건: 과거 197,384 + 증분 2,235 |
| 개찰 보강 processing | 180건 |
| 개찰 보강 partial_completed | 353건: 과거 3 + 증분 350 |
| 계약 Backfill 미해결 구간 | 1개, 재시도 15회 상한 도달 |

최근 오류 기록에는 `opening_lookup_failed`, `opening_response_incomplete`가 있다.
보강 큐의 상태와 오류는 Flow가 Completed여도 남을 수 있다. `partial_completed`는
전체 성공이 아니며 Runtime 수집 상태에서 `failed`로 노출한다. 근거를 확인하지 않고
완료로 바꾸거나 checkpoint를 임의로 앞당기지 않는다.

현재 판단은 **수집·적재가 실제로 진행 중이며 미처리·재시도 잔량은 남아 있다**는 것이다.
누적 건수를 전체 기간·모든 공고의 완전 수집으로 해석하지 않는다.

## 현재 절차와 후속 확인

재배포는 [Compose](../../../docs/deployment/compose.md), 실행·지연·큐 점검은
[Prefect 운영](../../../docs/pipelines/prefect.md), 원본 보존과 감사 건수는
[Data DB](../../../docs/pipelines/database.md)를 따른다. 로컬 검증에서 확인한 것과 별개로
EC2 K3s 실배포·자원 포화·장기간 처리량·모델 품질 평가는 추가 확인 대상이다.
