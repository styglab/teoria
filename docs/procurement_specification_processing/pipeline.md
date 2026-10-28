# 규격서 파이프라인과 Codex 사용

원본 입력부터 결과 저장까지 아래 순서로 처리한다. 실행은 Prefect, 원문 해석은 파서와 Codex,
표준관리에서는 미해결 사전 의미도 Codex가 판단한다. 검증·승인 정책·표준 적용·저장은 코드가 담당한다.

## 두 흐름과 공통 단계

| 처리 방식 | 목적 | Prefect Flow |
|---|---|---|
| 표준관리 | 추출 표준과 의미 후보를 관리하며 처리 | `procurement-standard-management` |
| 문서처리 | 지정한 고정 표준/프로파일로 처리 | `procurement-document-processing` |

두 방식은 같은 00–08 단계를 공유한다. 사전 전용 Flow는 없다.

| 단계 | 하는 일 | Codex |
|---|---|---|
| **00 원본 준비** | 파일 보관·해시 확인, 지정한 checkpoint 검증 | 사용 안 함 |
| **01 문서 파싱** | 본문·표·계층·위치 추출 | 사용 안 함 |
| **02 물품·계층·관계 추출** | 기준 목록, 하위 대상, 구성·작업·연계 관계 해석 | **사용** |
| **03 요구조건 추출** | 속성·값·단위·조건 분리, 누락 후보 재추출 | **사용** |
| **04 대상·역할·범위 해석** | 어느 대상의 조건인지, 납품/지원/기보유·개별/전체 범위 해석 | **사용** |
| **05 검증·저장** | 원문·참조·관계 유형 검사, 추출·보류 보존 | 사용 안 함 |
| **06 사전 연결·표준 의미 작성** | 원문 등록·승인 매핑 재사용, 미해결 정의·매핑 판단과 반영 | **표준관리의 미해결 항목에 사용** |
| **07 표준 적용** | 고정 표준/프로파일 적용, 사전 개념 연결 결과 저장 | 사용 안 함 |
| **08 보고서 저장** | 구성 트리·속성·근거·보류 표시, 산출물 저장 후 완료 기록 | 사용 안 함 |

Flow 코드가 [실행 순서](../../backend/src/teoria/features/specification_processing/flows.py),
Task 코드가 [단계 경계](../../backend/src/teoria/features/specification_processing/tasks.py)의 기준이다.

## Codex를 사용하는 단계

| 단계 | 호출 내용 | 검증·재시도 |
|---|---|---|
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
파서에서 사라진 정보는 추출기가 복원했다고 표시하지 않는다. 기본 파싱은 OCR을 사용하지 않는다.

## 사전과 표준 적용

06 단계는 원문에 나온 표현을 조회·등록하고, 승인된 의미 매핑이 있으면 표준 정의를 가져온다.
원문 명칭이 없는 속성은 내부 영문 후보명을 원문 표현처럼 등록하지 않는다.
새 동의어·표준 의미를 이름 유사도만으로 확정하지 않는다.

표준관리 모드에서는 미해결 물품 유형부터 Codex가 판단하고, 승인된 물품 유형을 소유자로 속성을 판단한다.
기존 정의 동등 매핑 또는 새 로컬 정의를 별도 Codex 호출로 재검증한다. 근거·유형·적용 대상·값 유형·단위 검사를 통과하면
`dictionary_meaning_auto_approve: true`(기본값)에 따라 인증된 Admin API로 정의와 매핑을 승인한다.
같은 실행에서 승인 매핑을 다시 조회해 07 결과에 적용한다. `false`이면 제안만 저장하며 새 정의의 승인이 필요한 속성은 보류한다.
문서처리 모드는 이 의미 작성 경로를 실행하지 않는다. 승인 주체·판정 사유는 Admin 감사 이력에 남고 Published Ontology는 바꾸지 않는다.

07 단계는 다음 두 연결을 구분해 저장한다.

| 연결 | 결과 |
|---|---|
| 사전의 승인된 개념 매핑 | `dictionary_meanings`, `dictionary_concept_ref`, 정의 개정·매핑 ID |
| 고정 표준/프로파일 적용 | 표준 버전·URI·checksum과 관찰별 적용/보류 |

사전 개념 ID와 Published Ontology Stable Concept ID는 다르다.
기본 `source_only`는 미확정 의미를 후보로 남긴다. 분류값만으로 분야 규칙을 켜지 않는다.
과거 `server` 규칙은 명시적인 호환 설정이며 현재 운영 물품 사전이나 활성 서버 Capability를 뜻하지 않는다.
상세 내용은 [사전](../platform/goods_dictionary.md)과 [프로파일](normalization_profiles.md)을 따른다.

여러 실행의 기존 extracted.json을 모은 초기 사전 구축·개정은 기존 06 단계의 `dictionary_reconcile` 옵션 또는 사전 안내의 `dictionary-maintain` 명령을 사용한다.
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

본문은 `<artifact_root>/specification_processing/<run_id>/`의 파일/S3에 저장한다.
표준관리의 로컬 표준 초안은 `standards/<version>/standard.json`에 별도로 저장한다.
Data DB에는 실행·문서별 요약·URI·checksum만 저장한다. [저장소 기준](../pipelines/database.md)을 따른다.

다른 내용으로 같은 객체 키를 덮어쓰지 않는다. 모든 산출물 저장 후 완료/부분완료 상태를 기록한다.
파서 native·청크·원시 모델 응답은 임시 디렉터리에서 처리 후 정리한다. 일반 실행의 최종 산출물은 보존한다.

## 실행 방법

화면에서는 [규격서 분석](../platform/admin_ui.md)을 사용한다. CLI는 다음과 같다.
실행 전에 Data DB·Prefect·Codex 인증·파서 Python·Admin 작성 API를 [환경 설정](../deployment/configuration.md)대로 준비한다.

```json
{
  "run_id": "specification_example_01",
  "mode": "standard_management",
  "model": "gpt-6.1-sol",
  "model_timeout_seconds": 600,
  "artifact_root": "file:///app/specification_artifacts",
  "documents": [{
    "document_id": "equipment_01",
    "source_uri": "file:///app/specification_inputs/equipment.hwpx",
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
현재 원본 처리와 Worker 반영은 [운영 검증](../verification/goods_relation_deployment_2026_10_28.md),
고정 원본 비교의 한계는 [평가 기록](../verification/goods_relation_repair_2026_10_28.md)에 있다.
별칭·동일 대상·조건 귀속·표준 의미 확대와 새 물품 Runtime 연결은 후속이다.

추출 개선은 [평가 절차](evaluation.md)를 따른다. 자동 공고 첨부 수집·참가자격 판단은 연결하지 않는다.
이전 실행 설계는 [보관 기록](../../archive/documentation/procurement_specification_processing/pipeline_2026_10_27.md)에서만 확인한다.
