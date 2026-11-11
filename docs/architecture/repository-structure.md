# 저장소 구조와 소유권

Teoria는 플랫폼·업무 도메인·앱으로 코드를 나눈다.
변경 전에 아래 표에서 소유자를 정한다. FormatID는 플랫폼 전체가 아닌 업무 앱이다.
플랫폼은 데이터·Ontology·향후 AI 영역과 별도 MLOps 영역으로 구분한다.
`ai/`는 예약 폴더이며 AIP가 구현되었다는 의미가 아니다.

## 실행 코드

```text
backend/src/teoria/
  platform/
    data/
      operations/          수집 계약·실행·원본·checkpoint
      metadata/            OpenMetadata·진단·검토·적용
    ontology/
      authoring/           업무 개념 작성·승인·게시
      bindings/            개념과 자산·용어·API 연결
      contracts/           Source·Mapping·Capability 검증·artifact
      runtime/             게시 계약 실행·Context
    ai/                    향후 AIP 예약 영역; README만 있고 미구현
    mlops/                 모델 실행 계약·Flow·서빙 배포 참조·운영 API
    access_control/        인증·권한·정책
    workflow_management/   Prefect 실행·스케줄 관리
  domains/
    goods/
      contracts.py         물품 처리 입력·산출물 값 계약
      runtime.py           승인 관찰의 불변 조회 artifact·Runtime handler
      data_processing/     파싱·추출·저장·문서 목록·평가
        tasks.py           원본 준비 → 파싱 → 추출 → 검증·저장
        flows.py           추출 실행 순서
      expression_links/    원문 표현 등록·게시 개념 연결
      normalization/       후보·프로파일·검토·고정 표준 적용
        candidates/        후보 선정·그룹화·프로파일 기반 연결 제안
        meaning_proposals/ 의미 후보·문서 해석 승인·감사
        application/       고정 프로파일·승인 해석의 별도 적용
        legacy_dictionary/ 과거 v1 결과 재현
      workflows/           Flow·Task I/O·실행 순서·승인 대기·재개
      notice_collection/   명시적 규격서 처리 입력 준비
    legal_information/     법령 수집·검색
  apps/
    formatid/              업무 HTTP API·입력 권한·결과 조합
  integrations/            Provider·Codex·OpenMetadata·MLflow·Prefect·DB 연결
  entrypoints/             API·MCP·CLI 프로세스 진입점
    composition/           플랫폼·도메인·앱 객체 조립
```

프런트엔드의 `shell/`은 전체 플랫폼 화면 틀이고 `apps/`는 FormatID 같은 업무 앱이다.
Shell은 접근 경계와 화면 틀을 조립한다. 경로는 `shell/routes.tsx`, 메뉴 경로는 `shell/navigation.ts`가 관리한다.
업무 API·응답 타입은 소유 화면 옆 `api.ts`에 둔다. 서버 조회는 TanStack Query로 관리한다.

```text
frontend/src/
  shell/                   플랫폼 화면 틀·라우팅·메뉴·홈
  platform/
    data/metadata/         자산·진단·제안 화면
    ontology/              authoring·bindings·runtime 화면
    ai/                    향후 AIP 예약 영역; 실행 화면 없음
    mlops/                 별도 모델 학습·등록·서빙 화면
    access_control/        인증·연결 상태
    workflow_management/   공통 실행·스케줄 화면
  domains/goods/           물품 표현 연결 화면
  apps/formatid/           규격서 처리·결과 분석 화면
  api/                     HTTP 전송·인증 오류·Query 공통 정책
  components/, lib/        실제 공유하는 UI와 기반 코드
```

## 어디를 수정하나

| 변경 | 소유 위치 |
|---|---|
| 공통 수집 실행·checkpoint | `platform/data/operations/` |
| 물품 문서 파싱·원문 근거·추출 결과 | `domains/goods/data_processing/` |
| 물품 의미 후보·프로파일·표준 적용 | `domains/goods/normalization/` |
| 표현과 게시 개념의 연결 | `domains/goods/expression_links/` |
| 개념·속성·관계의 게시 정책 | `platform/ontology/authoring/` |
| 용어·자산·API·Capability의 의미 연결 | `platform/ontology/bindings/` |
| FormatID API·결과 조합 | `apps/formatid/` |
| 외부 고객 이탈 샘플 이미지·소스 | `archive/customer_churn/` |
| 서비스 연결·주입·lifespan | `entrypoints/composition/` |

## 업무 앱과 모델 운영의 경계

화면·HTTP API·컨테이너가 있다는 이유로 `apps/`에 두지 않는다. 소유하는 업무 책임으로 판단한다.

| 영역 | 소유 책임 |
|---|---|
| `platform/data/` | 데이터 수집·처리·품질·메타데이터 기반 |
| `platform/ontology/` | 업무 의미 정의·Binding·승인·게시·Runtime |
| `platform/mlops/` | 모델 공통 실행 계약·학습·서빙 배포·중지·복구·상태 조회 |
| `platform/ai/` | 향후 AI 업무 실행 기반의 예약 영역; 현재 미구현 |
| `domains/<domain>/` | 해당 업무의 입력 해석·판단·승인·적용 규칙 |
| `apps/<app>/` | 사용자가 업무를 수행하도록 도메인과 플랫폼 기능을 조합하는 HTTP API |

모델마다 앱 패키지를 만들지 않는다. 모델의 알고리즘·특징·임계값은 외부 이미지나 소유 업무에 두고,
MLOps는 이미지 digest·모델 버전·실행 입력·배포 상태를 관리한다. 추론 결과를 해석해 업무 조치를
결정하는 규칙은 도메인에, 사용자의 조회·검토·승인 경험은 앱에 둔다.
MLflow의 모델 목록·평가 지표·학습 파라미터와 서빙 배포 목록은 각각의 소유 API에서 조회한다.
단일 기본 모델이나 특정 업무의 파라미터 이름을 플랫폼 조립 코드에 고정하지 않는다.

[Foundry 모델 통합](https://www.palantir.com/docs/foundry/model-integration/models)과
[Functions on models](https://www.palantir.com/docs/foundry/model-integration/functions-on-models)의
모델 배포와 애플리케이션 소비 구분을 참고한다. Teoria는 공통 운영만 MLOps가 소유하며,
Foundry와 동일한 모델·Ontology 연결 기능을 구현했다는 의미는 아니다.

## 의존성

`apps → domains → platform` 방향을 따른다. 외부 연결은 `integrations`, 객체 조립은 `entrypoints`가 맡는다.
플랫폼은 도메인·앱·예제를 역으로 import하지 않는다.
보관된 고객 이탈 샘플은 독립 이미지로 빌드하며 플랫폼 실행 코드에서 import하지 않는다. 실행 코드가 `entrypoints`를 import하지 않는다.
기능 간 의존성은 순환하지 않는다. 이 규칙은 `backend/tests/architecture/`에서 검사한다.

Workflow 플랫폼은 실행할 업무 목록이나 업무별 입력 규칙을 소유하지 않는다.
허용 목록은 `entrypoints/composition/workflow_catalog.py`에서 선택하고 실행 입력 정책과 함께 주입한다.

다른 모듈은 공개 값 계약과 서비스 인터페이스를 사용한다. 앱에 SQL을 두지 않는다.
물품 Workflow는 소유 모듈의 후보·연결 판단을 호출하며, 의미 판단 규칙을 직접 구현하지 않는다.
`normalization/`·`expression_links/`는 `workflows/`를 역으로 import하지 않는다.
Worker는 Ontology 저장소를 직접 변경하지 않고 인증된 Admin HTTP API를 사용한다.
`common`·`shared`·`utils` 폴더나 이름만 바꾼 이전 namespace의 forwarding 파일은 만들지 않는다.
클래스·함수마다 파일을 나누지 않는다. 같은 책임은 함께 두고 정책 없는 생성·전달 계층을 추가하지 않는다.
수집 공통 기반은 `platform/data/operations/`의 `schema.py`·`execution.py`·`checkpoints.py`·`persistence.py`에서 읽는다.
별도 설치 패키지는 둘 이상의 독립 프로젝트가 실제 소비할 때만 만든다.

## 코드 밖의 기준 위치

| 위치 | 내용 |
|---|---|
| `backend/contracts/runtime/` | Runtime Source·Object·Mapping·Capability 작성 계약 |
| `backend/contracts/ingestion/` | Pipeline Connector 계약 |
| `backend/config/` | 운영 입력·공통 Prefect 등록과 기본 파라미터 |
| `backend/authoring/` | 작성 입력·Ontology 이관 |
| `backend/migrations/application/`, `backend/migrations/data/` | 저장소별 순번 migration |
| `deploy/compose/`, `deploy/kubernetes/` | Compose·공통 Kubernetes 배포·pool·queue·Job 정책 |
| `deploy/kubernetes/overlays/k3s/` | K3s 전용 overlay·EC2 설치 설정 |
| `backend/tests/platform/`, `domains/`, `apps/` | 소유 코드에 대응하는 테스트 |
| `backend/tests/integration/` | 백엔드 모듈 간 연동·실환경 검사 |
| `tests/documentation/` | 문서 링크·목차 검사 |
| `archive/kory_parser/` | 별도 설치·실행하는 문서 파서·사용 문서·라이선스 |
| `archive/kory_parser_evaluation/` | 파서 회귀 테스트·평가·벤치마크·Codex 개선 실행기 |

Python 의존성과 잠금은 `backend/pyproject.toml`, `backend/uv.lock` 한곳에서 관리한다.
역할별 이미지·권한은 유지한다. 기존 URL·CLI·산출물 ID·적용 migration·게시 artifact는 구조 변경으로 수정하지 않는다.

[아키텍처](overview.md) · [개발 안내](../development.md)
