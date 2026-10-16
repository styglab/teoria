# 변경 제안의 검토·적용과 복구

설명 변경, Codex Skill과 자산 진단은 모두 변경 후보를 제안할 수 있다. 이 문서는
생성된 Suggestion을 사람이 검토하고 원천에 적용하는 공통 절차를 설명한다.
진단 Worker의 분석·근거 검증은 [자산 진단](asset_assessment.md)이 담당한다.

## 제안에서 적용까지

```text
제안 생성 → pending → 검토 → approved → 대상 재검증·적용 → applied / failed
                        └→ rejected / changes_requested
```

제안 생성은 `metadata_admin`, 검토·재시도·복구는 `metadata_reviewer`, `metadata_admin`,
`ontology_owner` 중 허용 역할이 필요하다. Ontology 변경 검토에는 `ontology_owner`가
추가로 필요하다. 변경 주체는 인증 principal이며 요청 body의 reviewer·actor를 신뢰하지 않는다.

1. 자산의 현재 값, 제안 값과 제안 당시 근거를 비교한다.
2. 대상·의미·근거가 맞으면 승인하고, 부족하면 거절하거나 변경을 요청한다.
3. 서비스가 원천의 version과 필요한 참조를 다시 검증한 뒤 적용한다.
4. 결과와 적용 이력을 확인한다. 승인되었다는 사실만으로 적용 성공을 판단하지 않는다.

## 적용 대상별 결과

진단 완료는 원천 변경 완료를 뜻하지 않는다. UI에서 결과의 근거·신뢰도·대상 version을
검토하고, 설명·Binding 제안은 `검토·적용`에서 승인한다. 개방 진단 findings는 검토
보고서이며 자동 태깅이나 공개 승인으로 적용되지 않는다.

| 제안 대상 | 승인 후 수행하는 작업 | 추가 절차 |
|---|---|---|
| 설명·Glossary·quality test | OpenMetadata API에 적용 | 대상 version·생성 결과 재검증 |
| Semantic Binding | Binding Draft 생성 | 별도 Binding 승인 |
| Ontology | 새 Draft에 변경 적용 | Ontology 검토·승인·게시 |

적용 시도는 `intelligence.application_attempts`에 남긴다. 실행권 token과 효과 시작·성공
기록으로 중복 적용을 막고 metadata entity 본문은 저장하지 않는다.

실패 후에는 서버가 반환한 다음 조치를 따른다. 변경 시작 전 실패는 기존 승인으로
재적용하고, 변경 시작 후 결과가 불확실하면 기존 결과를 먼저 확인한다. stale evidence는
재분석한다. 재시도는 새 승인을 만들거나 실행 중인 작업을 중복 호출하지 않는다.

## 조회와 변경 API

아래 경로의 공통 prefix는 `/v1/admin/intelligence`다. 자세한 요청·응답은 배포된
Admin OpenAPI를 따른다. 목록·단건·비교·이력 조회에는 관리자 인증이 필요하다.

| API | 용도 |
|---|---|
| `GET /suggestions?status=pending&table_id=<uuid>` | 상태·자산별 목록, `after` cursor로 다음 페이지 |
| `POST /suggestions` | 검증된 제안 입력 제출 |
| `POST /description-suggestions` | 현재 설명·version을 근거로 설명 변경안 생성 |
| `POST /binding-suggestions` | 자산 컬럼의 Binding 후보 제안 |
| `GET /suggestions/{id}/target` | 현재 대상과 제안 비교 |
| `POST /suggestions/{id}/reviews` | `approve`, `reject`, `request_changes`, `supersede` 검토 |
| `GET /suggestions/{id}/applications/attempts` | 시도별 실행자·시각·결과 조회 |
| `POST /suggestions/{id}/applications/retry` | 기존 승인으로 안전한 적용 재시도 |
| `POST /suggestions/{id}/applications/reconcile` | 외부 변경을 재실행하지 않고 기존 결과 확인 |

재시도·복구 가능 여부는 서버의 현재 실행권·효과 기록과 응답을 따른다.
`stale_evidence`는 근거 갱신과 재분석이 필요하다. 실행 중인 작업을 중복 호출하지 않는다.
목록과 이력은 페이지 단위이며 조회한 범위를 전체 누적 결과로 해석하지 않는다.

## 구현 위치

제안 기능은 `platform/src/teoria/intelligence/suggestions/`에 둔다. `generation.py`는 생성,
`application.py`는 승인·재시도·복구, `execution.py`는 실행권과 효과 기록,
`appliers/openmetadata.py`·`appliers/drafts.py`는 대상별 쓰기를 담당한다.
`contracts.py`에서 생성한 schema를 Skill bundle에도 사용한다.

### HTTP와 서비스 경계

`admin/intelligence_api.py`는 인증·역할 검사와 HTTP 오류 변환을 담당한다.
`intelligence/suggestions/service.py`는 자산 기준 제안 조회, 원천 대상 비교,
제안 생성·조회·적용 이력과 재시도 조건을 소유한다. OpenMetadata 자산 식별 확인과
대상 참조 구성은 서비스에서 수행하며, 비동기 경로의 동기 DB 조회는 thread pool에서 실행한다.

현재 화면은 [Admin UI](../admin_ui.md), Codex 제출 경로는
[진단 Skills](../../skills/analyze_metadata_asset.md)를 참고한다.
