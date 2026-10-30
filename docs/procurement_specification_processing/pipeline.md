# 규격서 파이프라인과 Codex 사용

원본 입력부터 결과 저장까지 아래 순서로 처리한다. 실행은 Prefect, 원문 해석은 파서와 Codex,
표준관리에서는 미해결 사전 의미도 Codex가 판단한다. 검증·승인 정책·표준 적용·저장은 코드가 담당한다.

## Prefect 실행 입력과 기본값

`Deployments → specification-standard-management → Run → Parameters`에서 입력한다.
기본 입력은 `classification_code`(세부품명 10자리, 필수)와 `target_specifications`(기본 30)다.
나머지는 배포 기본값을 사용하며 실행할 때 바꿀 수 있다. 실제 Flow 인자 이름은 다음과 같다.

```json
{
  "classification_code": "4321150102",
  "target_specifications": 30,
  "selection": {
    "strategy": "latest",
    "lookback_days": 365,
    "max_notices_to_scan": 300
  },
  "management": {
    "purpose": "dictionary_management",
    "auto_apply": true,
    "force_review": false,
    "holdout_documents": 5,
    "minimum_development_documents": 5,
    "max_held_source_ids": 0
  },
  "execution": {
    "concurrency": 2,
    "model_concurrency": 4,
    "model_timeout_seconds": 180
  }
}
```

| 설정 | 동작 |
|---|---|
| `selection.date_from`, `date_to` | 게시일 범위. 생략하면 실행일 기준 최근 365일, 날짜 끝날 포함 |
| `management.purpose` | `dictionary_management`(기본 사전 관리), `quality_evaluation`(읽기 전용 평가) |
| `management.baseline_dictionary` | 기준 사전의 URI·sha256. 평가는 필수. 사전 관리는 생략하면 현재 승인 사전을 사용하며, 지정하면 현재 사전과 일치해야 함 |
| `management.force_review` | 기본 `false`: 확인된 문맥 재사용. `true`: 기존 항목도 재검토. 사전 관리에만 사용 |
| `management.auto_apply` | 별도 문서 검증·의미 퇴행 없음·보류 수 한도를 통과한 변경 묶음만 자동 반영 |
| `execution.run_id` | 생략하면 Prefect 실행 ID로 생성. 직접 지정하면 동일 입력의 선정 목록 재사용 |
| `execution.artifact_root` | 생략하면 Worker의 `TEORIA_SPECIFICATION_ARTIFACT_ROOT`, 기본 `s3://teoria-artifacts` |
| `execution.model` | 생략하면 Worker의 Codex 설정 사용 |

분류를 지정해 보관된 물품 공고 DB의 최신 유효 차수를 게시일 내림차순으로 최대 300개 확인한다.
취소·다른 분류·게시일 없음은 대상에서 제외한다. 정기 공고 수집이나 보류된 수집 배포를 활성화하지 않는다.
분류가 여러 개인 공고는 특정 첨부에 한 분류를 임의로 적용하지 않고 제외한다.
파일명에 규격·시방·사양·specification이 있는 지원 형식만 후보로 삼고, 다운로드·형식 서명·해시 중복 검사를 한다.
이는 파일명 기반 후보 선정이며 본문이 실제 규격서인지 전부 판정했다는 뜻은 아니다.
ZIP이나 이름만으로 확인할 수 없는 문서는 자동 선정하지 않는다.

목표 수는 **공고 수가 아닌 중복 제거된 확보 파일 수**다. 독립된 파일 두 개는 두 개로 센다.
탐색 범위에서 목표 수를 채우지 못하면 확보한 수로 진행하고 사유를 남긴다. 파싱·추출 후 완료 문서 수와 부족 수를 따로 기록한다.
파일명 기준은 규격서처럼 보이는 첨부 후보 선정이며 본문 적격성을 보장하지 않는다. 01단계에서 명확한 공고문·빈 양식은 `not_specification`으로 제외하고, 혼합 문서는 기술·납품 요구 구간을 보존한다. 제외 문서는 확보 후보 수에는 포함되지만 추출·평가 완료 수에는 포함되지 않는다. 제외된 수만큼 자동 추가 확보하는 반복은 아직 없다.
부분 추출 문서는 품질 통과 수에 포함하지 않는다. 같은 공고의 첨부는 구축용·평가용에 나누어 넣지 않는다.
기본값은 완료 문서 중 구축용 최소 5개·평가용 최소 5개이며 부족하면 변경안을 저장하되 자동 반영은 보류한다.
실제 모델 기반 의미 검증이며 사람의 정답 평가나 전체 정확도 향상을 증명하지는 않는다.

`dictionary_management`는 사전이 비어 있든 기존 내용이 있든 같은 처리 경로를 사용한다.
기존 의미·문맥은 재사용하고 새 표현·변경 문맥을 판단해 필요한 정의·매핑을 추가·개정한다.
기존 `initial_dictionary`·`incremental_update` 입력도 이 이름으로 변환한다. 전체 재검토는 이름으로 결정하지 않고 `force_review`로 명시한다.
`quality_evaluation`은 고정 기준 사전에 연결한 결과를 저장하며 사전 정의·매핑을 변경하지 않는다.
`auto_apply: false`는 사전 관리 변경안을 저장하고 반영하지 않는다.

문서를 직접 지정하려면 같은 설정 객체를 `manifest`에 넣고 `documents` 목록을 추가한다.
이 경우 공고 DB를 조회하지 않고 입력 파일 순서로 처리한다. 기존 `SpecificationRun` 형식의 `manifest`도 유지한다.
`manifest`와 개별 Flow 파라미터를 동시에 수정해 제출하면 오류로 처리한다.
관리 API도 새 설정 객체를 기존 `manifest` 필드로 받는다. 이전 설명의 `request`는 실제 인자 이름이 아니다.
분류 없는 기존 샘플은 기존 명시적 문서 manifest 경로를 사용한다.

선정·준비 산출물은 `specification_processing/<run_id>/`의 `document_selection.json`,
`management_batch.json`, `development_checkpoint.json`, `validation_checkpoint.json`에서 확인한다.
00–05 전체 추출을 먼저 보존하고, 구축·검증 입력을 분리한 다음 `<run_id>_apply`에서 기존 처리·사전 관리·완료 기록을 실행한다.
최종 실행의 Data DB에도 준비 산출물 참조와 확보·평가 요약을 남긴다. 새 배포나 별도 Flow를 만들지 않는다.
DB에 보관된 공고가 오래됐으면 그 범위 내 최신순이며, 외부 사이트의 현재 최신 공고를 보장하지 않는다.

## 두 흐름과 공통 단계

| 처리 방식 | 목적 | Prefect Flow |
|---|---|---|
| 표준관리 | 추출 표준과 의미 후보를 관리하며 처리 | `procurement-standard-management` |
| 문서처리 | 지정한 고정 표준/프로파일로 처리 | `procurement-document-processing` |

두 방식은 같은 00–08 단계를 공유한다. 사전 전용 Flow는 없다.

| 단계 | 하는 일 | Codex |
|---|---|---|
| **00 원본 준비** | 파일 보관·해시 확인, 지정한 checkpoint 검증 | 사용 안 함 |
| **01 문서 파싱·본문 역할 분류** | 파서로 본문·표·위치 추출 후 규격·혼합 문서·양식·공고 및 구간 역할 판정 | **본문 분류에 사용** |
| **02 물품·계층·관계 추출** | 기준 목록, 하위 대상, 구성·작업·연계 관계 해석 | **사용** |
| **03 요구조건 추출** | 속성·값·단위·조건 분리, 누락 후보 재추출 | **사용** |
| **04 대상·역할·범위 해석** | 어느 대상의 조건인지, 납품/지원/기보유·개별/전체 범위 해석 | **사용** |
| **05 검증·저장** | 원문·참조·관계 유형 검사, 추출·보류 보존 | 사용 안 함 |
| **06 표준 사전 관리·연결** | 문맥 비교·과거 근거 조회·정의와 매핑 개정·검증·반영 | **표준관리의 신규·변경 문맥에 사용** |
| **07 표준 적용** | 고정 표준/프로파일 적용, 사전 개념 연결 결과 저장 | 사용 안 함 |
| **08 보고서 저장** | 구성 트리·속성·근거·보류 표시, 산출물 저장 후 완료 기록 | 사용 안 함 |

Flow 코드가 [실행 순서](../../backend/src/teoria/features/specification_processing/flows.py),
Task 코드가 [단계 경계](../../backend/src/teoria/features/specification_processing/tasks.py)의 기준이다.

## Codex를 사용하는 단계

| 단계 | 호출 내용 | 검증·재시도 |
|---|---|---|
| 01 | 본문으로 문서·구간 역할과 인접 문장 연결 판정 | 원문 ID·중복 검사. 불확실·분류 실패는 원문을 유지하고 보류 |
| 02 | 구매 기준 목록을 찾고, 이를 고정한 뒤 상세 대상·관계 추출 | 목록/관계 오류는 한 번 재판정. 관계 미해결은 보류 |
| 03 | 원문 조각별 요구조건 추출 | 누락 후보 구간을 한 차례 추가 처리 |
| 04 | 속성의 대상·역할·범위 판정 | 잘못된 ID·근거·응답만 한 번 재판정. 불명확하면 unknown 유지 |
| 06 | 표준관리의 미해결 표현에 기존 개념 동등 연결 또는 새 로컬 정의 판단 | 별도 Codex 재검증과 코드 검증 통과 시 승인 정책에 따라 반영, 불명확·충돌은 보류 |

한 단계가 한 번의 모델 호출이라는 뜻은 아니다. 문서 크기·구간 수·재판정에 따라 달라진다.
Codex는 제공한 원문과 문맥으로 JSON을 반환한다. 추론 호출에서 도구·파일·네트워크·위임을 금지하고,
코드가 스키마·원문 일치·ID·유형을 검사한다. 파이프라인 자체가 Skill을 읽어 실행하지는 않는다.

모델·동시 실행·시간 제한은 실행 입력으로 지정한다. 유효한 extraction_checkpoint를 재사용하면
01–04의 새 파싱·추론을 건너뛰므로 새 추출 품질 검증으로 표시하지 않는다.

## 엔티티·속성·관계 계약

### 물품과 관계

- 물품·구성품 외에도 소프트웨어·작업·문서·그룹을 추출한다. 대상 수가 납품 물품 수는 아니다.
- `대상 → in_procurement_scope → 구매 범위`와 `하위 → component_of → 상위`는 다른 관계다.
- 원문 구성 근거가 있으면 두 관계를 함께 보존한다. 단순 표·절 배치로 구성을 만들지 않는다.
- 작업은 `activity → service_for → 작업 대상`으로 표현한다. 문서·작업을 장비 부품으로 넣지 않는다.
- 물리적 내부 포함은 명시 근거가 있어야 한다. 수량을 상위에서 하위로 전파하지 않는다.

잘못된 관계를 코드가 임의로 뒤집지는 않는다. 재판정 후에도 해결되지 않은 관계,
불확실한 동일 대상·유형·순환은 `held_relations`에 원래 방향·근거·사유를 남긴다.
엔티티·속성은 유지한다. 기존 checkpoint의 잘못된 작업/구성 유형은 재추출을 요구한다.

### 속성과 근거

원문 값·단위·연산·한정 조건을 보존한다. 모델명·기보유 제품·지원 한도를 신규 납품 성능으로 바꾸지 않는다.
수치 단위 보완은 같은 구절의 값 바로 뒤에 명확히 붙은 알려진 단위만 사용한다.
최종 귀속 후 대상·값·조건·역할·범위·원문 근거가 모두 같은 관찰만 합치고 원래 ID를 남긴다.
다른 위치의 반복 진술이나 상충 조건은 보존한다.

03·04는 절·표·상위 문맥을 선택해 전달한다. 전체 원문을 처음부터 품목명 목록으로 걸러내지는 않는다.
파서에서 사라진 정보는 추출기가 복원했다고 표시하지 않는다. 기본 파싱은 OCR을 사용하지 않는다. 텍스트가 없는 스캔은 `needs_ocr`, 파서 프로세스 오류는 안전한 예외 유형과 함께 별도 기록한다.

## 사전과 표준 적용

06 단계는 원문에 나온 표현을 조회·등록하고, 승인된 의미 매핑이 있으면 표준 정의를 가져온다.
원문 명칭이 없는 속성은 내부 영문 후보명을 원문 표현처럼 등록하지 않는다.
새 동의어·표준 의미를 이름 유사도만으로 확정하지 않는다.

표준관리 모드에서는 문서가 들어올 때마다 기존 사전과 문맥을 비교한다.
현재 승인 정의 개정으로 이미 확인된 문맥은 재사용한다. 숫자만 달라진 경우 같은 문맥으로 인식할 수 있으며,
표현·소유 물품·역할·범위·조건·단위가 달라지면 관련 과거 추출 결과를 Data DB의 참조로 찾아 checksum을 확인한다.
Codex는 현재 문서와 관련 과거 근거를 함께 보고 기존 개념 연결, 새 정의, 정의 개정과 영향 매핑을 판단한다.
별도 검증을 통과한 변경 묶음만 인증된 Admin API로 원자적으로 반영한다.
`dictionary_meaning_auto_approve: false`이면 변경안을 저장하고 자동 반영하지 않는다.
과거 근거 누락·checksum 불일치·판정 충돌은 보류하고, 해당 문맥에 기존 의미를 임의로 적용하지 않는다.

문서처리 모드는 지정한 `dictionary_standard` URI·checksum의 고정 사전을 사용하고 이 증분 관리 경로를 실행하지 않는다.
로컬 사전 승인은 Published Ontology 게시가 아니다.

07 단계는 다음 두 연결을 구분해 저장한다.

| 연결 | 결과 |
|---|---|
| 사전의 승인된 개념 매핑 | `dictionary_meanings`, `dictionary_concept_ref`, 정의 개정·매핑 ID |
| 고정 표준/프로파일 적용 | 표준 버전·URI·checksum과 관찰별 적용/보류 |

사전 개념 ID와 Published Ontology Stable Concept ID는 다르다.
기본 `source_only`는 미확정 의미를 후보로 남긴다. 분류값만으로 분야 규칙을 켜지 않는다.
과거 `server` 규칙은 명시적인 호환 설정이며 현재 운영 물품 사전이나 활성 서버 Capability를 뜻하지 않는다.
상세 내용은 [사전](../platform/goods_dictionary.md)과 [프로파일](normalization_profiles.md)을 따른다.

사전 관리는 처음 입력한 문서와 이후 추가 문서에 같은 06 단계를 사용한다. 여러 문서의 extracted.json을 함께 입력할 수도 있다.
`dictionary_reconcile`은 이미 확인된 문맥도 다시 검토하는 옵션이며, `dictionary_corpus`는 추가 근거를 지정할 때 사용한다.
사전 안내의 `dictionary-maintain` 명령으로 묶음 개정도 실행할 수 있다.
개정과 영향 매핑을 함께 검증·반영하고 사전 스냅샷을 내보낸다. 문서처리는 `dictionary_standard` URI·checksum으로 사전 버전까지 고정할 수 있다.

## 저장 위치와 최소 산출물

| 산출물 | 내용 |
|---|---|
| `sources/` | 원본 파일 |
| `extracted.json` | 표준화 전 대상·관계·속성·원문·보류 |
| `dictionary_candidates.json` | 원문 표현 등록 후보와 근거 |
| `dictionary_bindings.json` | 등록·재사용·보류 판정 |
| `dictionary_semantic_decisions.json` | Codex 정의·매핑 판단, 재검증·자동 승인/제안/보류와 ID |
| `source_term_alignment.json` | 원문 등록과 표준 개념 연결 |
| `meaning_candidates.json` | 표준관리의 미해결 의미 후보 |
| `normalized.json` | 고정 표준 적용과 사전 연결 결과 |
| `index.md` | 사람이 보는 트리·속성·근거·보류 보고서 |

운영 본문은 MinIO의 `s3://teoria-artifacts/specification_processing/<run_id>/`에 저장한다.
화면 업로드 원본은 `s3://teoria-artifacts/specification_inputs/`에 저장한다.
`file://` 저장은 명시적으로 지정한 개발·테스트 경로로만 사용하며 운영 기본값은 S3다.
표준관리의 로컬 표준 초안은 `standards/<version>/standard.json`에 별도로 저장한다.
Data DB에는 실행·문서별 요약·URI·checksum만 저장한다. [저장소 기준](../pipelines/database.md)을 따른다.

다른 내용으로 같은 객체 키를 덮어쓰지 않는다. 모든 산출물 저장 후 완료/부분완료 상태를 기록한다.
파싱·추출·판정의 선택된 중간 결과는 `diagnostics/<종류>_<sha256>.zip`으로 묶어 MinIO에 저장한다.
모든 S3 업로드는 읽기 재검증으로 SHA-256 일치를 확인한다. 정상·일반 실패 종료 시 진단 저장이 성공하면 로컬 작업 폴더를 삭제한다.
저장·검증 실패 또는 원본 업로드 확인 전 실패 시 작업 폴더를 보존하고 오류에 위치를 남긴다.
임시 프롬프트·스키마·캐시는 진단 묶음에서 제외한다. 강제 종료 시 정리는 보장하지 않는다.
일반 실행의 원본·최종 산출물·진단 묶음은 보존하며 실행 종료만으로 MinIO 객체를 지우지 않는다.

## 실행 방법

화면 사용은 [규격서 분석 안내](../platform-guide.md#규격서를-처리하려면)를 따른다. CLI는 다음과 같다.
실행 전에 Data DB·Prefect·Codex 인증·파서 Python·Admin 작성 API를 [환경 설정](../deployment/configuration.md)대로 준비한다.

```json
{
  "run_id": "specification_example_01",
  "mode": "standard_management",
  "model": "gpt-6.1-sol",
  "model_timeout_seconds": 600,
  "artifact_root": "s3://teoria-artifacts",
  "documents": [{
    "document_id": "equipment_01",
    "source_uri": "s3://teoria-artifacts/specification_inputs/<업로드_문서_ID>.hwpx",
    "filename": "equipment.hwpx"
  }]
}
```

```bash
uv run --project backend --locked --group orchestration \
  teoria-pipelines specification run --manifest /data/run.json
```

컨테이너 실행에서는 컨테이너가 읽을 수 있는 경로를 사용한다.
분류가 없으면 생략하고, 있으면 검증된 10자리 값을 `classification_code`로 지정한다.
`document_processing`에는 `standard.uri`와 파일 전체의 `standard.sha256`이 필수다.
입력·코드가 달라지면 새 run_id를 사용한다. 저장된 실행의 다른 내용 덮어쓰기는 거부한다.

## 선택적인 상위 표준 작성

`procurement-standard-workflow`는 기존 처리와 Admin 작성 API를 연결하는 상위 조립이다.
새 문서 처리 방식이 아니며 승인된 기준 프로파일이 필요하다.
이 경로를 명시적으로 실행하면 Admin API의 의미 제안에서도 Codex를 사용한다.
일반 06 사전 조회·07 표준 적용 자체의 모델 호출과 혼동하지 않는다.
[프로파일·상위 작성 절차](normalization_profiles.md)를 따른다.

## 검증 범위와 남은 한계

실행 완료, 원문 적합성, 업무 의미 정확도는 구분한다. Prefect Completed여도 문서는 partial일 수 있다.
현재 원본 처리와 Worker 반영은 [운영 검증](../../archive/documentation/verification/goods_relation_deployment_2026_10_28.md),
고정 원본 비교의 한계는 [평가 기록](../../archive/documentation/verification/goods_relation_repair_2026_10_28.md)에 있다.
별칭·동일 대상·조건 귀속·표준 의미 확대와 새 물품 Runtime 연결은 후속이다.

추출 개선은 [평가 절차](evaluation.md)를 따른다. 자동 공고 첨부 수집·참가자격 판단은 연결하지 않는다.
이전 실행 설계는 [보관 기록](../../archive/documentation/procurement_specification_processing/pipeline_2026_10_27.md)에서만 확인한다.

## 증분 관리 산출물

- `dictionary_incremental.json`: 재사용·반영·보류 결과와 사유.
- `dictionary_related_context.json`: 관련 과거 문서와 불러온 추출 참조.
- `dictionary_history/`: 영향 검증에 사용한 과거 관찰 부분집합.
- `dictionary_release.json`: 현재 실행에 적용하는 승인된 사전 스냅샷.

변경이 필요하면 maintenance 산출물에 변경안·검증·적용 결과를 저장한다.
Data DB에는 파일 참조와 확인된 문맥의 해시·정의 개정 ID를 저장하며 완료 실행만 재사용한다.
과거 파일 조회는 최대 100개이며 영향이 넓어지면 한 번 추가 조회·재판정하고 미해결은 보류한다.

## 본문 역할·품질·근거 가용성

본문 분류는 원문을 변경하지 않는다. 제목·작성 지침·입찰 절차·문의 구간은 요구조건 추출에서 제외하되 원문과 판정은 보존한다.
불확실한 구간은 계속 전달하며, 실제 납품·설치·교육·보증·제출 문서 의무는 단순한 제목이나 문서 명칭으로 대체하지 않는다.
인접 노드로 끊긴 문장은 같은 절의 문맥으로 전달한다. 숫자·원문 offset·근거 문자열을 합성하거나 자동 수정하지 않는다.

누락 결과는 기술 요구·납품 의무·대상 명칭·미분류별로 기록하고, 관계 보류도 종류별로 기록한다.
속성 역할 unknown과 범위 unknown, 대상 미배정을 각각 기록한다. 기존 보류 관계를 자동 확정하거나 품질 게이트를 완화하지 않는다.

사전의 `dictionary_evidence_corpus`는 이번 실행에서 이미 확보된 과거 의미 재검토용 근거다.
구축용 입력 수·독립 평가 수와 별개이며, 평가 문서 및 같은 공고의 첨부를 포함하지 않는다.
관련 원본 해시는 이 근거에서 먼저 찾고 부족한 경우 과거 Data DB 참조를 조회한다. 근거 해시·분류·평가 분리를 검증한다.
`document_assessment.json`, `failure.json`, `coverage.json`과 수락한 중간 결과는 MinIO diagnostics에 보존한다.
원시 모델 응답과 파서 stderr 본문은 영구 진단에 복제하지 않는다.

공고문의 일반 계약 조건과 구매 수량만으로 기술 규격이 있다고 보지 않는다. 양식에 물품명만 있는 경우도 마찬가지다. 실제 기술 조건과 불확실한 구간은 계속 보존한다. 모든 명시 입력이 대상 제외라면 실패 0·제외 수를 기록해 실행을 완료하며, 실제 파싱 실패와 혼동하지 않는다.
