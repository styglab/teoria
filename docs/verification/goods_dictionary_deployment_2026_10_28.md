# 표준 의미 자동 작성·승인의 운영 Worker 반영

2026-10-28 사용자의 운영 반영 요청에 따라 로컬 Compose 규격서 Worker를 교체했다.
외부 EC2/K3s 배포 기록은 아니다.

## 배포와 확인

- 대상: `teoria-prefect-worker-1`, pool `teoria-specification`.
- 이미지: `teoria-pipelines:goods-dictionary-20261028-v3`.
- 이미지 ID: `ea322f0481c30ede21338363374a4ed6565876b5eaeca0e13e212cbce69b18de`.
- 이전 실행 이미지 위에 Flow·입력 계약·Admin client·사전 연결·Codex 의미 작성·공개 의미 계약의 6개 파일만 반영했다.
- 실행 중/Pending/Cancelling Flow가 없음을 확인한 뒤 교체했다.
- 설치한 6개 파일의 checksum이 작업공간 코드와 일치하고, 기존 환경·볼륨이 보존됨을 확인했다.
- 새 ProcessWorker `dc3484ec-e683-4699-b1e2-595b19f9fd3e`의 ONLINE·heartbeat를 확인했다.
- 필요한 사전 작성·승인 API는 기존 Admin 서비스에 있으므로 API·Runtime·다른 Worker를 교체하지 않았다.
- `deploy/compose/.env`의 `TEORIA_SPECIFICATION_WORKER_IMAGE`에 릴리스 태그를 고정했다.
- 이전 이미지는 `teoria-pipelines:goods-relations-before-dictionary-20261028`로 보존했다.
- DB migration과 Published Ontology 게시를 실행하지 않았다.

자동 승인은 표준관리 모드에서 동작한다. 기존 승인 매핑은 재사용하고, 미해결 의미를 Codex로 판단·별도 재검증한다.
코드 검증을 통과한 정의·매핑은 인증된 Admin API로 승인한다. 옵션을 끄면 제안으로 보존한다.
문서처리 모드는 새 의미를 작성하지 않는다.

## 검증의 경계

코드 검사: 백엔드 699개 통과·79개 건너뜀, 후속 의미 작성·문서 검사 19개 통과.
소유 대상·절 근거 전달 보완 후 규격서·구조 검사 255개, 마지막 프롬프트 보완 후 정규화 검사 29개가 통과했다.
Compose config 검증을 통과했다. 실제 모델 검증은 아래 실행 결과와 구분한다.

배포 메타데이터와 checksum은
[설치 확인](../../.artifacts/goods_dictionary_deployment_20261028/deployment.json)에 보존했다.
실제 검증은 기존 LC-MS 추출의 ‘용매 운반용 펌프 / 허용최대압력 105 MPa’ 부분만 사용한다.
원문 재파싱·02–05 재추출이나 전체 문서 품질 평가가 아니며, 06–08의 Codex·Admin API·저장 연결을 확인한다.

## 실제 모델·Admin API 검증 결과

- 실행 ID: `dictionary_semantics_deployment_20261028_03`, 모델 `gpt-6.1-sol`.
- 기존 LC-MS 원문에서 추출한 펌프 1개·허용최대압력 관찰 1개로 06–08 Task 본문을 실행했다.
  Prefect 배포 전체 실행·Data DB 완료 checkpoint 검증은 아니다.
- 최초 실행에서 펌프 유형 정의·매핑을 자동 승인했다. 속성 검증에 원문 소유 문맥이 부족한 문제가 드러나,
  소유 대상·절·귀속 근거 본문을 함께 전달하도록 보완했다.
- 다음 실행의 서로 다른 원문 줄을 합친 인용은 근거 검사에서 보류했다. 한 원문 근거 안의 연속 구절만
  인용하도록 지시를 명확히 했으며 근거 검사 기준을 완화하지 않았다.
- 최종 실행에서 펌프 유형 승인 매핑 1건을 재사용하고, 허용최대압력 정의·매핑 1건을 자동 승인했다.
- 사전 의미 연결은 2건 모두 resolved이며 속성의 typed_value는 decimal 105, unit MPa다.
- 두 정의·두 매핑의 Admin 감사 이력에 approve가 기록됐음을 조회했다.
- normalized.json·사전 판정·연결 결과·표준 후보·로컬 표준 draft·Markdown 보고서를 저장했다.
- 고정 추출 표준 source_only의 속성 적용은 여전히 보류 1건이다. 로컬 사전 의미 연결과 Published
  Ontology/고정 프로파일의 속성 적용은 다른 결과이며, 후자까지 완료했다고 표시하지 않는다.

[배포 실행 요약](../../.artifacts/goods_dictionary_deployment_20261028/verification_v3.json) ·
[사람이 읽는 보고서](../../.artifacts/goods_dictionary_deployment_20261028/results_v3/index.md) ·
[Codex 판정·재검증·승인 결과](../../.artifacts/goods_dictionary_deployment_20261028/results_v3/dictionary_semantic_decisions.json) ·
[표준 의미 연결 결과](../../.artifacts/goods_dictionary_deployment_20261028/results_v3/normalized.json).

운영 파일은 specification-artifacts 볼륨의
`/app/specification_artifacts/goods_dictionary_deployment_20261028/specification_processing/dictionary_semantics_deployment_20261028_03/`에 있다.
코드 복사에 사용한 임시 이미지 빌드 디렉터리는 제거하고, 이미지·배포 메타데이터·입력 부분집합·실행 결과를 보존했다.
