# 최초 설치와 도메인 활성화

빈 환경에서는 기반 서비스 → 계정·게시 artifact → Teoria 순서로 준비한다.
`--component all`은 필요한 인증과 artifact가 이미 준비된 환경을 한 번에 갱신하는 명령이다.
플랫폼 설치가 Ontology 검토·승인·게시를 대신하지 않는다.

## 1. 이미지·클러스터·기반 서비스

[공통 배포 준비](kubernetes.md#배포-전에-준비할-것)에 따라 namespace·Secret·TLS·pull 인증을 준비한다.
Harbor는 독립 설치하며 폐쇄망에서는 검증한 이미지와 chart를 반입한다.
이후 예시의 prefix·commit·공개 호스트·overlay는 실제 환경 값으로 지정한다.

```bash
bash deploy/kubernetes/deploy.sh "$IMAGE_PREFIX" "$COMMIT_SHA" "$PUBLIC_HOST" --overlay k3s --component database
bash deploy/kubernetes/deploy.sh "$IMAGE_PREFIX" "$COMMIT_SHA" "$PUBLIC_HOST" --overlay k3s --component storage
bash deploy/kubernetes/deploy.sh "$IMAGE_PREFIX" "$COMMIT_SHA" "$PUBLIC_HOST" --overlay k3s --component workflow
bash deploy/kubernetes/deploy.sh "$IMAGE_PREFIX" "$COMMIT_SHA" "$PUBLIC_HOST" --overlay k3s --component mlflow
bash deploy/kubernetes/deploy.sh "$IMAGE_PREFIX" "$COMMIT_SHA" "$PUBLIC_HOST" --overlay k3s --component openmetadata
```

k3d는 `local.sh deploy --component <이름>`으로 같은 단계를 실행한다.
일반 Kubernetes는 `--overlay generic`과 저장소·IngressClass 옵션을 지정한다.
기존 외부 서비스를 연결한 경우 해당 설치 단계를 생략하고 Service/DNS·ConfigMap 연결을 준비한다.

일반 설정과 역할별 입력은 [envs/dev·prod](../../deploy/kubernetes/envs/README.md)에서 준비한다. 필요한 namespace를 준비한 뒤 `--role connections`와 사용하는 Secret 역할을 명시적으로 등록한다.
ConfigMap이 없는 환경에서 플랫폼·MLflow 배포가 예시를 자동 등록하지 않는다. 기존 리소스 이름은 유지한다.

## 2. 계정과 공개 URL

OpenMetadata에 관리자·ingestion bot을 준비하고 `teoria-secrets`의
`TEORIA_OPENMETADATA_AUTH_TOKEN`·`OPENMETADATA_INGESTION_BOT_TOKEN`을 설정한다.
등록된 Teoria Data DB source의 읽기 계정도 확인한다. 구체적인 계정 준비는 [OpenMetadata](openmetadata.md)를 따른다.

`connections.env.example`의 `TEORIA_OPENMETADATA_BASE_URL`은 Pod가 호출하는 내부 API다.
`TEORIA_OPENMETADATA_PUBLIC_URL`은 브라우저용 URL이며 별도 Ingress/DNS·TLS를 준비한 경우에만 설정한다.
빈 값이면 홈의 외부 콘솔 링크를 숨긴다. 호스트명이나 8585 포트를 추측하지 않는다.

## 3. 승인·게시된 Runtime artifact

기존 환경을 이관하면 Application DB의 게시 이력과 일치하는 `active.json`·version 디렉터리를 준비한다.
[K3s artifact 복사 절차](k3s.md#인증정보와-최초-데이터)를 따른다.
PVC가 아직 없다면 배포할 YAML에서 PVC만 추출해 먼저 적용할 수 있다.
아래는 k3s 예시이며 `kubectl apply` 전에 `/secure/teoria_pvc.yaml`의 저장소 클래스를 확인한다.

```bash
bash deploy/kubernetes/deploy.sh "$IMAGE_PREFIX" "$COMMIT_SHA" "$PUBLIC_HOST" --overlay k3s --render > /secure/teoria_render.yaml
uv run --project backend --locked python - <<'PY' > /secure/teoria_pvc.yaml
import yaml
with open('/secure/teoria_render.yaml') as stream:
    claims = [r for r in yaml.safe_load_all(stream) if r and r['kind'] == 'PersistentVolumeClaim']
print(yaml.safe_dump_all(claims, sort_keys=False))
PY
kubectl apply -f /secure/teoria_pvc.yaml
```

기존 artifact가 없는 새 제품 설치는 소유자가 먼저 [Ontology 작성 절차](../platform/ontology.md)에 따라
Draft·검토·승인·게시를 완료해야 한다. 운영 Runtime의 artifact 검사를 끄는 방식으로 해결하지 않는다.
초기 작성이 필요한 경우 관리 PC에서 DB를 제한적으로 연결하고, 별도 authoring 프로세스를 loopback에만 실행할 수 있다.
보안 경로의 env 파일에 Application DB 연결·bearer 인증·작성 Registry 경로를 설정하고
`TEORIA_REGISTRY_REQUIRE_PUBLISHED=false`, `TEORIA_FORMATID_ENABLED=false`,
`TEORIA_GOODS_AUTHORING_ENABLED=false`, `TEORIA_LEGAL_INFORMATION_ENABLED=false`로 제한한다.
이 설정은 초기 작성 프로세스 전용이며 클러스터의 Admin·Runtime 설정에 복사하지 않는다.

```bash
# 다른 터미널: 관리 PC의 loopback으로만 DB 연결
kubectl -n teoria port-forward service/platform-postgres 15432:5432 --address 127.0.0.1
# TEORIA_APP_DATABASE_URL에는 위 연결을 사용하는 teoria_app 계정 DSN을 설정한다.
# 새 DB인 경우, 적용 이력을 보존하는 기존 migration 명령부터 실행한다.
TEORIA_ENV_FILE=/secure/bootstrap_authoring.env uv run --project backend --locked --extra api teoria migrate-app
TEORIA_ENV_FILE=/secure/bootstrap_authoring.env uv run --project backend --locked --extra api \
  uvicorn teoria.entrypoints.admin_api:app_factory --factory --host 127.0.0.1 --port 8001
```

이 API의 검토·승인·게시가 끝난 후, 관리 PC에서 명시적으로 Registry release와 Runtime bundle을 만든다.
아래 `teoria` namespace는 실제 게시한 Ontology namespace에 맞춘다.
`TEORIA_ENV_FILE`에는 검토 대상 DB 연결이 필요하다. version은 재사용하지 않는다.

```bash
TEORIA_ENV_FILE=/secure/bootstrap_authoring.env uv run --project backend --locked --extra api \
  teoria publish backend/contracts/runtime --version "$REGISTRY_VERSION" --output /secure/registry_releases
TEORIA_ENV_FILE=/secure/bootstrap_authoring.env uv run --project backend --locked --extra api \
  teoria compile-runtime-bundle "/secure/registry_releases/$REGISTRY_VERSION" \
  --ontology-namespace teoria --version "$BUNDLE_VERSION" --output /secure/runtime_store
uv run --project backend --locked --extra api teoria activate-artifact /secure/runtime_store --version "$BUNDLE_VERSION"
```

컴파일은 DB에 실제 게시된 Ontology·승인된 Binding만 읽으며, 없으면 실패한다.
준비된 store를 PVC에 이관한 뒤 초기 작성 프로세스와 DB port-forward를 종료한다.
배포는 해당 artifact의 checksum·version을 확인한다. SQL migration·게시 revision을 직접 고치지 않는다.

## 4. 플랫폼 설치

연결 ConfigMap·모델 실행 Secret과 게시 artifact가 준비되면 기본 `platform` 배포를 실행한다.
API 연결·Runtime artifact 확인과 Prefect 등록을 마친 뒤 Worker를 활성화한다.
데이터 처리·법령 수집과 정기 metadata 동기화는 기본 비활성화다.

## 5. 규격서 처리 활성화

다음 세 가지를 별도로 준비한다.

- `specification-processing`: [specification.env.example](../../deploy/kubernetes/envs/dev/specification.env.example)의 API·S3 설정.
  API 토큰은 Admin 토큰과 다른 난수다. 인증 주체는 `service:specification-processing`이며
  허용 경로는 `domains/goods/authoring_client.py`가 소유한다. Ontology 게시·메타데이터 쓰기 권한을 부여하지 않는다.
  기존 서비스의 draft·승인 정책과 감사는 그대로 적용된다.
- `specification-codex`: 규격서 실행 전용 `auth.json`. Job namespace에 복사하고 해당 Job만 마운트한다.
- `authoring-codex`: 물품 의미 작성 API 전용 `auth.json`. Admin API만 마운트한다.
  두 인증은 운영 주체·사용 한도에 맞게 각각 발급한다. metadata 진단의 기존 인증 PVC와 공유하지 않는다.

```bash
kubectl -n teoria create secret generic specification-processing --from-env-file=/secure/specification.env \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n teoria create secret generic specification-codex --from-file=auth.json=/secure/specification_codex/auth.json \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n teoria create secret generic authoring-codex --from-file=auth.json=/secure/authoring_codex/auth.json \
  --dry-run=client -o yaml | kubectl apply -f -
```

S3 bucket은 실행 전에 준비한다. MinIO를 쓰면 관리자 PC의 `mc` alias로 bucket·전용 사용자를 만들고
[저장소 정책](../../deploy/kubernetes/base/domains/goods/storage_policy.json)을 부여한다.
예시는 `teoria-artifacts` bucket의 조회·생성만 허용하며 삭제·관리자 권한을 부여하지 않는다.
다른 bucket을 쓰면 정책과 `TEORIA_SPECIFICATION_ARTIFACT_ROOT`를 함께 변경한다.
플랫폼·Job에는 MinIO root credential을 전달하지 않는다.

```bash
# teoria alias의 관리자 인증은 보안 운영 환경에서 미리 설정한다.
mc mb --ignore-existing teoria/teoria-artifacts
mc admin policy create teoria specification-artifacts deploy/kubernetes/base/domains/goods/storage_policy.json
# 전용 사용자는 운영 Secret 관리 절차로 생성한 후:
mc admin policy attach teoria specification-artifacts --user "$SPECIFICATION_STORAGE_USER"
```

ConfigMap의 `TEORIA_SPECIFICATION_PROCESSING_ENABLED=true`로 설정하고, 문서 입력도 허용할 때
`TEORIA_SPECIFICATION_UPLOAD_ENABLED=true`로 설정한다. 업로드는 S3에 저장하므로 read-only Data DB 권한을 확대하지 않는다.
배포는 필수 입력을 먼저 확인하고, API 기동 후 서비스 주체·Codex 인증 파일·S3 bucket 접근을 읽기 전용으로 검사한다.
이 검사가 성공해야 규격서 Worker·일정이 활성화된다. S3 쓰기·모델 추론 성공까지 증명하는 검사는 아니다.
실제 원문 업로드와 단일 규격서 실행으로 운영 검증을 마친다.

Codex 인증은 추론마다 별도 임시 환경에 복사한다. DB·S3·Prefect·Admin 토큰은 추론 subprocess에 상속하지 않는다.
Secret 인증이 갱신되면 별도 발급·Secret 교체와 플랫폼 재배포를 진행한다. 실행 중 Job은 기존 Secret을 사용할 수 있다.
운영 worker에는 refresh 결과가 영구 반영되지 않으므로 인증 만료·사용 한도를 모니터링한다.

법령 수집은 `TEORIA_CONNECTOR_MOLEG_LAW_API_KEY`를 준비하고 `TEORIA_LEGAL_INFORMATION_ENABLED=true`로 설정한다.
규격서·법령 Job에는 각자의 DB·Prefect 인증과 해당 기능의 Secret만 전달한다.

## 검증 상태

템플릿·실제 API 인증·Prefect Job 생성 계약은 자동 검사하며, 전체 플랫폼 신규 설치와 폐쇄망 반입은 별도 실환경 검증 대상이다.
정지 중인 개발 k3d를 시작하거나 기존 데이터·서비스를 갱신하지 않는다.

[Palantir Architecture Center](https://www.palantir.com/docs/foundry/architecture-center/overview/)의
데이터 처리·의미 작성·업무 앱 책임 분리를 참고한다. Teoria는 Prefect·OpenMetadata와 기존 승인 권위를 유지한다.
