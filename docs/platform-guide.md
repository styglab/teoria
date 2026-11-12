# 사용 안내

Teoria에서 데이터 자산을 확인하고 업무 의미를 작성한 뒤 앱에 활용한다.
현재 첫 업무 앱은 규격서를 구조화하는 **FormatID**다.

## 시작

로컬 Kubernetes 통합 환경은 [k3d 실행](deployment/k3d.md)에 따라 준비하고
`local.sh status`에 표시된 주소로 접속한다. 운영은 [통합 Kubernetes 배포](deployment/kubernetes.md)를 따른다.
Kubernetes는 [통합 배포](deployment/kubernetes.md)로 Metadata·Ontology·MLOps를 함께 실행한다.
규격서 처리·물품 사전·법령 수집은 별도 도메인 설정이다. 사용자 권한도 실행 가능 여부를 제한한다.
메뉴는 데이터·Ontology·MLOps·도메인 관리·업무 앱·공통 운영으로 나눈다.
AI/AIP는 예약 영역이며 현재 사용할 실행 화면은 없다.

## 데이터 자산 정비

**데이터 자산**에서 테이블·컬럼·설명·소유자·품질·계보를 확인한다.
정보의 기준은 OpenMetadata다. AI 진단은 제안이며 검토·적용 성공 후 자산에 반영된다.
법령 기반 공개 진단은 수집한 법령 근거와 조회 가능 범위를 함께 확인한다.

자세한 절차: [메타데이터 조회·진단·검토](platform/metadata.md).

## Ontology 작성과 연결

**온톨로지**에서 업무 개념·속성·관계를 작성한다.
Draft를 검토·승인·게시하며 게시한 revision은 직접 수정하지 않는다.
변경하려면 게시 버전에서 새 Draft를 만든다.
**데이터·용어 연결**에서 개념을 OpenMetadata 용어나 자산과 연결한다.
연결도 검토·승인을 거치며 이력을 보존한다.

물품 원문 표현은 **도메인 관리 → 물품 사전**에서 관리한다.
표현 등록과 업무 개념 승인은 서로 다른 작업이다. 새 업무 의미는 Ontology에서 작성한다.

참고: [Ontology](platform/ontology.md) · [물품 표현 연결](domains/goods/expression_links.md).

## FormatID 사용

1. **업무 앱 → FormatID**에서 명시적으로 규격서를 입력한다.
2. 실행할 문서와 처리 기준을 선택한다.
3. **파이프라인**에서 실행 상태와 실패 단계를 확인한다.
4. 저장 결과에서 물품·구성품·속성·조건과 원문 근거를 확인한다.
5. 의미 후보·프로파일·표현 연결을 각각 검토하고, 게시 버전과 snapshot을 고정해 적용한다.
   워크플로우의 `awaiting_approval`에서는 표시된 검토 단계를 처리한 뒤 같은 실행 ID로 재개한다.

프로파일 적용 결과의 **게시 의미로 조회**는 별도 승인·고정한 Runtime 조회 기준을 사용한다.
승인된 문서별 해석이 포함된 경우 구성 수량도 별도 표로 보여준다.
아직 게시·연결되지 않은 경우 원래 추출 결과와 구분해 오류를 표시한다.
화면은 추출·표현 등록·의미 연결·표준 적용 단계를 구분한다.
과거 실행에 단계 정보가 없으면 완료로 추정하지 않는다.
추출 표준 자동 채택은 draft이며 Published Ontology 승인이 아니다.

참고: [규격서 처리](domains/goods/specifications/pipeline.md) ·
[물품 모델](domains/goods/model.md) · [프로파일](domains/goods/specifications/normalization_profiles.md).

## 운영과 현재 제한

**파이프라인**은 허용된 실행·스케줄·취소 요청을 관리한다.
**연결 및 설정**은 서비스 연결과 인증 상태를 보여준다.
별도 선택 영역인 **MLOps**에서 모델·버전·평가를 조회한다.
MLOps는 업무 종류와 무관하게 모델을 운영한다. 학습 파라미터·평가는 MLflow에서, 서빙 상태는 모델별 배포 목록에서 조회한다.
추론 결과를 업무 판단·승인에 사용하는 기능은 해당 도메인과 업무 앱이 맡는다.
Compose에서는 공통 Worker가 학습마다 전용 컨테이너를 실행하고, 배포 요청에 따라 모델별 서빙 컨테이너를 생성한다.

물품 2.0.0의 마지막 운영 검증 상태는 Draft이며 현재 상태는 재확인이 필요하다.
의미 비교나 승인 API 구현만으로 실제 물품 Runtime이 활성화되지는 않는다.
기존 공고·계약·기업 분석과 구형 첨부 자동 수집은 비활성 보관 상태다.
전체 구현 범위는 [로드맵](roadmap.md), URL과 권한은 [관리 화면 참조](platform/admin_ui.md)를 읽는다.

이미지는 반입 PC에서 Harbor에 직접 push한다. 로컬 k3d는 `harbor.teoria.localhost`를 사용하며
운영은 내부 Harbor 주소를 설정한다. 외부에서 빌드한 이미지를 반입하므로 폐쇄망 빌드·GitHub Actions는 필수가 아니다.
Teoria는 대용량 이미지 파일을 업로드하거나 Registry로 중계하지 않는다.

Kubernetes MLOps는 PostgreSQL·MinIO·Prefect·MLflow·Teoria를 독립 배포 단위로 관리한다.
플랫폼 업데이트는 기본 `platform`, 개발 최초 전체 설치는 `all`을 선택한다.
[배포 수명주기](deployment/kubernetes.md#명령과-실행-순서)를 따른다.

공통 운영의 **컨테이너 이미지**에서는 연결한 외부 Registry의 모델 학습·서빙 repository와
태그·검증된 digest 참조를 조회한다. [Registry 연결과 배포](deployment/image_registry.md)를 참고한다.
현재 화면은 조회용이며 이미지 push·삭제·임의 외부 모델 실행을 수행하지 않는다.

MLOps는 [공통 모델 실행 계약](deployment/model_execution.md)으로 외부 학습·서빙 이미지를 실행한다.
이미지의 학습·서빙 실행 명령은 요청의 `command`에 명시한다.
Compose 개발 환경과 Kubernetes는 같은 입력을 사용하며 실행 방식만 다르다.
고객 이탈 샘플의 소스·Dockerfile·이미지는 [archive/customer_churn](../archive/customer_churn/README.md)에 보관한다.
플랫폼 내부 예제 API·전용 Flow·테스트 폼과 구형 구현 보관본은 제거했으며 같은 이미지에서 학습과 서빙을 실행한다.

Kubernetes는 [공통 base와 환경별 overlay](deployment/kubernetes.md)를 사용한다. 일반 클러스터는 generic,
기존 EC2 K3s는 k3s overlay를 선택하며 모델 실행·API 계약은 같다. 운영 환경별 검증 여부는 별도로 기록한다.
로컬 Kubernetes는 [k3d 실행 안내](deployment/k3d.md)의 단일 노드 클러스터와 k3d overlay를 사용한다.
기존 Semantic 배포를 공유하며 Compose의 규격서 처리 전체 배포와 같은 범위로 간주하지 않는다.

배포 구조 정리로 이미지 빌드 입력을 `deploy/image_builds/`로 옮기고, 작업 배정 Worker와 규격서·법령 실행 이미지를 분리했다.
규격서 API 인증·S3·역할별 Codex 연결과 업로드 설정을 추가했으며, OpenMetadata 콘솔 주소는 별도 공개 URL을 사용한다.
[최초 설치 절차](deployment/bootstrap.md)에 따라 기반 서비스·계정·승인 artifact·플랫폼을 순서대로 준비한다.
실제 통합 신규 설치와 규격서 실행은 아직 운영 검증 전이다.
