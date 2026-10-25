# Teoria 시작과 역할별 작업

현재 활성 업무는 명시 입력 규격서의 파싱·정보 추출·표준 후보 관리다.
Ontology·Binding·Source·Mapping·Capability·Runtime·Context·OPA와 OpenMetadata 기반은 유지한다.
기업·공고·계약·낙찰 분석과 조달 API 수집은 활성 구성에서 제외했다.
메타데이터 진단용 법령 수집·조회는 전용 Worker에서 재개했다.
이전 구현·계약·전용 테스트는 `archive/procurement_services/`에 보관하며 실행 의존성으로 사용하지 않는다.

## 시작

환경변수와 인증은 [환경 설정](deployment/configuration.md), 서비스 조립은
[Compose](deployment/compose.md)를 따른다. 기존 DB·볼륨·체크포인트와 게시 이력은 삭제하지 않는다.

```bash
uv sync --locked --all-packages --all-groups
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml up --build -d
```

Admin UI는 `http://localhost:8081/`, Prefect는 `/prefect/`, API 문서는
`/admin-api/docs`와 `/runtime-api/docs`다. OpenMetadata는 `metadata`,
예약된 metadata 동기화는 `metadata-orchestration` profile로 실행한다.

## 규격서 처리

[규격서 파이프라인](procurement_specification_processing/pipeline.md)의 manifest에
문서 URI·checksum·분류·산출물 위치를 명시한다. 문서 처리에는 고정한 표준 URI와 checksum도 필요하다.

```bash
uv run --locked --package teoria-pipelines teoria-pipelines specification run --manifest /path/to/manifest.json
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

물품·구성품·규격 요구조건을 위한 초기 blueprint는
`platform/ontology_blueprints/goods.yaml`이다. 현재 운영에는 인증된 Admin API로 `goods 0.1.0` Draft를 등록했다.
새 환경에서는 다음 명령으로 Draft만 생성할 수 있다.

```bash
uv run --locked --package teoria-platform teoria apply-ontology-blueprint --manifest platform/ontology_blueprints/goods.yaml
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
Semantic Binding 및 Runtime Mapping 연결은 아직 구현하지 않았다.
물품 검색·비교 Capability와 AI 질의 handler도 별도 구현 대상이다.
현재 활성 Registry는 공통 타입만 제공하므로 Capability discovery는 빈 목록을 반환한다.
배포된 bundle은 `2026.10.25.1`이며 `goods 0.1.0`은 검증된 Draft로 등록했다.
실제 배포·인증·모델 준비 상태는 [배포 검증 기록](verification/goods_focus_deployment_2026_10_25.md)을 따른다.
이전 게시 Ontology와 Runtime artifact는 수정하지 않는다.
새 코드가 기존의 조달 artifact를 그대로 사용하면 은퇴한 기능이 재노출될 수 있으므로,
새 Registry로 bundle을 구성하고 검증한 뒤 활성화한다. [Runtime 배포](platform/runtime.md)를 따른다.

## 검증

```bash
uv run --locked --package teoria-platform pytest platform/tests
uv run --locked --package teoria-platform teoria validate platform/registries
uv run --locked --package teoria-pipelines pytest pipelines/tests
uv run --locked --package teoria-pipelines teoria-pipelines validate pipelines
uv run --locked --package teoria-pipelines --group validation teoria-pipelines validate-integration pipelines --platform-registries platform/registries
```

프로젝트 소유권은 [저장소 구조](architecture/repository-structure.md), 남은 제품 결과는
[로드맵](roadmap.md)을 따른다. 저장소 구성 검사와 실제 서비스 배포·모델 품질 검증은 구분한다.
