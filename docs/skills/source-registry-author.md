# Source Registry 작성 Skill

`author-source-registry`는 Provider Reference 원문에서 Runtime API Source 또는 Ingestion API Connector와 Operation별 verification case를 작성하고, 정적·Build·회귀·Live 검증을 반복하는 저장소 범위 Codex Skill이다.

## 사용 방법

Codex를 이 저장소 루트에서 시작하고 프롬프트에 Skill 이름과 대상 Reference를 지정한다.

```text
$author-source-registry
pipelines/references/providers/pps/pps_contract_api의 모든 문서를 근거로
Ingestion Connector와 verification cases를 만들고 검증해줘.
모든 Operation에 대해 정적 검증, Build 검증과 실제 API Live 검증을 실행하고,
검증 실패가 Source 계약 문제면 수정한 뒤 전부 다시 실행해줘.
최종 결과에는 Operation별 PASS, FAIL, BLOCKED 상태를 남겨줘.
```

기존 Source를 원문과 다시 대조할 때도 사용할 수 있다.

```text
$author-source-registry
pipelines/references/providers/pps/pps_contract_api 원문을 기준으로
pipelines/connectors/pps_contract_api.yaml의 모든 Operation과 필드를 감사하고,
누락이나 오류를 수정한 뒤 실제 API Live 검증까지 실행하고 전체 결과를 보고해줘.
```

Skill 이름을 생략해도 요청 내용이 설명과 일치하면 Codex가 자동 선택할 수 있지만, 재현 가능한 작업 지시에는 `$author-source-registry`를 명시하는 편이 분명하다.

## 준비 사항

- Source 원문은 `platform/references/providers/{provider}/{source}/`, Connector 원문은 `pipelines/references/providers/{provider}/{connector}/`에 둔다.
- 의존성은 `uv sync --locked --all-packages --all-groups`로 설치한다.
- `.env` 또는 실행 환경에 Source나 Connector의 `credential_env` 값을 설정한다. 키는 프롬프트, YAML, verification case에 넣지 않는다.
- credential이 없더라도 정적 검증, 모든 Build 검증과 전체 테스트는 실행된다. Live만 `BLOCKED`로 보고된다.

예를 들어 조달청 Connector는 다음 환경변수를 사용한다.

```bash
export TEORIA_CONNECTOR_PPS_CONTRACT_API_KEY='...'
```

Skill을 사용한 Source 작성·검증 요청은 기본적으로 실제 API 호출을 포함한다. Live 호출이 불필요한 경우에만 프롬프트에 `Live 검증은 제외해줘`라고 명시한다.

## 산출물과 완료 기준

기본 산출물은 다음과 같다.

```text
platform/registries/sources/{source_id}.yaml
platform/registries/sources/verification_cases/{source_id}/{operation_id}.yaml
platform/references/providers/{provider}/{source}/metadata.yaml
```

Ingestion 전용 API라면 다음 위치를 사용한다.

```text
pipelines/connectors/{connector_id}.yaml
pipelines/verification_cases/{connector_id}/{operation_id}.yaml
pipelines/references/providers/{provider}/{connector}/metadata.yaml
```

최종 보고에는 원문과 Registry의 Operation·필드 대조 결과, 실행한 검증 명령별 상태, 수정한 문제, 모든 Operation의 Live `PASS`·`FAIL`·`BLOCKED` 상태와 남은 제한이 포함된다. 결과 파일을 `archive/`에 보관하려면 프롬프트에서 별도로 요구한다.

Skill 본문은 [SKILL.md](../../.agents/skills/author-source-registry/SKILL.md)에 있으며, Reference 추출 도구는 같은 Skill의 `scripts/extract_reference.py`에 있다.
