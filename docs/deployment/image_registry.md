# Harbor 이미지 저장소와 폐쇄망 반입

개발 k3d와 운영 K3s·Kubernetes의 이미지 저장소로 Harbor를 사용한다.
Harbor는 `deploy/kubernetes/harbor/`의 독립 Helm release이며 Teoria 모듈 배포에 포함하지 않는다.
같은 클러스터의 `harbor` namespace에 설치할 수 있다. 별도 namespace가 장애 격리를 보장하지는 않는다.
Teoria의 **컨테이너 이미지** 화면은 repository·tag·검증된 digest만 조회한다.
대용량 이미지 파일은 Teoria API·MinIO·Prefect를 경유하지 않고 반입 PC에서 Harbor로 직접 push한다.

이미지 본문은 Harbor, 학습 데이터·모델 파일은 MinIO/S3, 실험·모델 버전은 MLflow가 소유한다.
학습·서빙은 [공통 실행 계약](model_execution.md)을 유지하며 Teoria·Prefect 설치를 모델 이미지에 요구하지 않는다.
빌드와 모델 학습은 별개다. 외부에서 실행 환경을 빌드하고 내부 데이터의 학습·서빙은 폐쇄망에서 수행한다.
코드·라이브러리를 바꾸지 않는 재학습에는 이미지 재빌드·재반입이 필요 없다.

## 외부 준비와 이미지 반입

외부 개발 환경에서 대상 노드의 OS·CPU 아키텍처에 맞게 이미지를 빌드·검증한다.
모델 실행 중 pip·apt·모델 가중치 등을 인터넷에서 내려받지 않도록 필요한 파일을 포함하거나 내부 저장소를 지정한다.
GitHub Actions는 선택 사항이며 폐쇄망 내부 빌드 서버·CI는 필수 조건이 아니다.

```bash
# 외부 개발 환경: 예시는 linux/amd64 단일 이미지다.
docker build --platform linux/amd64 -t my-training:v1 -f Dockerfile .
docker save -o my_training_v1.tar my-training:v1
sha256sum my_training_v1.tar > my_training_v1.tar.sha256
```

조직의 검토·반입 절차로 두 파일을 옮긴 뒤 내부 PC에서 수행한다.
Harbor에는 먼저 `teoria`(플랫폼)·`models`(학습·서빙) private project를 만든다.
모델에 따라 동일 이미지의 다른 command를 쓰거나 학습·서빙 이미지를 나눌 수 있다.

```bash
sha256sum -c my_training_v1.tar.sha256
docker load -i my_training_v1.tar
docker login harbor.example.com
docker tag my-training:v1 harbor.example.com/models/my-training:v1
docker push harbor.example.com/models/my-training:v1
```

수십 GB 이미지도 이 경로를 사용한다. 반입 PC의 archive·Docker layer 공간, Harbor 저장소,
클러스터 노드의 image layer 공간을 각각 확보한다. Harbor 앞단의 Ingress·LB에는 대용량 요청 제한·
읽기/쓰기 timeout을 조정한다. 제공 values는 nginx Ingress에 크기 제한 해제·요청 buffering 해제·
3600초 timeout을 설정한다. k3d `up`은 `overlays/k3s/traefik_config.yaml`의 HTTPS read/write timeout 3600초도 적용한다.
K3s에서 이 설정이 필요하면 기존 `kube-system/traefik` HelmChartConfig와 병합해 적용한다.
이 값은 controller의 모든 HTTPS 경로에 적용되므로 다른 추가 설정을 덮어쓰지 않는다. 외부 LB 제한도 확인한다.
실제 이미지 크기의 push·pull·Pod 실행을 대상 환경에서 확인해야 한다.

파일 SHA256은 반입 파일의 무결성이고 image digest는 Registry manifest의 무결성이다.
`save/load/push` 과정에서 manifest 형식이 달라질 수 있으므로 **Harbor에 게시된 최종 digest**를 사용한다.
Teoria 화면에서 태그를 선택해 digest를 확인하고 학습·서빙 요청에 고정한다.

## Harbor 설치

기준은 Harbor Helm chart **1.19.4 / Harbor 2.15.4**다. 외부 환경에서 chart를 확보한다.

```bash
helm repo add harbor https://helm.goharbor.io
helm pull harbor/harbor --version 1.19.4 --destination /path/to/export
sha256sum /path/to/export/harbor-1.19.4.tgz
```

고정 chart SHA256:
`759872bbabaf05524268096b9d551a480d3f6814d13ed08723036e2673859182`.
설치 스크립트는 이 checksum을 검증하고 로컬 chart만 사용하며 외부 chart를 다운로드하지 않는다.
버전 변경은 checksum·values·템플릿 검증을 함께 갱신한다.

`values.example.yaml`을 checkout 밖으로 복사해 권한을 제한한다.
Harbor URL·IngressClass·스토리지와 internal DB 초기 암호를 실제 환경에 맞춰 설정한다.
인증정보를 담은 values나 렌더링 결과는 Git·로그에 보관하지 않는다.

```bash
mkdir -p "$HOME/.config/teoria"
cp deploy/kubernetes/harbor/values.example.yaml "$HOME/.config/teoria/harbor_values.yaml"
chmod 600 "$HOME/.config/teoria/harbor_values.yaml"
# CHANGE_ME와 URL을 변경한다. k3d는 URL과 host 모두 harbor.teoria.localhost 사용.
```

일반 클러스터에서는 `harbor` namespace와 TLS 인증서를 먼저 준비한다.
Harbor 관리자 암호와 16문자의 암호화 key는 checkout 밖 Secret 파일로 준비한다.
기존 설치의 암호화 key를 새로 만들거나 DB 암호를 values만 바꿔 회전하지 않는다.

```bash
kubectl create namespace harbor
kubectl -n harbor create secret tls harbor-tls --cert=/secure/harbor.crt --key=/secure/harbor.key
# /secure/harbor_secrets.env: HARBOR_ADMIN_PASSWORD와 secretKey 두 항목.
kubectl -n harbor create secret generic harbor-secrets --from-env-file=/secure/harbor_secrets.env

# 먼저 렌더링 검토. 생성되는 Secret을 포함하므로 출력 파일은 비공개로 관리한다.
umask 077
bash deploy/kubernetes/harbor/deploy.sh --overlay generic \
  --chart /secure/harbor-1.19.4.tgz --values "$HOME/.config/teoria/harbor_values.yaml" \
  --render > /secure/harbor_rendered.yaml
# 같은 명령에서 --render를 제거하면 설치·갱신한다.
```

K3s는 `--overlay k3s`, k3d는 `--overlay k3d`를 사용한다.
기본 구성은 단일 replica·내부 DB/Redis·영속 볼륨이며 고가용성을 제공하지 않는다.
이미지 볼륨 기본 요청은 100Gi이고 실제 이미지 수·크기에 맞춰 확장한다.
삭제 시 PVC를 보존하지만 이는 백업을 대신하지 않는다. 운영은 DB·이미지 본문·Secret을 함께 백업한다.

폐쇄망 **최초 설치**에는 Harbor 자체와 K3s 기본 구성요소의 이미지도 필요하다.
외부에서 동일 chart·values로 `helm template`을 실행해 Pod·initContainer의 이미지 목록을 확인하고
기본 이미지까지 반입한다. 기존 내부 Registry가 있으면 image repository를 그 주소로 바꾸고,
없으면 각 노드의 containerd에 원래 이름으로 미리 적재한다.
k3d는 Docker 호스트에서 `k3d image import -c teoria /secure/harbor_images.tar`를 사용한다.
Harbor 설치에 Harbor 자신의 미기동 주소를 사용하면 시작할 수 없으므로 bootstrap 이미지는
미리 적재하거나 별도 접근 가능한 저장소를 사용한다. 기본 Trivy는 비활성이고 검사 DB·오프라인
갱신 절차를 마련한 뒤 별도로 활성화한다. 비활성 구성을 취약점 검사 완료로 간주하지 않는다.

## 개발 k3d

[로컬 실행](k3d.md)의 `local.sh up`은 클러스터·스토리지·Harbor TLS와 노드 DNS/CA를 준비한다.
기존 `k3d-teoria-images` Registry 컨테이너를 새로 만들지 않는다.
그 다음 위의 Harbor Secret·private values를 준비하고 Harbor를 별도로 설치한다.

| 사용처 | 주소 |
|---|---|
| Docker push·브라우저·Teoria 조회 | `https://harbor.teoria.localhost` |
| 플랫폼 이미지 | `harbor.teoria.localhost/teoria/<name>:<commit_sha>` |
| 모델 이미지 | `harbor.teoria.localhost/models/<name>@sha256:...` |

Harbor는 Docker 호스트의 `127.0.0.1:443`을 사용한다. 기존 플랫폼의 `8443`은 유지한다.
호스트 443 포트 충돌을 먼저 해결한다. 호스트 이름이 해석되지 않으면 hosts 파일에
`127.0.0.1 harbor.teoria.localhost`를 등록한다.
호스트 Docker는 `deploy/kubernetes/k3d/.local/harbor.crt`를
`/etc/docker/certs.d/harbor.teoria.localhost/ca.crt`에 설치하고 OS·브라우저도 인증서를 신뢰하도록 설정한다.
Docker Desktop은 해당 환경의 CA 신뢰 절차를 따른다. TLS 검증을 비활성화하지 않는다.
노드 containerd에는 같은 인증서를 복사하며 Pod는 CoreDNS에서 Traefik으로 연결한다.
토큰 서비스의 public URL도 호스트·노드·Pod 모두에서 같은 이름으로 접근 가능해야 한다.
Devcontainer·원격 Docker에서는 인증서 파일과 bind 경로가 Docker 호스트에 있어야 한다.

Harbor에 로그인한 뒤 선택적으로 로컬 빌드를 수행한다. 외부에서 반입한 이미지만 사용해도 된다.

```bash
docker login harbor.teoria.localhost
bash deploy/kubernetes/k3d/local.sh build
```

아래 Teoria 연결 Secret과 플랫폼·모델 pull Secret을 설정한 후 배포한다.
`up`은 빈 pull 인증으로 기존 credential을 덮어쓰지 않는다.
플랫폼용 최소 권한 Docker 설정 파일을 checkout 밖에 준비한다.

```bash
kubectl -n teoria create secret generic teoria-registry \
  --type=kubernetes.io/dockerconfigjson --from-file=.dockerconfigjson=/secure/platform_docker_config.json \
  --dry-run=client -o yaml | kubectl apply -f -
bash deploy/kubernetes/k3d/local.sh deploy  --component all
```

원격 개발에서 도메인 없이 접속하려면 [k3d IP 진입 구성](k3d.md#원격-ip-접속)을 적용한다.
Harbor 공개 URL과 이미지 참조가 `서버IP:18444`로 바뀌며 기존 내부 이름의 참조도 유지한다.

## Teoria 연결과 권한

Kubernetes `teoria-secrets`에 다음을 설정한다.
Harbor는 프로젝트 API로 repository를 조회하고 Distribution API로 tag·manifest를 검증한다.
기존 Distribution 연결은 `PROVIDER=distribution`으로 유지할 수 있다.

```dotenv
TEORIA_IMAGE_REGISTRY_PROVIDER=harbor
TEORIA_IMAGE_REGISTRY_PROJECT=models
TEORIA_IMAGE_REGISTRY_URL=https://harbor.example.com
TEORIA_IMAGE_REGISTRY_PUBLIC_HOST=harbor.example.com
TEORIA_IMAGE_REGISTRY_USERNAME=<models 조회 계정>
TEORIA_IMAGE_REGISTRY_PASSWORD=<조회 계정 암호>
TEORIA_IMAGE_REGISTRY_CA_PEM=<사설 CA인 경우 PEM 본문>
```

k3d에서는 URL·host를 `harbor.teoria.localhost`로 바꾼다.
CA는 PEM 전체를 보존하도록 Secret 생성 도구·비공개 YAML을 사용한다. env-file에 여러 줄을 그대로 넣지 않는다.
`model-control`의 `TEORIA_MODEL_ALLOWED_REGISTRIES`도 같은 host로 지정한다.

권한은 반입 PC의 push 계정, Teoria의 프로젝트 조회 계정, 플랫폼·모델의 pull 계정으로 나눈다.
조회 계정에는 repository list·artifact read·pull 등 실제 조회에 필요한 최소 권한만 부여한다.
Kubernetes 플랫폼 pull은 `teoria/teoria-registry`, 모델 pull은 `teoria-models/model-images`를 사용한다.
노드 containerd에도 CA를 신뢰시키며 Teoria CA 설정만으로 노드의 TLS 신뢰가 바뀌지는 않는다.
배포 인프라용 Harbor credential은 Teoria Application DB에 저장하지 않는다.
플랫폼 Ingress에 `/v2/`를 추가하지 않으며 이미지 업로드·삭제 권한을 Teoria에 주지 않는다.

일반 Kubernetes에서는 기존 공통 명령에 주소를 지정한다.

```bash
bash deploy/kubernetes/deploy.sh harbor.example.com/teoria COMMIT_SHA teoria.example.com \
  --overlay generic --shared-storage-class cluster-rwx --model-registry-host harbor.example.com
```

이미지가 이미 등록되어 있으면 이 명령은 빌드·GitHub 접속을 하지 않는다.
다만 manifest의 외부 서비스 이미지도 내부 Harbor로 이관하거나 각 노드에 사전 적재해야 한다.
기존 GitHub Actions는 인터넷 연결 환경의 선택적 빌드·배포 경로이며 폐쇄망 실행의 선행 조건이 아니다.

## 기존 구성에서 전환

기존 k3d 클러스터에는 Harbor의 443 포트와 노드 TLS 설정이 없으므로 `up`이 전환 안내로 중지한다.
기존 이미지·DB·게시 artifact·Secret을 백업하고 Harbor로 이미지 이관을 준비한 뒤,
운영자가 명시적으로 클러스터를 재생성한다. `local.sh`는 클러스터·Registry·볼륨을 자동 삭제하지 않는다.
원래 호스트 데이터 경로를 유지하고 `up` → Harbor 설치 → 같은 Secret·artifact 복원 → 플랫폼 배포 순서로 진행한다.
기존 `k3d-teoria-images` 컨테이너·이미지 본문은 이관 확인 뒤 별도로 정리한다.
이전 이미지 반입용 DB 이력·적용 migration도 삭제하거나 수정하지 않는다. Teoria 파일 반입 API·Flow는 사용하지 않는다.

현재 Kubernetes의 Semantic·MLOps 결합 설치 제한은 그대로이며 Harbor 설치로 해소되지 않는다.

## 검증과 설계 근거

```bash
TEORIA_TEST_HARBOR_CHART=/secure/harbor-1.19.4.tgz \
  uv run --project backend --locked --all-extras --group orchestration pytest \
  backend/tests/platform/mlops/test_image_registry.py \
  backend/tests/entrypoints/test_harbor_deployment.py \
  backend/tests/entrypoints/test_kubernetes_deployment.py -q
```

검사는 프로젝트 목록·페이지 처리·토큰 인증·digest 검증과 chart 렌더링을 확인한다.
개발 k3d의 실제 Harbor 설치·파일 반입·학습·서빙·복구는 [검증 기록](harbor_validation.md)에서 확인한다.
수십 GB 전송·완전 폐쇄망·운영 클러스터 검증은 별도다.

공식 근거: [Harbor push/pull](https://goharbor.io/docs/2.14.0/working-with-projects/working-with-images/pulling-pushing-images/),
[Helm chart와 values](https://github.com/goharbor/harbor-helm),
[프로젝트 API](https://github.com/goharbor/harbor/blob/main/api/v2.0/swagger.yaml),
[Distribution 토큰 인증](https://distribution.github.io/distribution/spec/auth/token/),
[Traefik EntryPoint timeout](https://doc.traefik.io/traefik/reference/install-configuration/entrypoints/).
[Palantir 컨테이너 모델](https://www.palantir.com/docs/foundry/integrate-models/container-overview)의
외부 실행 환경과 플랫폼 소비 경계를 참고한다. Teoria는 자체 이미지 빌드·파일 업로드 계층을 추가하지 않고
Harbor의 이미지 관리와 Prefect·MLflow·객체 저장소의 기존 책임을 유지한다.
