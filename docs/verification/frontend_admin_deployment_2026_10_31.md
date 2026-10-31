# Web·Admin API 배포 — 2026-10-31

## 대상과 입력

기존 Compose 프로젝트 `teoria`의 `mlops,semantic,formatid` 구성을 유지했다.
현재 작업트리의 프런트엔드 개선과 Admin API 변경으로 `teoria-nginx:latest`와
`teoria-platform-authoring:latest`를 빌드했다. git commit을 배포 버전으로 간주하지 않고
아래 실제 이미지 ID와 게이트웨이가 전달한 정적 파일 checksum을 확인했다.
다른 Runtime·Prefect Worker 이미지와 DB migration·게시 artifact는 변경하지 않았다.

전용 Buildx builder `teoria`로 `admin-api nginx`만 빌드한 뒤 같은 API 이미지를 공유하는
네 서비스를 Compose `up -d --no-build --no-deps --wait`로 교체했다.
배포 전 설정 checksum은 기존 성공 배포 상태와 일치했다.

| 컨테이너 | 배포 이미지 ID 앞 12자리 | 확인 상태 |
|---|---|---|
| `teoria-nginx-1` | `35efabc24959` | healthy |
| `teoria-admin-api-1` | `cafdfffeb121` | healthy |
| `teoria-policy-control-plane-1` | `cafdfffeb121` | healthy |
| `teoria-metadata-assessment-worker-1` | `cafdfffeb121` | 실행 중; 별도 healthcheck 없음 |

## 실제 환경 검증

- 게이트웨이 `/health`와 인증된 Admin session 정상. 인증 없는 session 요청은 401.
- 모듈 flag가 기존 세 기능과 일치하며 Runtime 게시 artifact checksum·MLflow 연결 검사 통과.
- 자산 검색 총 14개, 설명 없음 9개·소유자 없음 14개·태그 없음 14개를 조회했다.
  5개 단위의 두 페이지가 겹치지 않고, 존재하지 않는 검색어·스키마는 0개였다.
  누락 필터 결과와 별도 집계가 일치했다. 조회 응답의 `Cache-Control: no-store`를 확인했다.
- 규격서 이력 16개와 저장된 실행 상세를 조회했다. 13개 실행에 후보 산출물 참조가 있었다.
- 실제 게이트웨이를 사용하는 Chromium에서 관리자 연결·로그아웃·재연결,
  검색·누락 필터, 저장된 후보 검토 탭을 확인했다. 모의 API는 사용하지 않았다.
  모바일 폭 390px에서 페이지 가로 넘침이 없었다. 브라우저 예외와 서버 5xx 응답은 0건이었다.
- 전달된 JS/CSS는 사전에 빌드·검증한 `frontend/dist` 파일의 checksum과 일치했다.
- 새 네 컨테이너의 배포 이후 로그에서 ERROR·CRITICAL·Traceback을 발견하지 않았다.

실제 후보의 Draft 생성·승인과 신규 문서 처리·AI 진단 작업은 실행하지 않았다.
이전 단계의 모의 API 승인 흐름 검증을 실제 운영 데이터 승인 성공으로 기록하지 않는다.

## 정리와 보존

검증 후 사용자가 요청한 이전 이미지 정리를 수행했다.
Compose가 교체한 이전 컨테이너 4개의 제거를 확인했고, 모든 실행·중지 컨테이너와
다른 저장된 프로젝트 상태에서 참조하지 않는 다음 두 이미지를 강제 옵션 없이 삭제했다.

| 삭제한 이전 이미지 | 이미지 ID 앞 12자리 |
|---|---|
| Web gateway | `9c9fa0dfec4b` |
| Admin/authoring | `42760739d1be` |

현재 컨테이너·정기 ingestion·초기화 작업에 필요한 태그 있는 이미지는 유지했다.
DB·원본·산출물·인증 볼륨은 정리 대상에 포함하지 않았다.
검증에 사용한 개발 컨테이너의 임시 네트워크 연결을 해제하고 빌더를 중지했다.

현재 이미지와 삭제한 이전 이미지 참조는 `deploy/compose/.state/teoria/deployment.json`에
반영했다. 상세 배포 전후 상태와 실조회 결과는 같은 로컬 상태 디렉터리의
`frontend_rollout_before.json`, `frontend_rollout_after.json`,
`frontend_rollout_verification.json`에 보관한다. 삭제한 이전 두 이미지는 로컬 rollback 대상으로
남아 있지 않으며, 필요하면 해당 소스를 다시 빌드해야 한다.

배포·정리 절차의 기준은 [Compose 운영 안내](../deployment/compose.md)를 따른다.
