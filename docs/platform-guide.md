# Teoria 시작과 역할별 작업

현재 활성 업무는 명시 입력 규격서의 파싱·정보 추출·표준 후보 관리다.
Ontology·Binding·Source·Mapping·Capability·Runtime·Context·OPA와 OpenMetadata 기반은 유지한다.
기업·공고·계약·낙찰 분석과 조달 API 수집은 활성 구성에서 제외했다.
메타데이터 진단용 법령 수집·조회는 전용 Worker에서 재개했다.
이전 구현·계약·전용 테스트는 `archive/procurement_services/`에 보관하며 실행 의존성으로 사용하지 않는다.

통합 구조의 API·MCP·Worker·프런트엔드 이미지를 Compose 운영에 반영했다.
Compose 서비스와 임시 Job의 [자원 상한](verification/compose_resource_limits_2026_10_26.md)을 운영에 적용했다.
Compose 화면과 API 진입점은 [통합 nginx](verification/http_gateway_consolidation_2026_10_26.md)가 제공한다.
계약·작성 입력·Prefect 배포 경로 변경도 [운영 재배포](verification/backend_contract_structure_deployment_2026_10_26.md)했다.
후속 [FastAPI·책임 구조 정리](verification/backend_cleanup_2026_10_26.md)도 API·MCP·Worker 운영에 반영했다.
[재배포 검증](verification/backend_consolidation_deployment_2026_10_25.md)에서 현재 전환 결과를 확인한다.

## 시작

환경변수와 인증은 [환경 설정](deployment/configuration.md), 서비스 조립은
[Compose](deployment/compose.md)를 따른다. 기존 DB·볼륨·체크포인트와 게시 이력은 삭제하지 않는다.

```bash
uv sync --project backend --locked --all-extras --all-groups
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml up --build -d
```

Admin UI는 `http://localhost:8081/`, Prefect는 `/prefect/`, API 문서는
`/admin-api/docs`와 `/runtime-api/docs`다. OpenMetadata는 `metadata`,
예약된 metadata 동기화는 `metadata-orchestration` profile로 실행한다.

## 규격서 처리

[규격서 파이프라인](procurement_specification_processing/pipeline.md)의 manifest에
문서 URI·checksum·분류·산출물 위치를 명시한다. 문서 처리에는 고정한 표준 URI와 checksum도 필요하다.

```bash
uv run --project backend --locked --group orchestration teoria-pipelines specification run --manifest /path/to/manifest.json
```

두 작업은 Prefect Deployment로도 등록한다. 자동 cron은 없으며 `manifest`를 입력해 제출한다.
전용 pool은 Compose `teoria-specification`, K3s `teoria-specification-k3s`, queue는 `documents`다.
기존 `--kind ingestion` 등록 옵션은 CLI 호환 이름이며 이전 수집 작업을 등록하지 않는다.
배포 목록은 [자동 생성 문서](pipelines/deployments.md)를 따른다.

Worker는 외부 parser 실행 환경과 Codex CLI·인증이 필요하다. CLI 설치는 이미지에 고정하고
인증은 실행 환경에서 주입한다. Compose는 별도 `specification-model-auth` volume을
`/home/teoria/.codex`에 연결한다. 기존 호스트 인증을 이미지에 복사하지 않는다. 모델 인증 없이 실제 AI 추출이 완료되었다고 기록하지 않는다.
Compose의 입력 volume은 `/app/specification_inputs`, 산출물 volume은
`/app/specification_artifacts`다. S3는 기존 [파이프라인 설정](procurement_specification_processing/pipeline.md)을 사용한다.

## 법령 수집·조회

법령 전용 pool은 `teoria-legal-information`, queue는 `laws`, 동시 실행 상한은 1개다.
Compose의 `prefect-law-deploy`로 등록하고 `prefect-law-worker`가 실행한다.
법제처 credential은 법령 Worker에만 주입한다. 일일 변경 동기화와 일요일 전체 버전 보정이 활성 상태다.
기존 조달 pool과 Backfill은 계속 중단한다.

인증된 Admin API의 `/v1/admin/legal-information/search`와
`/v1/admin/legal-information/documents/{snapshot_id}`로 검색·원문을 조회한다.
AI 자산 진단도 기준일에 해당하는 법령 snapshot 근거를 사용한다. 법률 적용성이나 공개 승인은 확정하지 않는다.
[법령 운영 안내](pipelines/domains/legal_information.md), [복구 검증](verification/law_recovery_2026_10_25.md)을 따른다.

## 물품 온톨로지 작성

추출기는 원문 수치에 명시된 단위의 누락을 보완하고 최종 귀속 뒤 동일 근거의 중복 속성을 합친다.
이 동작의 회귀·Task 통합 테스트와 실제 모델의 문서 전체 품질 평가는 구분한다.
개선 평가 CLI는 각 실행 전후 Parser 소스·설치 패키지 지문을 검사하며, 실행 중 변경되면 비교를 중단한다.

물품 의미의 작성 입력은 `backend/authoring/ontology_blueprints/goods.yaml`이다.
사용하지 않던 운영 `goods 0.1.0` Draft와 과거 실험·조달 데이터를 [정리했다](verification/retired_data_cleanup_2026_10_26.md).
사용자의 초기화 요청으로 기존 `goods`·`computer_server` 모델과 후보·프로파일·Binding·관찰을 운영에서 삭제했다.
현재 `goods` 1.0.0은 규격서 버전·규격 물품 항목·속성 명세·구성 명세·기타 요구 명세·원문 근거의 Draft다.
분류체계·분류항목·분류 판정·물품 유형·표준 특성·서비스 항목을 보완했다.
납품 범위·공급 역할·적용 문맥·납품자료·물품 연계 명세와 네 샘플 대표 그래프를 추가했다.
객체 17개·속성 93개·관계 50개이며 새 승인 프로파일과 Published 물품 모델은 아직 없다.
기존 처리 06 단계는 원문 표현의 자동 등록·재사용·보류를 지원한다.
실제 샘플에서 유형 31개·특성 14개를 저장했다. [사전 자동 승인](verification/goods_dictionary_auto_approval_2026_10_27.md)을 참고한다.
새 환경에서는 다음 명령으로 Draft만 생성할 수 있다.

```bash
uv run --project backend --locked --extra api teoria apply-ontology-blueprint --manifest backend/authoring/ontology_blueprints/goods.yaml
```

Application DB를 구성한 뒤 실행하고, [Ontology 검토·승인·게시](platform/ontology.md)를 따른다.
추출 표준의 `pipeline_selected_draft`는 Published Ontology가 아니다.
물품 [정규화 프로파일](procurement_specification_processing/normalization_profiles.md)은 Published 개념을
참조해 작성·승인하고 JSON 패키지로 내보낸다. Pipeline은 URI·checksum으로 고정한 패키지를 읽는다.
승인 이력은 Application DB, 문서별 관찰·미해결 후보는 기존 파일/S3 산출물에 둔다.
미해결 후보의 문맥별 묶기·기존 개념 검색과 선택한 제안의 새 프로파일 Draft 생성을 지원한다.
기본 검색은 문자열 유사도와 대상·자료형 필터 기반이다. 별도 Codex 의미 판정과
기존 개념 매핑·신규 Ontology Draft·프로파일 Draft 경로도 제공한다.
자동 승인 평가는 격리 DB의 `goods_eval_` Ontology에서만 실행한다.
전체 표준관리는 `teoria-pipelines specification standard-workflow --manifest ...`로 실행한다.
상위 Prefect Flow가 추출·작성 API·패키지 저장·재적용을 연결하며 승인 대기와 실패에서 같은 실행 ID로 재개한다.
기존 서버 전용 Source·Mapping·Capability와 숫자 관찰 적재 코드는 제거했다.
현재 활성 bundle은 `2026.10.27.3`이며 물품 Capability discovery는 빈 목록이다.
[규격서 물품 모델](architecture/specification_goods_model.md)의 명세·값·유형 참조 계약을 검토한 뒤
새 프로파일과 Runtime 탐색 경로를 작성한다. 기존 처리·조회 결과를 새 모델의 결과로 재사용하지 않는다.
삭제 범위와 새 Draft는 [초기화 기록](verification/specification_goods_reset_2026_10_27.md)에서 확인한다.
원본 규격서와 물품 외 데이터는 유지하고, 이전 물품 모델과 산출물은 백업 후 운영에서 삭제했다.
새 코드가 기존의 조달 artifact를 그대로 사용하면 은퇴한 기능이 재노출될 수 있으므로,
새 Registry로 bundle을 구성하고 검증한 뒤 활성화한다. [Runtime 배포](platform/runtime.md)를 따른다.

## 검증

```bash
uv run --project backend --locked --all-extras --all-groups pytest backend/tests tests/integration
uv run --project backend --locked --extra api teoria validate backend/contracts/runtime
uv run --project backend --locked teoria-pipelines validate backend
uv run --project backend --locked --extra api teoria-pipelines validate-integration backend --platform-registries backend/contracts/runtime
```

계약은 `backend/contracts/`, 작성 입력은 `backend/authoring/`, Prefect 배포 선언은
`deploy/prefect/`가 기준 위치다. 기존 게시 artifact와 DB 이력은 보존한다.

프로젝트 소유권은 [저장소 구조](architecture/repository-structure.md), 남은 제품 결과는
[로드맵](roadmap.md)을 따른다. 저장소 구성 검사와 실제 서비스 배포·모델 품질 검증은 구분한다.


## 선택형 합성 고객 MLOps 예제

`model_operations`는 개인정보 형태의 합성 데이터로 메타데이터 진단과 모델 운영을
함께 검증하는 선택 기능이다. Data DB의 `mlops_demo.customers`와
`mlops_demo.customer_activity`에 각각 600건을 명시적인 데이터 준비 Flow로 넣는다.
이메일은 `example.invalid`, 전화번호는 `010-XXXX-…`, 이름·주소는 가상 값이다.
기존 업무 데이터와 Published Ontology를 바꾸지 않는다.

메타데이터 동기화는 `mlops_demo`를 수집 대상에 포함한다. 테이블을 만들자마자
실행되는 DDL 이벤트 방식이 아니며 기존 Prefect 예약 또는 수동 실행으로 수집한다.
AI 진단은 자산 상세에서 별도로 요청하고 행 데이터 없이 컬럼 metadata와 법령 근거만
사용한다. 합성 데이터의 진단 결과를 실제 개인정보나 법률 적용 확정으로 해석하지 않는다.

Compose 환경 파일에 MLflow DB 암호·MinIO access/secret key·전용 추론 token을 설정하고
`TEORIA_MODEL_OPERATIONS_ENABLED=true`로 활성화한다. 추론 token은 24자 이상이어야 한다.
MLflow 상태는 전용 PostgreSQL volume, 모델 산출물은 전용 MinIO bucket에 저장한다.
다음 명령은 기반 스택이 이미 실행 중인 환경에서 선택 서비스를 추가한다.

```bash
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml --profile mlops build mlflow
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml --profile mlops --profile object-storage up -d mlflow-postgres minio minio-init mlflow model-register model-training-worker model-deployment-worker
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml --profile model-serving up -d --no-deps demo-inference
```

Data migration `096_mlops_demo_customers.sql`은 기존 migration 절차로 별도 적용한다.
기존 Admin·UI 이미지에도 변경을 배포해야 새 메뉴와 관리 API를 사용할 수 있다.
최초 합성 데이터 준비는 Prefect에서 실행하고, `/admin/workflows`에서 메타데이터 동기화를 실행한 뒤
`demo-customer-churn-pipeline` 상위 Flow를 실행한다. 상위 Flow는 실제 Prefect의
데이터 조회·검증 → 학습 → 평가(ROC AUC ≥ 0.65) → MLflow 등록을 연결한다.
기본 `deploy=false`는 등록까지만 수행하며, 실행 시 데모 자동 배포를 명시적으로 선택하면
별도 `teoria-model-deployment` pool의 배포 Deployment를 하위 Flow로 호출해 완료를 기다린다.
배포 대기는 최대 15분이며 시간 초과·상위 실행 취소 시 진행 중인 하위 배포도 취소 요청한다.
학습 전용·특정 버전 재배포 Deployment도 독립 실행으로 유지한다. `/admin/models`에서 등록 버전·평가 지표를, `/admin/serving`에서 배포 상태와 입력값별 예측을 확인한다.
학습은 식별정보·연락처·생년월일·주소·소득·신용점수를 제외한 네 이용 이력 특성만 쓴다.
고객 단위 480/120건 학습·평가 분리와 seed를 고정하며, 합성 지표는 실제 성능 근거가 아니다.

배포 Flow는 모델 artifact checksum과 버전을 고정한 release를 원자적으로 기록한 뒤
전용 추론 프로세스를 재시작한다. 이미지 변경 배포는 별도 Compose 재생성이 필요하다.
준비 상태와 샘플 추론 검증에 실패하면 이전 release를 복원하고 재시작한다.
Docker socket은 전용 배포 Worker만 mount하며 학습 Worker·Admin API는 mount하지 않는다.
추론 프로세스는 MLflow가 관리하는 신뢰된 데모 모델만 적재한다.
`POST /inference-api/predict`는 Admin token과 별도의 `TEORIA_DEMO_INFERENCE_TOKEN` bearer를
사용한다. UI는 인증된 Admin API를 통해 추론하며 전용 token을 브라우저에 전달하지 않는다.

현재 모델 배포 Flow는 Compose 전용이다. K3s에서 모델 학습 Job·서빙 Deployment를 제어하는
어댑터와 운영 클러스터 검증은 후속 범위이며, 기존 Kubernetes Worker를 모델 배포에 사용하지 않는다.

진단 모델의 문맥 크기에 맞춰 `TEORIA_ASSESSMENT_LAW_MAX_DOCUMENTS`(1~5개)와
`TEORIA_ASSESSMENT_LAW_MAX_CHARS`(문서당 1,000~12,000자)를 조절한다.
긴 법령 문서가 잘리면 근거로 채택하지 않고 결과를 partial로 유지한다.
컬럼을 선택해 진단할 수 있으며 입력 제한을 줄였다고 법률 적용이나 공개 가능성을 확정하지 않는다.

모델 운영 화면은 Prefect API의 실제 실행·Task·로그를 조회하며 별도 실행 상태를 복제하지 않는다.
파이프라인별 최근 기록, 상태 필터, 서버 페이지네이션과 실행 상세를 제공한다.
기본 실행 이력에서는 향후 예약을 제외하며 예약·대기 필터에서는 미래 예약도 표시한다.
실행 상세는 운영 목록에 명시한 파이프라인에 속한 Flow만 조회하고 최근 100개 로그와 최대 100개 Task를
표시한다. 하위 Flow의 상태·소요 시간과 원본 Prefect 실행 링크도 제공한다.
모델 목록과 선택 모델의 버전은 MLflow에서 각각 최대 25개씩 cursor 페이지로 조회하며,
평가 지표와 데이터 checksum도 MLflow에서 읽는다. 최신 등록과 실제 서빙 버전은 구분한다.
MLflow run에는 Prefect 학습·상위 실행 ID를 tag로 기록하고 상위 실행 artifact에는
MLflow run·모델 버전·데이터 checksum·배포 실행 참조를 남긴다.
Compose의 `/mlflow/`는 Prefect 운영자 계정으로 인증한 뒤 원본 UI를 새 탭으로 연다.
외부 인증 없이 접근할 수 없으며 운영자 계정은 MLflow 원본 쓰기 작업도 가능한 관리 계정이다.
Prefect 원본 UI는 `/prefect/`에서 제공한다. K3s에는 MLflow ingress를 추가하지 않는다.


## 관리 화면 메뉴

메뉴는 데이터·의미(데이터 자산·온톨로지·의미 연결), 거버넌스(메타데이터 공백·제안 검토),
모델 운영(모델 레지스트리·추론 서비스), 워크플로(파이프라인)로 구성한다.
연결 및 설정·기능 계약은 사이드바 하단의 플랫폼 관리에 둔다.
모델 운영 메뉴는 선택 기능이 활성화되고 관리자 인증이 확인된 환경에서 표시한다.
파이프라인 메뉴는 MLOps 활성화와 독립적으로 제공하며 인증된 관리자 API를 사용한다. 플랫폼 현황에서도 활성 기능의 모델·추론 상태를 확인할 수 있다.
모델 레지스트리·추론 서비스·파이프라인은 데이터 자산과 같은 좌측 검색·선택 목록과 우측 상세 구조다.
모델은 개요·버전·학습 이력, 추론 서비스는 개요·스키마 기반 추론 테스트·배포 이력으로 구분한다.
파이프라인은 `workflow_management`가 소유하며 개요·스케줄·실행 이력을 제공한다.
`/v1/admin/workflows`는 Prefect의 상태를 조회하며, 메타데이터 동기화·법령 수집·규격서 처리와
선택형 모델 상위 Flow만 운영 목록에 노출한다. 초기화·학습 전용·개별 재배포는 Prefect에 유지한다.
`metadata_admin`은 수동 실행·실행 중지·스케줄 활성화와 중지·기존 Cron 주기 및 시간대 변경을
요청할 수 있다. 규격서 실행은 기능 소유 입력 모델로 검증하며 parser 실행 파일 override는 받지 않는다.
취소는 Prefect에 CANCELLING 상태를 요청하고 실제 최종 상태를 다시 조회한다.
스케줄 변경은 Prefect가 검증·적용하고 미래 자동 예약을 다시 계산하며 진행 중 실행은 유지한다.
스케줄 추가 및 interval/rrule 주기 편집은 원본 Prefect에서 관리한다. 배포 YAML 재등록은 운영 화면에서
변경한 스케줄을 선언값으로 덮어쓸 수 있으므로 지속할 주기는 `deploy/prefect/`에도 반영해야 한다.
조회 전용 계정은 변경 작업을 수행할 수 없다. 구형 모델 운영 pipeline API는 호환 경로로 유지한다.
기존 `/admin/model-operations` 주소는 query와 fragment를 보존해 `/admin/models`로 이동한다.
모바일에서는 탐색 메뉴를 작업 화면 위에 열고, 메뉴 선택 또는 배경 클릭으로 닫는다.

현재 원문 등록 319개는 표준 개념 사전이 아니다. 원문 등록 ID는 source_term_ref로 연결하며 표준 개념 참조를 대체하지 않는다.

원문 등록과 별도로 표준 정의의 불변 개정·범위별 의미 매핑·승인 재사용을 구현했다. 최초 인버터 유형·정격출력 정의 2개와 매핑 2개를 적용했다. [물품 사전](platform/goods_dictionary.md)을 따른다. 단위 환산과 전체 사전 정비는 후속 작업이다.

네 규격서 전체 처리·사전 후보 수정·남은 구성 관계 문제는 [실행 검증](verification/goods_four_sample_pipeline_2026_10_27.md)에 기록했다. 4개 모두 partial이며 원문 등록이 의미 정렬 완료를 뜻하지 않는다.
