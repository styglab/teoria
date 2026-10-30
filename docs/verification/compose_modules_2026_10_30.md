# Compose 모듈 실행 검증 — 2026-10-30

현재 작업 트리에서 빌드한 이미지로 로컬 서버의 기존 볼륨을 사용했다.
Docker 20.10.21·Linux 4.15 환경이며 Teoria 전용 BuildKit은 v0.30.0이다.
K3s 배포와 새 서버의 빈 저장소 초기화는 이번 검증 범위가 아니다.

## 실제 실행

| 구성 | 상시 컨테이너 | 확인 |
|---|---:|---|
| 기본 | 10 | 기능별 Workflow 없음, 인증 유지 |
| MLOps | 14 | OpenMetadata·Runtime 없이 실행 |
| Semantic | 17 | 법령·메타데이터·진단 포함, FormatID·MLOps Workflow 제외 |
| FormatID | 11 | OpenMetadata·Runtime 없이 작성 API·규격서 Worker 실행 |
| 전체 | 22 | 초기화·등록 후 실행 및 `stop` → `start` 확인 |

각 구성은 이전 구성의 컨테이너를 `down`한 뒤 배포했다. 모듈 선택 API,
Workflow 목록, 컨테이너 수와 잘못된 인증정보의 401 응답을 확인했다.
`start`는 초기화·migration·Flow 재등록 없이 저장한 구성을 재개했다.
서버의 비공개 실행 기록은 `deploy/compose/.state/validation/`에 보존한다.

## 실제 업무 경로

- 합성 고객 데이터의 학습·평가·MLflow 모델 등록 Flow 완료.
- 모델 버전 3의 checksum 검증·서빙 전환 Flow 완료 및 추론 API 200 확인.
- 공식 ingestion 이미지의 일회성 Job을 통한 OpenMetadata 동기화 완료: 오류 0건.
- 합성 DOCX 규격서 한 건의 업로드·S3 원본 조회·파싱·Codex 추출·고정 표준 적용·결과 저장 Flow 완료.
- 법령 검색·Ontology 조회·Runtime 게시 artifact checksum 확인.
- MCP STDIO 초기화와 도구 목록 조회 성공. 현재 게시된 업무 도구는 0개다.

첫 규격서 샘플은 분류코드 누락으로 표준과의 분류 일치 검증에서 거부됐다.
분류코드를 지정한 재실행은 완료됐다. 이는 추출 의미 정확도나 표준 품질 평가의 통과를 뜻하지 않는다.
Flow 상태는 Completed, 문서 처리 판정은 partial이다. 산출물 9개와 구성 전환 후 S3 미리보기 200을 확인했다.
이전 종료 때 실행 컨테이너가 삭제된 고아 Prefect 실행 한 건은 사유를 남겨 Crashed로 정리했다.
그 실행의 Data DB 결과와 이력은 삭제하지 않았다.

## 배포 경로에서 수정한 문제

- FormatID Worker의 잘못된 경량 이미지 target을 파서·Codex가 있는 Worker target으로 수정.
- 이미지당 한 번만 빌드하고, 전체 이미지 조회로 미사용 `<none>` 이미지도 검사하도록 수정.
- 현재·직전·컨테이너 참조 이미지 및 다른 모듈의 태그 있는 준비 이미지를 보존하도록 정리 범위 수정.
- API·제어 서비스 종료 후 DB·검색·객체 저장소를 중지하도록 종료 순서 보완.
- 비공개 배포 상태·환경 백업을 Docker 기본 빌드 context에서 제외.

MinIO 클라이언트 레지스트리는 401, OpenMetadata ingestion 레지스트리는 429를 반환했다.
서버에 있던 같은 버전 이미지를 OCI로 보존하고 파일시스템 layer와 실행 설정의 일치를 확인해 빌드했다.
캐시 경로·전환 방법은 [설정 안내](../deployment/configuration.md)를 따른다.
새 환경은 공식 원본 이미지에 접근하거나 검증한 OCI 원본을 별도로 확보해야 한다.

비활성 기능의 Python 코드를 이미지에서 제외하거나 모든 API import를 조건부로 바꾸는 작업은 남아 있다.
운영 명령의 기준은 [Compose 안내](../deployment/compose.md)다.
