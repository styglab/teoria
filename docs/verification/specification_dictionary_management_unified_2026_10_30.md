# 사전 관리 목적 통합 — 2026-10-30

표준관리 Flow의 목적을 `dictionary_management`(기본)와 `quality_evaluation` 두 개로 통합했다.
초기 구축과 매일 추가되는 문서는 같은 사전 관리 경로를 사용한다. 사전 관리에 기준 사전을
지정하지 않으면 현재 승인 사전을 사용하고, 지정하면 현재 사전과 일치하는지 확인한다.
품질 평가는 고정 사전 URI·sha256을 필수로 받으며 정의·매핑을 변경하지 않는다.

`force_review: false`는 확인된 의미·문맥을 재사용한다. 새 표현·변경 문맥은 검증 후 추가·개정한다.
`force_review: true`는 기존 항목도 재검토한다. 이 옵션은 품질 평가에서 허용하지 않는다.
기존 `initial_dictionary`·`incremental_update` 입력은 관리 입력 검증 시 `dictionary_management`로
변환하며 전체 재검토를 자동으로 켜지 않는다. Prefect 목적 선택에는 새 이름 두 개만 표시한다.

## 검증과 운영 반영

- 전체 백엔드: **751 passed, 79 skipped**.
- 문서 테스트: **9 passed**. Compose config·배포 문서 일치·공백 검사 통과.
- 두 이전 이름의 정규화, 기본 재사용, 명시적 전체 재검토의 실행 요청 전달,
  품질 평가의 기준 사전 필수·재검토 금지를 검증했다.
- 기존 배포 ID `be281dd8-da46-4057-9cc2-fbe26494accc`에 기본 목적·force_review·두 목적의 schema를 등록하고 조회 검증했다.
- Admin healthy, 새 Worker ONLINE·최근 heartbeat 확인. 교체 전 활성 실행 0개.
- 기존 volume과 이미지 선택 이외의 환경 설정을 유지했다. DB migration은 추가하지 않았다.
- 설치 파일 일치와 운영 확인 결과는 로컬 `.artifacts/specification_parameters_20261030/unified_management/`의
  `deployment.json`, `smoke.json`에 저장한다. 이전 v1 이미지는 보존한다.
- 실제 문서 처리·Codex 호출은 실행하지 않았다.

배포 이미지:

- Admin: `teoria-platform-authoring:specification-parameters-20261030-v2`
- Worker: `teoria-pipelines:specification-parameters-20261030-v2`

현재 실행 방법은 [파이프라인 입력](../procurement_specification_processing/pipeline.md#prefect-실행-입력과-기본값)을 따른다.
