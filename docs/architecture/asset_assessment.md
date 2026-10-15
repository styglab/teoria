# Asset assessments

`intelligence.asset_assessments`는 사용자가 시작한 자산 진단의 요청·실행·결과를
소유한다. 자산의 상태는 OpenMetadata에서 읽고 `MetadataTargetRef`와 관찰 version만
저장한다. 실행 상태는 `queued → running → completed / partial / failed`다.

## 첫 구현 범위

| 진단 | 입력 | 결과 |
|---|---|---|
| `metadata_enrichment` | 테이블·컬럼의 현재 설명·타입 | 설명 변경 Suggestion |
| `semantic_alignment` | 메타데이터·게시된 Property 후보·기존 Binding | 기존 Concept에 대한 직접 자산 Binding Suggestion |
| `disclosure_assessment` | 메타데이터·평가일·개방 상황·로컬 법령 검색 | 법령 근거가 붙은 검토 findings |

새 Glossary 생성·할당의 자동 추론, 용어를 통한 Binding 확장, 원천 문서 자동 검색,
프로파일·원본 샘플 사용, 신규 Ontology와 태그 자동 적용은 이 Worker의 첫 범위에
포함하지 않는다. 기존 Codex Skill은 설명·Glossary 정비와 용어 경유 의미 연결을
계속 지원한다. 첫 Worker의 직접 Binding은 보조 연결이며 기본 의미 경로인
`Physical Asset → Glossary Term → Ontology`보다 우선하지 않는다.

원천 업무 문서를 대조하지 않은 제안은 추정임을 명시하며 confidence를 0.69 이하로
제한한다. 법령 검색은 기준일의 키워드 검색이며 적용 조건·예외의 검토를 대신하지
않는다. 진단은 법적 적합성을 확정하지 않고 태그 후보도 미검증으로 표시한다.
법령 근거가 없으면 공개 가능 판정 대신 `review_required`로 남긴다.

## API와 화면

`POST /v1/admin/intelligence/asset-assessments`는 `metadata_admin` principal만
호출한다. 요청 body의 actor는 허용하지 않는다.

```json
{
  "table_fqn": "service.database.schema.table",
  "scopes": ["metadata_enrichment", "semantic_alignment"],
  "column_names": ["amount"],
  "disclosure_context": "public_release"
}
```

`assessment_date`는 선택 사항이며 기본값은 한국 날짜다. `column_names`가 비면
전체 컬럼을 분석하며 최대 30개다. `disclosure_context`는 `public_release` 또는
`restricted_sharing`이다. API는 실제 자산 identity와 컬럼을 확인하고 202와 진단
레코드를 반환한다. 같은 대상·version·범위·기준일의 활성 요청은 중복 등록하지 않는다.

- `GET /v1/admin/intelligence/asset-assessments?table_id=<uuid>`: 자산의 최근 진단
- `GET /v1/admin/intelligence/asset-assessments/<assessment_id>`: 상태·제안 ID·findings

진단 조회는 인증이 필요하다. 자산 상세의 `자산 진단`에서 항목과 컬럼을 고르고
`진단 실행`을 누르면 상태를 주기적으로 조회한다. 실패한 진단은 이력을 유지하며
새 진단을 요청한다. 별도 자동 대상 스캔이나 예약 진단은 없다.

## Worker와 결과 검증

Worker는 `platform/src/teoria/intelligence/asset_assessment/`를 실행한다.
Prefect는 데이터·메타데이터 수집을 계속 담당한다.

PostgreSQL `SKIP LOCKED` 선점, claim token과 10분 lease를 사용한다. 진단 실행은
8분으로 제한하며 lease가 만료된 실행은 최대 3회 선점한다. timeout·모델 오류 등
명시적 실패는 `failed`로 종료한다. 프로세스 종료로 만료된 작업만 자동 선점한다.
만료된 Worker는 결과를 저장할 수 없다. 강제 종료 후 재실행은 모델 호출 비용을
중복시킬 수 있지만 제안 저장은 실행권과 트랜잭션으로 보호한다.

모델은 서버가 고정한 gateway만 호출한다. 메타데이터·법령의 텍스트는 비신뢰 입력으로
취급하며 모델에 임의 Tool 실행이나 외부 쓰기를 허용하지 않는다. 모델은 변경 후보와
근거 ID만 반환한다. 서버는 선택 범위·컬럼·게시된 Concept 후보·근거 ID를 검증하고
제안의 적용 payload를 직접 구성한다. 분석 전후 자산 version이 다르면 저장하지 않는다.

검증된 Suggestion, 진단 결과, 연결 ID를 한 트랜잭션으로 기록한다. 동일한 기존
pending 제안은 재사용한다. 결과 검증에서 일부가 제외되거나 법령 버전이 없으면
`partial`로 표시한다. 기존 `Suggestion → Review → Application`을 그대로 사용하며
Worker는 승인·태깅·게시를 실행하지 않는다. DB에는 원천 자산 본문, 샘플, 전체
법령 본문, 모델의 원문 응답을 저장하지 않는다.

## 설정과 실행

```dotenv
TEORIA_ASSESSMENT_ENABLED=true
TEORIA_ASSESSMENT_MODEL_URL=<full chat-completions endpoint>
TEORIA_ASSESSMENT_MODEL_NAME=<model identifier>
TEORIA_ASSESSMENT_MODEL_TOKEN=<secret if required>
TEORIA_ASSESSMENT_MODEL_MAX_TOKENS=6000
```

gateway는 `messages`, `model`, `temperature`, `max_tokens`,
`response_format: {"type":"json_object"}` 요청과
`choices[0].message.content` JSON 문자열 응답을 지원해야 한다. 모델 토큰은
Worker에만 주입하며 기본 외부 endpoint나 모델을 임의로 선택하지 않는다.
출력 토큰 한도는 모델의 실제 문맥 한도에 맞춘다. 현재 운영의 로컬 Qwen3.8-27B는
8,192토큰 문맥으로 실행되므로 출력 한도를 2,048로 두고 소수 컬럼부터 진단한다.
대량 컬럼·긴 법령을 처리하려면 더 큰 문맥의 모델이나 입력 분할이 필요하다.
기존 모델 컨테이너는 `teoria_default` 네트워크의 `metadata-model` 별칭으로 연결한다.
이 컨테이너를 재생성하면 네트워크 별칭도 다시 연결해야 한다.

Application DB migration을 적용하고 새 authoring·UI 이미지를 빌드한 뒤 시작한다.

```bash
docker compose -f deploy/compose/compose.yaml --profile metadata --profile intelligence \
  up -d --build admin-api admin-ui metadata-assessment-worker
```

Compose의 `app-postgres-migrate`가 신규 migration을 적용한다. 모델 설정이 비어 있으면
Admin API는 `asset_assessment_not_configured`를 반환하며 Worker도 시작하지 않는다.
운영 Admin API는 `bearer`와 별도 관리자 토큰을 사용한다.

## 운영 검증 (2026-10-15)

로컬 Qwen3.8-27B와 운영 Admin API·Worker를 연결해 다음을 확인했다.

- `be6f555e-3a9a-41a9-885a-46d2203785ec`: `runtime_contracts`의
  `contract_date`, `current_contract_amount` 진단 완료. 설명 제안 2건은 pending이며
  신뢰도 0.2인 검토 후보다. 의미 연결은 후보가 모호해 보류했다.
- `21f1f682-ae5e-49c8-9349-539c00ec7ef8`: `runtime_bid_opening_participants`의
  `representative_name` 개방 진단 완료. 실제 수집 snapshot을 인용한 검토 finding을
  생성했다. 법적 적합성 확인은 false이며 태그와 원천 설명은 변경하지 않았다.

초기 법령 검색·인용 실패 회차는 partial 이력으로 보존한다. 한글 검색어 확장과
짧은 근거 ID를 적용한 뒤 재검증했다. 이 검증은 실행·저장 경로의 확인이며,
생성 설명·법령 해석의 정확도나 Binding 품질을 보증하는 평가가 아니다.
