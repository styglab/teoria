# 규격서 전체 흐름 검증 — 2026-11-08

새 공개 원본을 확보하고 격리 환경에서 문서 등록·추출·처리 기준 승인·재처리·결과 조회를 확인했다.
빈 표준 승인 결함을 재현해 차단했다. 독립 추출 정확도 승인, Published Ontology 의미 연결 승인, 운영 배포는 수행하지 않았다.

## 입력과 평가 범위

- 대학·공공기관 공개 PDF 원본 11개, 1,758,208바이트와 원본 URL·SHA-256 provenance를 보존했다.
- 모델 실행 전에 10개를 고정했다. 공통 Commodity Description 양식 3개는 같은 그룹으로 묶어 총 8그룹을 개발 4개·검증 6개로 분할했다. 기존 세척기 문서 1개는 별도 회귀 자료다.
- 34쪽의 여러 물품 문서는 최초 실행 범위를 제한하기 위해 고정 전에 제외했고 원본은 보존했다. 신규 대상은 모두 PDF이며 다른 형식으로 일반화하지 않는다.
- 분류는 null을 유지했다. 파일명·품목 설명으로 서버 분류를 추정하지 않았다. 새 사례는 AI 작성 silver이며 사람 검토 정답이 아니다.
- `platform_workflow_20261108_01` baseline은 개발 묶음 실행 중 중단했다. 승인 제어 결함을 수정 대상으로 선택했으며 추출기 수정·candidate 비교·독립 정확도 승인은 하지 않았다. validation 결과를 수정 선택에 사용하지 않았다.
- 모델은 `gpt-6.1-sol`, 파서는 `/tmp/teoria_parser_validation/bin/python`, 실행 동시성 2·모델 동시성 2였다. 원본별 전체 재현율이나 조건 의미 동등성을 측정하지 않았다.

| 원본 | SHA-256 앞 12자리 | 공개 원문 |
|---|---|---|
| bioreactor.pdf | `eaad6e7afc08` | [원문](https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do?bidPbancNo=R25BK00866684&bidPbancOrd=000&fileSeq=2&fileType=) |
| thermal_camera.pdf | `72484c6309aa` | [원문](https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do?bidPbancNo=R26BK01526280&bidPbancOrd=000&fileSeq=2&fileType=&prcmBsneSeCd=01) |
| raman_detector.pdf | `beac84ca54ce` | [원문](https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do?bidPbancNo=R26BK01411202&bidPbancOrd=000&fileSeq=3&fileType=&prcmBsneSeCd=01) |
| vacuum_system.pdf | `e54683a4c617` | [원문](https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do?bidPbancNo=R25BK01037362&bidPbancOrd=000&fileSeq=2&fileType=) |
| centrifuge.pdf | `0a90df58dc0d` | [원문](https://www.syu.ac.kr/wp-admin/admin-ajax.php?action=file_download_id&o_name=%EA%B7%9C%EA%B2%A9%EC%84%9C-%EB%8C%80%EC%9A%A9%EB%9F%89%EC%9B%90%EC%8B%AC%EB%B6%84%EB%A6%AC%EA%B8%B0-1.pdf&t_id=112089) |
| climate_control.pdf | `8edd110c1db2` | [원문](https://ibsi.kiu.ac.kr/bbs/bbs_download.php?download=h&mv_data=aWR4PTEwMDc0OCZzdGFydFBhZ2U9NDAmbGlzdE5vPTMwNSZ0YWJsZT1jc19iYnNfZGF0YSZuYXZfY29kZT1raXUxNTU2ODQ4MjkzJnNpdGVfY29kZT1raXUmY29kZT1vdXRiaWQmc2VhcmNoX2l0ZW09JnNlYXJjaF9vcmRlcj0mb3JkZXJfbGlzdD0mbGlzdF9zY2FsZT0%3D%7C%7C&seq=1) |
| freezer_room.pdf | `c7152e96aa41` | [원문](https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do?bidPbancNo=R25BK01030221&bidPbancOrd=000&fileSeq=2&fileType=) |
| deep_freezer.pdf | `876ee8de58c4` | [원문](https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do?bidPbancNo=R25BK01051370&bidPbancOrd=000&fileSeq=2&fileType=) |
| glovebox.pdf | `d7ec91dd5628` | [원문](https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do?bidPbancNo=R25BK00908995&bidPbancOrd=000&fileSeq=2&fileType=) |
| operating_microscope.pdf | `1e7e4e8b0898` | [원문](https://www.hallym.or.kr/chpfile/bid/20210531_F_2_660.pdf) |
| teaching_equipment.pdf | `03663a727b4d` | [원문](https://www.yeonsung.ac.kr/bbs/ko/100/58195/download.do) |

## 실제 통합 검증

전용 PostgreSQL의 Application/Data DB, 별도 MinIO bucket, 실제 Prefect Task와 기존 `teoria-pipelines specification run` CLI를 사용했다. 자동 사전·의미 승인은 끄고 추출 checkpoint 재사용도 끈 상태다. 운영 DB·원본·게시 의미는 변경하지 않았다.
원본은 마약류 탐지장비 규격서이며 SHA-256은 `beac84ca54ce983c0c76c9148e6a1cb56cc4232b9f79023f6d3129546f4ea64e`다.

| 실행 ID | 상태 | 추출 속성 | 적용 | 보류 | checksum 확인 산출물 |
|---|---|---:|---:|---:|---:|
| `validation_raman_management_20261108` | partial | 21 | 0 | 21 | 17 |
| `validation_raman_reprocess_20261108` | partial | 21 | 0 | 21 | 12 |
| `validation_raman_literal_management_20261108` | partial | 21 | 1 | 20 | 17 |
| `validation_raman_literal_reprocess_20261108` | partial | 21 | 1 | 20 | 12 |

- 4회 모두 새 추출을 실행했고 원본 해시는 유지됐다. 문서 catalog 1개·실행 이력 4건과 산출물 58개의 실제 저장 본문 checksum을 확인했다.
- 원문 보존 규칙은 레이저 파장 표현 `785 nm` 1건에만 적용했다. `source_literal` 결과이며 수치 비교는 금지된다. Business Ontology 개념이나 전체 물품 적합성 결과가 아니다.
- 승인자는 인증된 `validation:reviewer`로 기록됐다. 이는 자동 통합 검사 계정이며 사람의 의미 검토를 대신하지 않는다.
- 원래 규칙 0개인 기준도 승인·재처리됐으며 21개가 전부 보류됐다. 수정 뒤 readiness는 ready=false, 새 승인은 HTTP 409, 과거에 승인된 빈 기준의 CLI 실행 확인도 거절됐다.
- 규칙 1개 기준은 ready=true이며 수정 뒤 실제 API 승인과 CLI 승인 참조 검사를 통과했다.
- 수정 전 실제 staging 웹에서 결과·원문 근거·승인/재처리 연결을 HTTP mock 없이 확인했다. 수정 뒤에는 실제 앱의 ASGI HTTP 처리와 동일 DB·S3로 승인 차단을 검증했다. 수정 뒤 UI는 별도 컴포넌트·브라우저 검사 범위다.
- 검증 DB에 Published Ontology가 없어 Ontology 기반 의미 연결 승인은 미실행했다. 전체 의미 업무의 완료로 해석하지 않는다.

## 수정

- 처리 기준 승인 화면에서 실제 정의·적용 규칙 수를 확인하고 빈 기준은 이유와 함께 비활성화한다.
- Admin 승인·실행 정책과 CLI/Worker 시작 경계에서 빈 규칙, 미승인 상태, 고정 참조·분류·checksum 불일치를 거절한다. 실행 상태 등록과 원본 읽기보다 먼저 확인한다.
- 수정 코드 revision: `6a102bee040d6e7300cf3214923d8b8832c488fe40cdc5031375723efc9bb49b`.

## 검증·정리

- 백엔드·문서 1,184 passed / 89 skipped, 프런트엔드 148 passed, 브라우저 4 passed, 프런트엔드 build·Compose config·Pipeline 계약/연동 검증이 통과했다. 기존 archive 문서 링크 오류 24건은 유지된다.
- 평가 CLI abort 재시도로 작업공간 24,526,682바이트를 제거했다. 평가 상태의 정리 대기는 0이며 원본과 사용 이력은 유지한다.
- 전용 DB 컨테이너·S3 컨테이너(객체 66개·2,175,594바이트)와 임시 Docker network를 제거했다. 작업용 로컬 산출물 7,618,680바이트와 이번 브라우저 캡처도 제거했다. 입력 원본·최소 회귀 검사·코드·이력·압축된 검증 요약은 보존한다.
- 임시 API·웹·Prefect 포트 8253·18111·18112·18113은 닫혔다. DB/S3는 host port를 공개하지 않았다.
- 사람이 검토한 정답, 게시 Ontology·프로파일로의 의미 승인, 운영 배포와 실제 SSO는 후속 검증이다.

## 자동 승인·적용 배포 후속 검증

2026-11-08 09:21 UTC에 현재 Compose 전체 구성에 변경 이미지를 반영했다. EC2 K3s 배포 검증은 아니다.
원문 근거·대상·역할·범위가 확인된 값은 원문 보존용 `source_literal` 규칙으로 자동 적용하고,
사용 가능한 규칙과 실행 당시 사전 버전을 인증된 Admin API에서 자동 승인·고정한다.
새 업무 의미 작성·Ontology 게시는 이 정책의 대상이 아니다.

- 백엔드·문서 1,197 passed / 90 skipped, 프런트엔드 149 passed, Compose 검사 20 passed.
- 격리 PostgreSQL의 실제 API·SQL·파일 연동 3건에서 자동 승인, 인증 주체 기록, 중복 방지와 실행 요약 저장을 확인했다. 추출 입력은 fixture이며 실제 모델 품질 검사와 구분한다.
- 실제 배포 화면에서 HTTP mock 없이 관리자 인증, 처리 기준 조회, 자동 적용 기본 선택·활성화, 브라우저 오류 0건을 확인했다. 규격서 Prefect 배포 3개가 등록되고 pause가 해제됐다. Worker 이미지의 자동 승인 Task도 확인했다.
- 교체한 기존 컨테이너는 제거됐고 사용하지 않는 Teoria 이미지는 배포 절차에서 정리했다. 정지된 기존 Teoria 서비스 컨테이너는 0개다. 데이터 볼륨·원본·DB 백업과 배포 도구가 보존하는 복구 이미지는 유지했다.
- 배포 전 DB 백업은 `backups/teoria/20261108T090559Z`에 보존했다. 백업 스크립트에서 jobs 프로필을 포함하도록 고쳤다.
- 기존 Prefect Redis의 AOF 손상으로 유지보수가 실패했다. 원본 29,020,160바이트에서 마지막 미완성 475바이트를 제외한 29,019,685바이트를 복사본에서 검증한 뒤 복구했다. 복구 전 파일은 같은 백업에 보존했다. healthcheck는 실제 PONG을 요구하며 복구 후 재시작 0회·healthy를 확인했다.
- 배포 확인용 임시 네트워크 연결과 Redis 복구용 복사 볼륨은 제거했다. 공개 포트는 추가하지 않았다.

배포 증거는 `deploy/compose/.state/teoria/automatic_approval_rollout.json`과
`automatic_approval_live_verification.json`에 압축해 기록한다. 실제 운영 문서의 자동 승인 완료는
위 fixture 연동 검사나 화면 기본값 확인만으로 주장하지 않는다.

## 10개 문서 재평가와 숫자 근거 검사 보강

10개 원본과 기존 회귀 문서 1개를 원래 사례·분할·모델·파서 설정으로 재실행했다.
기존 노출 이력을 유지한 `quality_assessment`이며 새 독립 검증이나 개선 승인으로 간주하지 않는다.
전체 평가는 **미완료**다. 검증용 6개 묶음에서 실행기가 종료됐고 회귀 문서는 실행하지 못했다.

| 실행 | 개발용 4개에서 관측한 고정 사례 | 실패·부분 완료 | 이후 결과 |
|---|---|---|---|
| `platform_quality_assessment_20261108_02` | 엔티티 6/6, 요구조건 4/4 | 실패 0, partial 3 | 검증용 묶음 실행기 오류. 구형 정리 정책으로 상세 예외와 중간 점수 파일이 소실돼 관측 요약만 보존 |
| `platform_quality_assessment_20261108_03` | 엔티티 5/6, 요구조건 4/4 | 실패 0, partial 3 | `persist_extraction → validate_checkpoint`의 숫자 근거 검사에서 ValueError·종료 코드 1. 점수와 코드 위치는 누적 state에 보존 |

미일치 사례는 `glovebox`의 `entity:0`이다. 사례는 AI 작성 silver이며 이 비율을 문서 전체 정확도나
원문 전체 재현율로 해석하지 않는다. 위 두 실행은 `inconclusive`다. 개별 결과를 측정하지 못한
검증용 문서 6개를 모두 실패 문서로 판정한 것도 아니다.

종료 위치는 `source_numeric_literal_mismatch`에 해당한다. 실제 실패 속성 ID와 값은 과거
예외에 포함되지 않아 확인하지 못했다. 별도로 원본 `bioreactor.pdf` 2페이지의
`11. 프로그램: 100개 저장`을 대조해, 수량 검사가 `100`의 일부인 `10`이나 `1`도
원문에 존재한다고 통과시키는 경로를 재현했다. 이 경로가 실제 실패 행이었다고 단정하지 않는다.

- 수량 목록의 앞단 검사와 자동 채택의 숫자 근거 검사를 완전한 숫자 토큰 기준으로 일치시켰다. 마지막 검사는 유지한다. 앞단에서 거절되면 기존 재판정·문서별 실패 처리 경로를 사용한다.
- 평가 실행기는 완료한 development/regression 점수와 종료 코드·예외 유형·코드 위치를 보존한다. 숫자 검사 예외에는 문서·속성·노드 ID를 추가했고, 실행기 오류 요약은 이 ID와 고정 오류 코드만 수집한다. 원문 값·인용문·모델 응답·전체 로그는 보존하지 않는다.
- 백엔드·문서 1,201 passed / 90 skipped, 평가·숫자 근거의 최종 표적 검사 191 passed / 1 skipped. 이들은 전체 문서의 실제 모델 재평가를 대신하지 않는다.
- 2026-11-08 10:56 UTC에 규격서 pool만 일시정지하고 활성 실행 0을 확인한 뒤 Worker를 교체했다. 이전 Worker 컨테이너는 제거됐고 기존 pool pause 상태를 복원했다. API·웹·DB 컨테이너는 이 교체에서 재시작하지 않았다.
- 실제 Worker에서 완전한 `100`의 허용, 일부 `10`의 수량·자동 채택 거절, 자동 승인 Task 존재를 확인했다. 소스와 배포 Worker의 processor revision은 모두 `65ee612fe974ef0c4891dbcc6c4f76b60010ab414ecd50e59854a72cdb609a9c`다.
- 보강 뒤 전체 실제 모델 재평가는 미실행이다. [평가 스킬](../../.agents/skills/improve_specification_processing/SKILL.md)의 세 사이클 범위에서 추가 전체 반복은 하지 않았다. 다음 검증은 실제 실패 속성의 원문 대조와 전체 고정 표본 재평가다.
- 두 재평가의 작업공간 71,020,138바이트를 제거했다. 정리 대기와 활성 평가 controller는 0이다. 입력 원본 11개·해시·고정 사례·사용 이력·압축된 점수와 진단은 보존한다.
- 별도 작업용 manifest·검증 스크립트·빌드/검사 로그 25개·166,653바이트도 제거했다. 배포 증거 요약과 운영 DB·Redis 백업은 보존한다.

최종 배포 상태는 실행 중 22개, unhealthy 0개, 종료된 기존 서비스 컨테이너 0개다.
공개 포트는 추가하지 않았다. Worker 교체 증거는
`deploy/compose/.state/teoria/specification_worker_numeric_guard_rollout.json`에 기록했다.

후속 이미지 정리에서는 사용자 요청에 따라 직전 이미지의 자동 보존을 해제하고, 남아 있던 이전
Worker `<none>` 이미지를 삭제했다. 현재 dangling 이미지는 0개이며 서비스 22개는 정상이다.
배포 정리 로직도 과거 이미지를 삭제하도록 수정했고 관련 검사 14건이 통과했다.

## 오류 격리·평가 재개·자동 승인 품질 조건 후속 검증

새 추출 결과의 원문 검증 실패를 속성 또는 문서 단위로 격리하고, 실패·검증 보류 문서만
재추출하는 경로를 추가했다. 원본 식별·해시 불일치는 실행 전체를 중단한다. 검증 재현은
저장된 원문·속성과 현재 검증기를 사용하며 모델 호출이나 결과 변경을 하지 않는다.
평가 재개는 동일 원본·사례·분할·processor·grader·파서·실행 설정과 점수 checksum을 요구한다.
자동 승인에는 원문 검증 오류·문서 실패 비율·적용 보류 비율·동일 입력 속성 수 변화 한도를 적용한다.

별도 PostgreSQL의 Application/Data DB와 소유한 파일 산출물 경로에서 실제 모델·Prefect·Admin API로
같은 마약류 탐지장비 PDF를 두 번 처리했다. 원본 SHA-256은 위 통합 검증과 같다.
모델 `gpt-6.1-sol`, 파서 0.9.16, 동시성 2이며 단계 checkpoint 재사용과 사전/의미 자동 승인은 껐다.

| 실행 ID | 상태 | 추출 속성 | 적용 | 보류 | checksum 확인 산출물 |
|---|---|---:|---:|---:|---:|
| `reliability_raman_management_20261108` | partial | 21 | 18 | 3 | 16 |
| `reliability_raman_reprocess_20261108` | partial | 21 | 11 | 10 | 11 |

첫 실행은 실제 사용 가능한 원문 보존 규칙을 자동 승인했고, 두 번째는 승인된 동일 고정
표준·사전 참조로 원본을 새로 추출했다. 승인 주체는 인증된 `validation:reliability-worker`다.
실제 native API에서 catalog 1개·처리 이력 2건·문서 결과와 산출물 27개 checksum을 확인했다.
실제 staging 웹에서 결과의 물품·속성·원문 근거, 자동 승인 안내·동일 원본 재처리 연결을
HTTP mock 없이 확인했으며 브라우저 실행 오류는 0건이다. 웹에서 새 Flow를 제출한 검사는 아니다.
두 실행은 모두 partial이며 새 추출의 속성 귀속·적용 수가 달라졌다. 고정 표준을 사용한다고
모델의 새 추출까지 동일해지는 것은 아니다. 전체 의미 정확도나 Published Ontology 검증은 아니다.

기능·workflow 검사 667 passed / 2 skipped, 프런트엔드 152 passed와 build가 통과했다.
후속 10개 고정 표본 평가 및 운영 반영 상태는 아래에 별도로 기록한다.

`reliability_assessment_20261108_01`은 2026-11-08 15:34 UTC에 `assessment_recorded`로
마무리했다. 고정 표본 10개와 회귀 1개 모두 실행했고 전체 백엔드 검사 종료 코드는 0이다.

| 구분 | 문서 | 실패 | 부분 완료 | 엔티티 고정 사례 | 요구조건 고정 사례 | 격리 속성 |
|---|---:|---:|---:|---:|---:|---:|
| 개발 | 4 | 0 | 4 | 4/6 | 2/4 | 0 |
| 검증 | 6 | 0 | 5 | 8/8 | 3/8 | 1 |
| 별도 회귀 | 1 | 0 | 1 | 3/4 | 사례 없음 | 0 |

잘못된 속성 1건을 격리하면서 전체 실행을 마쳤다. 다만 고정 표본의 요구조건 일치는 5/12로,
전체 추출 품질이 충분하다는 판정은 하지 않는다. 사례는 AI 작성 silver이며 전체 재현율이나
사람 검토 정답 점수가 아니다. 개선 전후 비교가 없는 현재 품질 관측이며 개선 승인도 아니다.
평가 작업공간 47,853,373바이트를 제거했고 cleanup=complete다. 입력 원본·고정 사례·노출 이력과
문서별 점수·checksum 요약은 보존했다. 이번 신뢰성 보강의 새 이미지는 빌드했으나 운영에는
아직 반영하지 않았다. 다음 품질 작업은 개발 문서 원문에서 확인된 대상·요구조건 누락의 원인을
대조하는 것이며, 공개한 검증 점수를 새 독립 검증으로 재사용하지 않는다.

## 2026-11-09 요구조건 미일치 원인 대조

원문 `vacuum_system.pdf`의 구매 범위에는 `고효율 진공펌프`, 기술 표에는 `진공펌프`가
같은 구매 대상으로 적혀 있다. 실제 추출에서도 root `고효율 진공펌프`에 600 kW와 425 kW가
연결되고 원문 표의 `진공펌프`가 별칭으로 남았다. 기존 고정 사례에는 이 대응이 없어 두 값을
누락으로 계산할 수 있었다. 앞선 5/12는 엄격한 고정 사례 일치 수치이며 실제 누락 7건이
확정됐다는 뜻은 아니다. 특히 진공펌프 두 건을 실제 누락이라고 해석한 설명을 정정한다.

- `requirement_repair_20261109_01`: 이 기준 불일치를 발견해 비교를 중단했다. 추출 개선 판정은 하지 않았고 작업공간 12,755,239바이트를 제거했다.
- 원문으로 확인한 세 명칭만 `vacuum_power_cases.json`에 명시했다. 유사 문자열 허용이나 대상 ID 병합은 추가하지 않았다. 값·단위·연산·다중 대상 모호성 거절을 포함한 회귀 검사 7건이 통과했다.
- `requirement_name_calibration_20261109_02`: 동일 원본·모델·파서·설정으로 별도 보정 실행했다. 엔티티 1/1, 전력 요구조건 2/2, 실패 문서 0, partial 1, 격리 속성 0이다. 전체 백엔드 검사 종료 코드 0, `baseline_recorded`이며 추출 개선 점수나 새 독립 검증이 아니다. 작업공간 6,811,135바이트를 제거했고 cleanup=complete다.
- 원본 해시·노출 이력과 이전 점수는 보존했다. 새 회귀 사례는 silver이며 사람이 검토한 정답으로 승격하지 않았다.

전날 신뢰성 통합 검증의 별도 staging API와 전용 PostgreSQL 컨테이너를 종료·제거했다.
소유 표시를 확인한 파일 산출물 1,004,639바이트, 작업용 manifest·로그·Prefect 상태
6,343,140바이트와 별도 검사 로그 11,556바이트를 제거했다. 위 압축된 통합 결과·원본·운영 DB·
백업은 보존했다. 이 정리는 실제 업무 실행의 산출물 보존 정책을 바꾸지 않는다.

### 단위 인식 개선안과 회귀 판정

`requirement_repair_20261109_03`은 기존 노출 원본 네 개(원심분리기·초저온 냉동고·냉동실·
열화상카메라)를 development, 마약류 탐지장비를 regression으로 고정해 실제 모델로 전후 실행했다.
새 독립 표본이 아니며 원문·사례·모델·파서·실행 설정·채점기를 유지했다.

| 구분 | 수정 전 | 수정 후 |
|---|---:|---:|
| 개발 엔티티 사례 | 5/5 | 5/5 |
| 개발 요구조건 사례 | 1/5 | 1/5 |
| 개발 실패 / 부분 완료 문서 | 0 / 4 | 0 / 3 |
| 개발 격리 속성 | 1 | 1 |
| 별도 회귀 요구조건 사례 | 2/2 | 2/2 |
| 별도 회귀 부분 완료 문서 | 0 | 1 |
| 별도 회귀 미귀속 속성 | 0 | 1 |

수정 전에도 다섯 수치 자체는 추출돼 있었다. 원심분리기의 22,000 RPM·230 Kg은 본체에,
열화상카메라의 195 g은 `열화상카메라(렌즈 포함)`에 연결됐다. 냉동실 고내등 50 W의
인용은 같은 원문 `LED(50W)` 중 `50W`로 좁혀져 있었고 기존 사례는 전체 구절을 요구했다.
이것은 미일치 원인 분석이며, 본체/전체 장비의 정답 귀속이나 대체 이름·인용 라벨의 검증
완료를 뜻하지 않는다. 진행 중인 비교의 라벨이나 채점기는 변경하지 않았다.

`ℓ`, `Kg`, `RPM/rpm`을 단위 정규화기가 인식하지 못하는 별도 코드 경로를 재현했다.
수치 옆의 명확한 단위만 복원하도록 기존 정책을 유지한 소규모 개선안을 비교했다.
실제 중간 그래프에서 해당 단위의 관찰 6개가 모두 unmapped에서 normalized로 바뀌었지만,
이는 전체 추출 정확도 개선 점수가 아니다. 별도 원문 표기 표적 검사는 수정 전 양성 3건 실패·
음성 5건 통과, 수정 후 확장한 양성 4건·음성 5건 모두 통과했다.

최종 판정은 **rejected**다. 개발 부분 완료는 줄었지만 별도 회귀의 partial과 미귀속 속성이
증가했다. 코드 변경 때문인지 새 모델 추론의 변동인지 이 비교로 분리하지 못했다.
단위 인식 코드 변경과 그 구현용 테스트를 되돌렸다. 원문 기반 최소 입력
[source_unit_spellings.json](../../backend/tests/features/specification_processing/extraction/fixtures/source_unit_spellings.json)과 확인한 결함은 후속 검증용으로 보존한다.
해당 표기 지원이 현재 코드나 운영에 반영됐다고 주장하지 않는다. 후보 이미지는 배포하지
않고, 빌드 태그도 변경 전 소스로 다시 만들었다.

평가의 전체 백엔드 검사 종료 코드는 0이었다. 되돌린 최종 상태에서 백엔드·문서 검사는
1,223 passed / 90 skipped, 진공펌프 평가 기준 표적 검사 7 passed, 문서 검사 9 passed다.
전용 PostgreSQL의 실제 자동 승인/API/SQL 및 실행 집계 검사는 fixture 입력으로 2 passed였다.
이번 후보의 실제 전체 Flow·UI 연동은 rejected 판정으로 실행하지 않았으며 전날의 실제 모델
통합 검증을 이번 후보의 성공으로 대체하지 않는다.

작업공간 42,010,363바이트를 제거했고 cleanup=complete다. 이번 요청의 세 사이클은
중단·별도 평가 기준 보정·개선안 비교로 기록했다. 스킬의 최대 3사이클 범위를 넘겨 같은
원본을 반복하거나 회귀가 좋은 모델 응답만 선택하지 않았다. 원본·이전 점수·노출 이력과
최소 사례를 보존한다. 다음 작업은 원문에 맞는 대상/인용 기준을 먼저 확정하고, 모델 추론의
변동과 결정적 단위 처리 변경을 분리해 검증하는 것이다.

최종 정리에서는 이번 전용 DB 컨테이너와 익명 볼륨·staging API를 제거했다. 소유 표시를 확인한
파일 산출물 212바이트와 작업용 manifest·스크립트·로그 181,587바이트를 제거했다.
미사용 dangling Teoria 이미지 18개를 삭제했고 현재 배포가 참조하는 이미지
14개는 유지했다. 실패한 후보가 빌드 태그에 남지 않도록 변경 전 Worker 동작도
확인했다. Compose config와 최종 표적/문서 검사 16건이 통과했다. 운영 서비스 22개·unhealthy 0개이며
새 운영 배포나 Published Ontology 변경은 하지 않았다. 세 평가의 cleanup은 모두 complete다.

## 2026-11-09 고정 관찰의 Ontology 연결 비교

원문 추출 Tasks 00–05는 유지하고, 사전 처리 뒤 선택형 `06b 게시 Ontology 참고·의미 연결 비교`를
추가했다. 입력은 checksum으로 고정한 게시 Ontology snapshot과 최대 32개 Stable Concept ID다.
인증된 Admin API로 게시 이력·승인 표현의 출처를 확인하며, 프로파일 package가 있으면 같은
Ontology 버전을 요구한다. 기본 설정은 비활성이다. 제안은 기존 사전·프로파일 적용에 투입하지
않으며, 관찰 전체와 미해결 후보를 별도 산출물로 보존한다. 결과 UI에는 게시 버전·연결 제안·
보류 이유·원문 근거를 표시한다. 의미 동일성이나 추출 정확도를 자동 확정하지 않는다.

운영 조회에서 `goods 1.0.0`은 Draft, `teoria 0.1.4`는 Published였다. 운영 goods를 게시하지
않고 별도 PostgreSQL·실제 인증 Admin API에서 `goods_alignment_fixture 1.0.0`을 게시했다.
규격서 원문으로 만든 장비·레이저 파장·장비 질량의 세 개념을 사용한 silver fixture이며,
독립 정답이나 운영 Ontology가 아니다. 이 검증의 산출물 저장소는 FileArtifactStore다.

실제 마약류 탐지장비 PDF(SHA-256
`beac84ca54ce983c0c76c9148e6a1cb56cc4232b9f79023f6d3129546f4ea64e`)를
유지한 CLI `teoria-pipelines specification run --manifest`로 실행했다. 모델은
`gpt-6.1-sol`, parser는 0.9.16이다. 사전·의미 연결·적용 표준 자동 승인은 모두 껐다.

| 실행 | 원문 추출 재사용 | 연결 제안 | 미해결 | 검증한 산출물 |
|---|---|---:|---:|---:|
| `ontology_alignment_baseline_20261109` | 아니요 | 비교 단계 없음 | 비교 단계 없음 | 16 |
| `ontology_alignment_informed_20261109` | 예 | 0 | 22 | 14 |
| `ontology_alignment_context_20261109` | 예 | 3 | 19 | 14 |

세 실행의 상태는 모두 partial이다. 첫 비교에서 엔티티에 제목 근거만 전달하자 모델이
`procurement_scope` 문서 역할을 장비 유형과 혼동했다. 엔티티 소유 속성·원문 조항을 함께
제공하고 문서 역할과 물리적 유형의 차이를 설명하도록 일반 문맥 구성을 보강했다.
특정 문서 이름·ID를 코드에 넣지 않았다. 최종 22건은 엔티티 1건·속성 21건이며 관계는 없다.
3건은 장비, `1 kg 이하`, `785 nm`의 연결 제안이다. 원문 spot check 3건을 확인했지만,
단일 노출 원본의 사후 확인이므로 precision·recall이나 독립 정확도 측정으로 해석하지 않는다.
미해결 19건에는 선택한 개념 범위에서 표현하지 못하는 내용도 포함된다.

세 실행의 `extracted.json` 바이트 SHA-256은 모두
`6358d7643bb84572a09d99fdc5c57a0343cf1f96bb270944997d197dfaf5c403`이며,
관찰·원문 조항과 기존 `normalized.attributes`가 동일했다. 등록 산출물 44개의 실제 checksum,
문서 catalog의 실행 3개, 문서별 API의 비교 overlay를 확인했다. 추론 후 승인 사전 연결은 0개,
fixture 게시 버전·checksum은 그대로였다. 실제 staging API를 사용하는 브라우저에서 제안
3건·게시 버전·785 nm 원문 이동을 확인했고 page error는 0개였다. 관계 방향은 단위 검사로만
검증했으며 실제 문서 관계 정확도는 측정하지 않았다.

실제 모델을 실행한 최종 processor revision은
`f786a2fc3c09163ecaebd0cebdd01f20eae00a6126f54d0ebb8ced13d836565e`다.
이후 role/scope 허용값 검사를 강화한 revision
`73a9da8f5d5dd8b028bce772f800bc9adf5e0afa3cfa60e9bb400307ad8cff7b`에서
실제 모델 응답 22개를 재생했고 모든 판정이 동일했다. 재생은 새 모델 호출이나 네 번째
추출 실행이 아니다. 문맥·출처·타입·단위·소유자·방향·중복·누락·실패 보존과 문서별 표시
관련 표적 검사 27건, 프런트엔드 전체 154건, 문서 검사 9건이 통과했다.

최종 백엔드 전체 검사는 **1,234 passed / 90 skipped**, 프런트엔드 전체는 **154 passed**,
문서 검사는 **9 passed**다. 프런트엔드 production build, Compose config와 `git diff --check`가
통과했다. 이미지 내부에서도 최종 processor revision과 비교 옵션의 기본값 `None`을 확인했다.

`deploy/compose/deploy.sh deploy --all`이 실제 운영 서비스 교체·migration 확인·Prefect 재등록·
인증 Admin/Runtime artifact/MLflow 연결 확인·Worker 재시작을 완료했다. 서비스 **22개 실행**,
중지된 프로젝트 컨테이너 **0개**, unhealthy **0개**다. 배포된 Worker의 최종 processor revision과
06b Task를 확인했고, 실제 gateway health HTTP 200과 gateway가 제공하는 FormatID의 지연 로딩
JavaScript 모듈에서 비교 UI를 확인했다. 운영 화면에 fixture 결과를 이관하지 않았다.

배포 전후 Ontology 버전 목록과 사전 snapshot checksum
`15a7fda1345f307622eebdac4a2edbfa1c9116618872786417bd95dd5fed25e4`는 동일했다.
`goods 1.0.0`은 여전히 Draft이며 운영 `teoria 0.1.4`의 게시 checksum은
`dd978094dc04fc59b51457f513f95f2184144485366bc7b44638d93321aad254`로 유지됐다.
이번 코드 배포가 goods 게시나 AI 의미 제안의 공식 반영을 뜻하지 않는다. 추출 입력에 Ontology를
제공하는 변경과 다양한 문서의 의미 정확도 평가는 후속 검증 범위다.

기존 컨테이너를 교체한 뒤 미사용 Teoria 이미지 **34개**를 삭제했다.
현재 참조하는 이미지와 타 프로젝트는 유지했고 dangling Teoria 이미지 **0개**를 확인했다.
전용 staging API·PostgreSQL 컨테이너와 익명 볼륨을 제거했다. 소유 표시를 확인한 파일 산출물
**1,549,046바이트**, 작업용 manifest·스크립트·로그·Prefect 상태
**6,799,756바이트**를 제거했으며 cleanup=complete다. 압축 검증 기록과 원본 11개·출처·
이전 평가 이력·운영 데이터·배포 운영 로그·백업은 보존한다.
