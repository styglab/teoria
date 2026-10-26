# 규격서 추출 개선 평가

[파이프라인 계약](pipeline.md)의 공통 추출 단계를 평가한다. 스킬 호출과 직접 CLI 실행 방법을 정리한다.

평가 실행 코드는 `evaluation.py`, 입력·샘플링은 `evaluation_cases.py`, 독립 채점·비교는
`evaluation_scoring.py`가 소유한다. Skill은 이 명령을 호출하고 원문 분석과 코드 수정을 수행한다.
별도 실험용 샘플러·채점 스크립트·코드 스냅샷을 만들지 않는다.

## 스킬로 사용하기

스킬을 계속 사용한다. 다음처럼 요청하면 스킬이 평가 CLI를 호출하고 개발 결과를 분석해 소유 코드를 수정한다.

```text
$improve-specification-processing 한 사이클 돌려줘.
```

기본 대상은 분류 근거가 있는 컴퓨터 서버 원본이며, 신규 샘플 목표는 10개다.
실제 수량은 공고·양식·중복 파일의 연결 그룹과 확보한 자료에 따라 달라진다.
스킬은 원문 분석·오류 진단·수정을, 코드는 고정 샘플링·실행·채점·비교·정리를 담당한다.
사용자는 조건을 바꿀 때만 문서 수·분류·중점 대상을 덧붙이면 된다.
아래 CLI 명령은 직접 실행하거나 문제를 재현할 때 사용한다.


`procurement-extraction-evaluation` Flow는 운영 Flow와 같은 `extract_documents()`를 호출해
원본 준비·파싱·엔티티/관계·요구조건·귀속 해석·추출 저장 Task 00–05를 실행한다.
추출 checkpoint를 재사용하지 않는다. 표준 후보 채택·정규화·운영 DB 완료 처리는 실행하지 않으며,
이 평가로 해당 기능의 품질이나 운영 연동 성공을 주장하지 않는다.
실행은 별도 프로세스의 임시 Prefect 홈·로컬 객체 저장소를 사용하며 운영 DB에 행을 만들지 않는다.

### 명령과 실행 순서

```bash
uv run --locked --project backend teoria-pipelines specification evaluate schema
uv run --locked --project backend teoria-pipelines specification evaluate prepare --manifest /data/evaluation.json
uv run --locked --project backend teoria-pipelines specification evaluate baseline --cycle-id server_cycle_01
# 개발 문서·baseline을 확인하고 소유 코드와 회귀 테스트를 수정한다.
uv run --locked --project backend teoria-pipelines specification evaluate candidate --cycle-id server_cycle_01
uv run --locked --project backend teoria-pipelines specification evaluate finish --cycle-id server_cycle_01
```

별도 요약 위치는 `evaluate --state-dir PATH prepare ...`처럼 단계 이름 앞에 지정한다.
중단·폐기 또는 사전 검사 실패로 남은 사이클은 `evaluate abort --cycle-id ID`로 정리한다.
진행 중인 사이클이 정리되지 않으면 다음 `prepare`를 거부한다. 같은 variant 재실행으로 유리한
결과를 고를 수 없으며 baseline 완료 전에는 candidate를 실행하지 않는다.

### 입력 계약

`schema` 명령이 현재 Pydantic JSON Schema를 출력한다. 주요 필드는 다음과 같다.
상대 경로는 명령을 실행한 저장소 루트를 기준으로 해석하므로 같은 루트에서 실행한다.

| 필드 | 의미 |
|---|---|
| `cycle_id` | 새 개선 사이클 ID |
| `case_contract_version` | 현재 평가 계약 `2` |
| `purpose`, `replay_of` | 기본 `extraction_improvement`; 평가 보정 재실행은 `grader_calibration`과 원래 사이클 ID |
| `classification_code` | 기본 컴퓨터 서버 `4321150102` |
| `documents` | 원문·분류 근거·해시를 가진 후보 문서 목록 |
| `regression_documents` | 별도 고정 회귀 문서·사례. 신규 샘플 수에 포함하지 않음 |
| `sample_size`, `seed` | 기본 10개. seed 생략 시 새 값 생성 후 고정 |
| `history_reviewed` | 이전 사용 이력을 대조했는지. 기본 false이면 신규 노출 여부 미확인으로 보고 |
| `excluded_notices`, `excluded_sha256` | 기존 실험 이력에서 가져온 제외 대상 |
| `model`, `parser_python` | 비교에 사용할 모델·Parser Python. 모델 미지정이면 개선 채택 판정 불가 |
| `run_timeout_seconds` | 각 variant의 split 실행 및 테스트 시간 제한. 기본 1800초 |

문서 한 개의 입력 예시는 아래와 같다. 경로·해시는 실제 값으로 대체하며, 독립 개발·검증 그룹과
별도 회귀 사례를 평가하려면 해당 문서들을 목록에 더 넣는다. 이 한 항목만으로 독립 검증을 주장하지 않는다.

```json
{
  "document_id": "server_doc_01",
  "notice_number": "SOURCE_NOTICE_ID",
  "source_uri": "file:///data/specification.hwpx",
  "filename": "specification.hwpx",
  "sha256": "실제 원본 SHA-256",
  "classification_code": "4321150102",
  "classification_evidence": {
    "path": "/data/notice_metadata.json",
    "sha256": "실제 메타데이터 파일 SHA-256",
    "code_pointer": "/classification_code",
    "notice_pointer": "/notice_number"
  },
  "template_family": "known_template_family_or_null",
  "layout": "table",
  "label_status": "silver",
  "requirements": [
    {
      "subjects": ["CPU"],
      "value_raw": "16",
      "unit_raw": "core",
      "operator": "gte",
      "source_text": "CPU 16core 이상"
    }
  ]
}
```

분류 메타데이터의 코드와 공고 번호를 JSON pointer로 실제 확인한다. 파일명으로 분류하지 않는다.
같은 공고·명시한 양식군·동일 바이트를 연결 그룹으로 만든 뒤 무작위 선정·분할한다.
형식·layout별 층화를 사용하며 같은 그룹을 쪼개지 않아 정확히 5/5가 되지 않을 수 있다.
문서 부족·양식 미확인·이력 미확인은 숨기지 않고 기록한다. 삭제 후에도 사용 공고·해시·양식 이력은 유지한다.

### 점수와 채택의 한계

분류값이 확인되지 않은 `.artifacts/sample`의 네 문서는 별도의 원문 기반 평가기 판정 테스트에
사용한다. 작은 고정 원문·위치·해시는 `backend/tests/features/specification_processing/evaluation/fixtures/sample_source_cases.json`,
실행 코드는 같은 평가 디렉터리의 `test_sample_source_cases.py`에 있다. 기존 `score_extraction()`을
호출하여 통제된 정상 결과와 대상·값·단위·연산·역할·범위·근거·관계 방향·누락·중복 오류를 검사한다.
분류나 공고 번호를 만들어 넣지 않으며, 정식 평가 CLI의 분류 근거 검증을 우회하지 않는다.
이는 이미 알려진 네 문서에 대한 평가기 보정용 silver 사례이며 LLM 추출 실행·신규 무작위 검증·
독립 정답 정확도 측정이 아니다. 원본이 있는 로컬 환경에서는 원본 바이트의 해시도 검사한다.

```bash
uv run --project backend --locked --all-extras --group orchestration pytest \
  backend/tests/features/specification_processing/evaluation/test_sample_source_cases.py -q
```

사례는 `entities`, `relations`, `requirements`로 제공한다. 관계 방향, 요구조건의 대상·값·단위·연산·한정자와
선택적으로 속성명 후보·역할·범위·상위 대상(`owner`)을 검사한다. 동명 하위 대상이 여러 개면
`owner`와 관계 사례로 소속을 구분한다. `source_text`는 원문에서 확인한 작은 구절이다.
기본 라벨은 silver다. `human_reviewed`는 실제 사람 검토가 있을 때만 표시하며 자동 생성하지 않는다.

평가 계약 v2는 다음을 구분한다.

- 엔티티의 `evidence_mode: existence`는 문서 안에 해당 엔티티가 원문 근거와 함께 존재하는지 확인한다.
  `mention`은 라벨에 지정한 원문 위치까지 일치해야 한다. 동명 항목은 `owner`로 구분한다.
- 요구조건의 `qualifiers_raw: null`은 한정자를 주석하지 않았다는 뜻이다. 기본 `required_subset`은
  라벨에 명시한 조건이 모두 포함되는지 검사하고, 원문에 근거한 추가 조건을 허용한다.
  `qualifier_mode: exact`와 `qualifiers_raw: []`를 함께 쓰면 조건이 없어야 한다는 명시적 주장이다.
  `forbidden_qualifiers`는 허용하지 않는 조건 표현을 지정한다.
- 한정자 비교는 공백·유니코드와 바깥쪽 표시용 괄호만 정리한다. 부정, AND/OR, 내부 연산은 버리지 않는다.
  `entity_aliases`는 원문으로 확인하여 동결한 별칭만 허용하며 유사 문자열 추정은 하지 않는다.
- 대상·상위 항목·값·단위·연산·명시한 역할과 범위가 틀리거나, 필수 조건이 빠지거나,
  금지 조건 또는 원문에 없는 값·조건이 생기면 실패한다.

이 점수는 주석한 제약의 재현과 원문 적합성을 측정한다. 모든 추가 조건의 의미적 동등성까지
검증했다는 뜻은 아니다. 계약 버전이 다른 점수를 비교해 추출 개선을 주장할 수 없다.

채점은 표준 의미 추론과 독립된 코드이며, 원문 근거·ID·중복·미귀속·실패/부분 문서와 고정 사례 일치를 센다.
중복은 대상·속성·값·조건·역할·범위뿐 아니라 원문 노드·문자 범위·필드 근거가 같은 관찰을
반복 추출했는지 검사한다. 문서의 다른 위치에 실제로 반복 기재된 요구조건은 별도 근거 관찰로
보존하며 중복 오류로 세지 않는다. 재시도의 임시 fragment ID만 다른 경우는 같은 원문 관찰이다.
라벨이 없는 문서는 원문 적합성 검사만 가능하다. 일부 사례 점수를 전체 요구조건 재현율이나
완전한 관계 정확도로 표시하지 않는다. 추출 실패 문서도 사례 분모에서 제외하지 않는다.
검증 점수는 후보 코드가 고정되어 실행된 뒤 `finish`에서 공개한다.

`finish`는 Pipeline 전체 테스트를 실행한다. 개발 사례 개선, 검증·회귀 악화 없음과 필요한 사례가 모두
확인될 때만 `accepted`를 반환한다. 사례 부족·모델 미고정·Parser 버전 변경·코드 변경 없음은 미확정이다.
같은 입력·라벨·평가 코드·점수 해시를 고정하고 점수 파일 변경을 검출한다. 수정된 코드를 자동으로
커밋·게시·배포하지 않으며, silver 사례 통과를 독립 정답 정확도로 주장하지 않는다.

`prepare`는 Parser 실행 환경의 Python 버전, Parser 소스 해시와 설치 패키지 버전 목록의 해시도
기록한다. 각 split 실행 전후와 `finish`에서 이를 다시 검사한다. 실행 경로·버전 문자열이 같아도
코드나 의존성이 바뀌면 `ParserRuntimeChanged`로 중단하고 정리하며 비교를 미확정으로 남긴다.
이 검사는 변경 감지이며 설치 환경 자체를 잠그지는 않는다. 개발 중인 editable 설치 대신
변경되지 않는 Parser 설치 환경을 사용한다. Parser를 사용할 수 없으면 그 상태를 기록하며
실제 Parser 품질 검증에 성공한 것으로 해석하지 않는다.

### 평가 기준을 보정할 때

평가 코드나 라벨이 원문과 충돌하면 진행 중인 사이클을 중단한다. 동결된 기준을 실행 도중 수정하지 않는다.
보정 후 새 manifest에 `purpose: "grader_calibration"`, `replay_of: "원래_사이클_ID"`를 넣어
`prepare → baseline → finish`만 실행한다. `candidate`는 허용하지 않는다.

보정 재실행은 원래 사이클에 있던 문서의 전부 또는 일부를 사용하되, 원본 해시·공고·분류·split·seed와
실행 설정을 유지한다. 노출 이력은 초기화하지 않으며 신규 무작위 검증으로 보고하지 않는다.
정상 완료 판정은 `baseline_recorded`다. 이는 새 기준점 기록이며 추출 코드의 개선 채택이 아니다.
Parser 버전이나 모델 출력 변동이 있으면 이전 점수와의 차이를 평가 코드 수정 효과로 단정하지 않는다.
추출 개선은 이후 별도 사이클에서 동일한 평가 계약으로 baseline/candidate를 비교한다.

### 자동 정리

실행 실패·취소 시 평가 작업 디렉터리를 정리하고, 정상 비교는 `finish`의 종료 경로에서 정리한다.
강제 프로세스 종료로 남은 작업은 `abort`로 정리한다. 생성한 `/tmp/teoria_specification_eval_*` 경로와
소유 토큰을 확인하고 삭제하므로 입력 디렉터리·운영 S3·공유 DB를 삭제 대상으로 사용하지 않는다.
원본·고정 회귀 사례와 작은 누적 `state.json`, `index.md`만 남긴다. state에는 입력 참조·고정 사례·
사용 이력·코드/평가 해시·전후 수치·판정·정리 용량이 남고 전체 추출 그래프·모델 응답·로그는 삭제한다.
일반 운영 실행의 영구 산출물 저장 계약은 바꾸지 않는다.

