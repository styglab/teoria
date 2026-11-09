# 규격서 처리

FormatID가 사용하는 물품 처리 파이프라인이다. 원문에서 관찰을 추출하고,
필요한 의미 후보를 검토한 뒤 고정된 표준을 적용한다.
새 업무 정의의 작성·게시 권위는 플랫폼 Ontology에 있다.

## 처리 순서와 코드

| 단계 | 하는 일 | `domains/goods/` 아래 소유 위치 |
|---|---|---|
| 원본 준비 | 입력 검증·원본 저장·checksum 확인 | `data_processing/tasks.py` |
| 파싱 | 본문·표·OCR·문서 역할 분류 | `data_processing/parsing/` |
| 추출 | 물품·구성·관계·속성·조건·원문 근거 | `data_processing/extraction/` |
| 검증·저장 | 근거 대조·실패 격리·추출 artifact 저장 | `data_processing/tasks.py`, `storage/` |
| 표현 등록 | 원문 표현과 문맥 등록 | `expression_links/` |
| 의미 제안 | 게시 Ontology 비교·후보·미해결 상태 보존 | `normalization/meaning_proposals/` |
| 기준 적용 | 고정 프로파일·추출 규칙 적용 | `normalization/application/` |
| 결과 확정 | 보고서·문서별 결과·실행 영수증·완료 checkpoint | `workflows/tasks.py`, `specifications.py` |

추출 Task 순서는 `data_processing/flows.py`, 전체 실행은 `workflows/specifications.py`에서 읽는다.
앱의 HTTP 진입점은 `apps/formatid/router.py`다. SQL·파일 저장은 물품 도메인이 맡는다.
파싱·추론과 결정적 검증·승인 정책을 구분한다. 모델 응답을 그대로 승인하지 않는다.

## 실행 방식

- `specification-standard-management`: 문서에서 처리 기준과 의미 후보를 준비한다.
- `specification-document-processing`: 선택한 문서에 고정된 처리 기준을 적용한다.
- `specification-standard-workflow`: 추출·후보·프로파일 작성 절차를 연결한다.

이름은 기존 Prefect 배포와 CLI의 외부 계약이므로 코드 디렉터리와 별도로 유지한다.
공통 파라미터는 `backend/config/specification_processing/prefect_deployments.yaml`,
환경별 pool·queue 정책은 `deploy/compose/prefect/`, `deploy/k3s/prefect/`에 있다.

화면에서는 [FormatID 사용 순서](../../../platform-guide.md#formatid-사용)를 따른다.
CLI 입력 계약은 다음 명령으로 확인한다.

```bash
uv run --project backend --locked --extra api teoria-pipelines specification --help
```

입력에는 문서 ID·파일명·원본 URI·선택적 checksum, 품목 분류, 실행 상한,
적용할 표준 또는 프로파일 참조를 지정한다. 실제 입력 필드와 검증은
`domains/goods/contracts.py`, `workflows/management_parameters.py`가 기준이다.

## 저장과 재실행

원본·추출 JSON·적용 JSON·보고서·문서별 관찰 본문은 객체 저장소에 둔다.
Data DB는 실행 상태·문서별 요약·산출물 URI·checksum을 저장한다.
산출물 저장과 적재가 성공한 뒤에만 완료 checkpoint를 갱신한다.

원본·모델·파서·처리 코드의 식별자를 고정한다. 재사용 가능한 단계만 checkpoint로 복원하며,
실패한 문서는 격리해 재처리할 수 있다. 평가 실행은 추출을 다시 수행한다.
기존 결과는 덮어쓰지 않고 새 실행과 processor revision으로 구분한다.
과거 저장 경로의 `specification_processing/` 접두사는 호환을 위해 유지한다.

## 승인과 적용의 차이

표현 등록은 원문 표현의 검증이다. 새 개념의 게시 승인이 아니다.
의미 후보와 Ontology 비교 결과는 Suggestion이다. 검토·승인·게시 절차를 거쳐야 한다.
Worker는 인증된 Admin HTTP API로 의미 작성과 승인을 요청한다.

적용 기준은 게시 프로파일, 고정 추출 규칙, 추출 draft를 구분한다.
추출 표준의 자동 채택은 draft이며 Published Ontology를 변경하지 않는다.
`legacy_dictionary/`는 과거 v1 평가·재현을 위한 호환 코드다.
활성 v2 경로는 새 로컬 의미 원장을 만들지 않는다.

## 실행 환경

규격서 Worker에는 별도 parser 실행 환경과 Codex CLI·인증이 필요하다.
동시 실행과 모델 호출에 상한을 두고, DB 연결을 Task 사이에 공유하지 않는다.
업로드와 원본·산출물 미리보기는 인증·허용 경로·크기·checksum을 검증한다.
운영은 객체 저장소와 별도 Admin token을 사용한다.

[물품 모델](../model.md) · [표현 연결](../expression_links.md) ·
[프로파일](normalization_profiles.md) · [평가](evaluation.md) ·
[배포](../../../deployment/compose.md)
