# 규격서 파일 저장소 MinIO 전환 — 2026-10-30

규격서 처리의 기본 파일 저장소를 `s3://teoria-artifacts`로 전환했다.
Compose 기본 스택에 MinIO·초기화를 포함하며, Admin API·Worker에서 기존 입력·산출물 volume 마운트를 제거했다.
API는 `specification_inputs/` 업로드와 산출물 읽기, Worker는 입력 읽기와 `specification_processing/` 쓰기를 사용한다.
계정에는 객체 삭제 권한을 부여하지 않는다. 운영에서는 file artifact backend를 거부한다.

## 파일 보관과 종료 정리

- 원본·파싱·추출·판정·사전 스냅샷·보고서는 MinIO에 보관한다.
- 선택된 중간 결과는 내용 해시를 포함한 diagnostics ZIP 한 묶음으로 저장한다.
- S3 PUT 뒤 GET으로 저장된 바이트의 SHA-256을 확인한다.
- 정상·일반 실패 종료 시 진단 업로드가 성공하면 로컬 작업 폴더를 삭제한다.
- 업로드·검증 실패 또는 원본 업로드 확인 전 실패는 작업 폴더를 보존하고 오류에 위치를 기록한다.
- 임시 프롬프트·스키마·캐시는 묶음에서 제외한다. 강제 중단 시 자동 정리는 보장하지 않는다.
- MinIO 객체는 실행 종료만으로 지우지 않는다. 단계별 재시작 기능은 이번 변경 범위에 추가하지 않았다.

## 기존 파일 초기화

사용자의 기존 파일 삭제 지시에 따라 이관하지 않았다.

| 저장소 | 삭제 파일 | 삭제 바이트 |
|---|---:|---:|
| `teoria_specification-artifacts` | 244 | 109343504 |
| `teoria_specification-inputs` | 11 | 5991024 |

두 저장소의 남은 항목은 0개로 확인했다. 사전·승인 이력·공고 데이터·백업은 유지했다.
과거 DB 파일 참조는 남아 있지만 파일 조회는 불가능하다. 다음 실행은 새 MinIO 경로를 사용한다.
현재 입력의 원본 해시가 같은 경우 현재 추출을 재검토에 사용해 삭제된 과거 파일을 불필요하게 읽지 않는다.
다른 과거 근거가 필요한데 파일이 없으면 기존과 같이 보류한다.

## 검증

- 백엔드 전체: **759 passed, 79 skipped**. 문서 검사 9 passed.
- Compose config와 공백 검사 통과.
- 실제 MinIO 쓰기·읽기·업로드 해시 확인, 중간 결과 묶음 저장 후 로컬 삭제 확인.
- 실제 Admin API 업로드의 S3 URI·해시와 Worker의 입력 읽기 확인.
- 실제 Data DB에 임시 저장소 검증 레코드를 등록해 소유 산출물 API 조회를 확인하고 즉시 정리했다.
  문서 추출 성공으로 기록하지 않았으며 모델은 호출하지 않았다.
- API 계정의 파이프라인 산출물 쓰기 거부(403) 확인.
- 검증용 객체와 임시 DB 레코드 정리 완료. Admin healthy, Worker 기동과 실행 큐 재개 확인.
- DB migration은 추가하지 않았다. Application DB와 Data DB의 책임은 유지한다.

운영 이미지:

- `teoria-platform-authoring:specification-minio-20261030-v3`
- `teoria-pipelines:specification-minio-20261030-v3`
- `teoria-storage-init:latest` (`deploy/compose/minio/`에서 빌드)

초기화 CLI가 128MiB 제한에서 OOM으로 종료돼 512MiB로 조정했고, 초기화 exit 0을 확인했다.
임시 빌드 디렉터리는 빌드 후 자동 삭제했다. 별도 .artifacts 작업 폴더는 추가하지 않았다.
K3s 배포·전환은 검증하지 않았다.

현재 사용법은 [파이프라인](../procurement_specification_processing/pipeline.md),
기본 스택은 [Compose 운영](../deployment/compose.md)을 따른다.

## MinIO 브라우저 외부 경로

기존 nginx 공개 주소의 `/minio/`로 객체 브라우저를 연결했다. `/minio`는 포트·scheme을 유지하는
상대 경로 308 응답으로 정규화한다. `MINIO_BROWSER_REDIRECT_URL`은 Compose의
`TEORIA_MINIO_BROWSER_REDIRECT_URL`로 설정하며 기본값은 `http://localhost:8081/minio/`다.

- `/minio/` HTML의 base 경로, JavaScript 응답 200과 MIME type 확인.
- 다른 외부 Host·포트 헤더에서도 로그인·버킷 조회·로그아웃 확인. credential은 출력하지 않았다.
- 로그인 전·로그아웃 후 버킷 조회 403 확인.
- 메인 화면·Prefect 화면·gateway health 200 확인. nginx -t·Compose config·문서 검사 통과.
- S3 9000과 브라우저 9001의 직접 호스트 포트 공개는 없다.
- gateway 이미지 `teoria-nginx:minio-console-20261030-v2`, 이전 이미지도 별도 태그로 보존했다.
- MinIO의 기존 영구 volume을 유지했다. 브라우저 경로 추가 시 데이터 변경은 하지 않았다.

샘플을 제외한 로컬 `.artifacts` 정리 지시에 따라 나머지 554개 파일을 삭제했다.
`sample/` 원본 4개는 SHA-256 일치를 확인해 보존했다. 실제 Docker DB·MinIO 볼륨이나 백업을 삭제한 작업은 아니다.

## 빈 구형 볼륨 제거

사용자 지시에 따라 두 저장소가 비어 있음을 재확인하고
`teoria_specification-inputs`, `teoria_specification-artifacts` Docker 볼륨을 삭제했다.
Runtime API의 남은 읽기 전용 마운트와 Compose volume 선언도 제거했다.
Runtime API는 기존 이미지·환경과 게시 artifact 볼륨을 유지해 재생성했고,
직접 health·nginx 경유 Runtime health 모두 200을 확인했다.
이미지 선택은 `TEORIA_RUNTIME_API_IMAGE`로 현재 운영 버전을 고정했다.
DB·MinIO·인증·Runtime 게시 파일·복구 보관 볼륨은 삭제하지 않았다.
