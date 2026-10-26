# HTTP 진입점 통합 — 2026-10-26

Compose의 UI 파일 제공과 reverse proxy를 하나의 nginx로 합쳤다. K3s는 Traefik이
각 서비스로 직접 라우팅하도록 중간 nginx Deployment·Service를 제거했다.
Compose 운영 반영과 K3s 격리 환경 검증을 구분해서 기록한다.

## 변경

- `frontend/Dockerfile`에 `gateway`·`standalone` target을 두고 React build 단계를 공유한다.
- Compose는 `gateway` target을 `nginx` 서비스로 실행하며 별도 `admin-ui` 서비스를 제거했다.
- K3s는 `standalone` UI 이미지를 유지하고 Ingress가 API·Prefect·UI Service로 직접 연결한다.
- `/admin-api`·`/runtime-api`와 `/prefect/api`는 `api-prefix` Middleware로 실행 서비스에 맞게 변환한다.
  Prefect UI의 `/prefect`는 유지한다. TLS host는 두 Ingress에 동일하게 적용한다.
- GitHub K3s 이미지 matrix에서 중간 nginx 이미지를 제거했다. 배포 스크립트는 공개 HTTPS 검증을
  완료한 뒤 이전 `Deployment/nginx`·`Service/nginx`를 제거한다.
- CI의 API-only K3s는 공식 Traefik v3.7.16 CRD를 설치한 뒤 server dry-run을 수행한다.

현재 기준 위치는 [저장소 구조](../architecture/repository-structure.md), 운영 절차는
[Compose](../deployment/compose.md)·[K3s](../deployment/k3s.md)를 따른다.

## 검증

| 대상 | 결과 |
|---|---|
| 프런트엔드 | 45 tests passed, TypeScript·Vite build 성공 |
| 이미지 | gateway·standalone build 및 nginx 설정 검증 성공 |
| Compose | 설정 테스트 7개·설정 검증 성공 |
| HTTP 라우팅 | 격리 Compose gateway 8개·실제 Traefik Kubernetes Ingress 8개 통과 |
| HTTP 검증 내용 | 실제 UI assets·SPA fallback·health, API prefix/query/body/인증 header 보존, Prefect UI/API 분리, WebSocket 101 handshake |
| Kubernetes schema | 격리 K3s API 서버에서 execution 3개·infrastructure 18개·OpenMetadata 2개·application 24개 및 Job 9개 server dry-run 성공 |
| Release 렌더링 | 두 Ingress host 치환·이미지 치환 후 server dry-run 성공 |
| 문서·shell | 문서 검사기 테스트 7개·링크 검사·`bash -n deploy/k3s/deploy.sh`·diff 검사 성공 |

라우팅 검증은 [HTTP 계약 테스트](../../tests/integration/test_public_routing.py)와
[격리 echo upstream](../../tests/integration/fixtures/http_upstream.py)을 사용했다.
실제 Traefik v3.7.16은 임시 K3s API의 Ingress·Middleware·EndpointSlice를 읽고
실제 UI 이미지와 격리 API fixture에 요청을 전달했다. 단순 YAML 검사만 수행한 것은 아니다.

기존 Vite chunk 크기 경고는 남아 있으며 이번 HTTP 진입점 변경과 별도다.

## Compose 운영 반영

운영 backend와 연결한 preview gateway에서 화면·API·법령 조회를 먼저 확인했다.
기존 nginx·UI 이미지를 rollback tag로 보존하고 gateway만 교체했다.
새 gateway의 실제 요청을 확인한 뒤 `teoria-admin-ui-1`을 종료·제거했다.
DB·Worker·OPA·게시 artifact는 이번 교체 대상에 포함하지 않았다.

- 운영 Compose 서비스: **18개 → 17개**.
- 개발 환경 포함 Teoria 관련 상시 컨테이너: **19개 → 18개**.
- 새 gateway: healthy, restart 0.
- 실제 UI JavaScript·SPA 경로·Admin·Runtime health 및 인증 조회·법령 검색 성공.
- Prefect 화면 200, 인증된 API 200, 익명 API 401 확인.
- 복구 자료: `backups/teoria/gateway_consolidation_20261026T083844Z/`.
- 새 gateway image: `sha256:3be70bc6d06a04c04092ac04c0e05efe4e87d2d7779ad7bcdc15a53318f44e8c`.

K3s 운영 접속용 kubeconfig·EC2 연결 설정이 현재 환경에 없어 실제 운영 클러스터에는 배포하지 않았다.
K3s는 배포 설정·CI·격리 API 서버·실제 Traefik 라우팅 검증까지 완료했다.
임시 gateway·Traefik·K3s·upstream 컨테이너와 검증 network는 확인 후 정리했다.
