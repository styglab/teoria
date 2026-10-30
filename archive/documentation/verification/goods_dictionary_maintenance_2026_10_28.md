# 사전 일괄 구축·개정·버전 고정의 운영 반영

> 현재 저장소에 없는 과거 로컬 산출물은 링크 대신 경로로 표시한다. 아래 결과는 작성 당시의 관측이다.

2026-10-28 기존 추출 결과를 사용하는 사전 유지관리 기능을 구현하고 로컬 Compose Admin API와 규격서 Worker에 반영했다.
EC2/K3s 배포나 Published Ontology 게시 기록은 아니다.

## 구현 범위

- 기존 06 Task에서 `dictionary_reconcile: true`를 지정하면 현재 문서와 `dictionary_corpus`를 함께 정비한다.
  같은 코드를 `specification dictionary-maintain` CLI에서도 사용한다. 새 문서 처리 모드·Prefect Flow·기본 schedule은 없다.
- 물품 유형을 먼저, 속성을 다음으로 Codex가 묶음 판단한다. 기존 개념 재사용·새 정의·개정·병합/분리를 지원한다.
- 변경안은 별도 Codex 호출로 재검증한다. 개발 문서에서 실패하면 최대 한 번 수정·재검증한다.
  선택한 별도 검증 문서는 변경안 동결 뒤에만 검사하며 수정에 사용하지 않는다.
- 새 개정은 Stable Concept ID를 보존한다. 의미가 바뀌는 개념은 별도 정의와 명시적 재매핑·이전 개념 중단으로 표현한다.
- 서버가 기준 checksum·의존 소유자·영향 매핑·과거 원문 해시의 검토 누락을 검사한다.
  정의 개정·매핑 교체·중단·감사는 한 transaction이다. 같은 operation ID·같은 요청의 재전송은 결과를 재사용한다.
- 적용 transaction의 정확한 사전 스냅샷을 export한다. 문서처리의 `dictionary_standard` URI·SHA256으로 버전을 고정한다.
- 기존 실행 파일은 유지한다. 새 run_id·기존 extraction_checkpoint·새 사전 버전으로 필요한 문서를 재처리한다.
- 문서처리의 버전 고정은 명시적 옵션이다. 지정하지 않은 기존 입력은 현재 승인 매핑 조회를 유지한다.

## 운영 반영

- Worker: `teoria-pipelines:goods-dictionary-maintenance-20261028-v4`.
- Admin: `teoria-platform-authoring:goods-dictionary-maintenance-20261028-v2`.
- Worker 8개·Admin 6개 설치 파일의 checksum을 작업공간과 대조했다.
- 기존 환경·볼륨을 보존하고 Admin health와 새 Worker heartbeat를 확인했다.
- 로컬 `.env`의 역할별 이미지 변수를 고정했다. 다른 authoring 역할은 Admin 이미지 선택 변수의 영향을 받지 않는다.
- 이전 이미지는 `teoria-pipelines:before-dictionary-maintenance-20261028`,
  `teoria-platform-authoring:before-dictionary-maintenance-20261028`로 보존했다.
- 실행 중/Pending/Cancelling Flow가 없는 상태에서 교체했다. DB migration은 필요하지 않았다.

설치 파일·환경·볼륨 대조 (`.artifacts/goods_dictionary_maintenance_20261028/deployment.json`, 현재 저장소에 없음).

## 실제 검증 결과와 한계

### 실제 DB의 transaction·멱등성

기존 승인 매핑 4개를 의미 변경 없이 재확인했다. 적용 전후 사전 checksum이 같고 재전송 결과가 같았다.
관련 문서 참조 32건을 조회했다. 참조 건수는 서로 다른 원본 문서 수가 아니다.

실제 API·DB 확인 (`.artifacts/goods_dictionary_maintenance_20261028/transaction_verification.json`, 현재 저장소에 없음).

### 네 규격서 전체의 첫 묶음

기존 네 규격서 추출 결과의 687개 속성 관찰에서 원문 표현 297개(유형 144·특성 153)를 묶어 분석했다.
분류 metadata는 null이며 추정하지 않았다. 이미 알려진 문서이고 별도 독립 검증 표본은 아니다.

재검증에서 서로 다른 용도의 고정 벨트 병합, 반사체의 요구·용도 구분 소실,
브래킷 정의의 과도한 일반화, 탈기 장치의 미확정 중복 등 네 가지 문제가 발견됐다.
첫 변경안은 held이며 새 표준 정의·매핑을 적용하지 않았다. 원문 표현 등록은 수행했다.
이후 최대 한 번 수정·재검증하는 개발 경로를 추가하고 회귀 검사했다.
이 네 문서 전체의 초기 사전을 완료했다고 표시하지 않는다.

네 원문 분석 보고서 (`.artifacts/goods_dictionary_maintenance_20261028/four_source_result/index.md`, 현재 저장소에 없음) ·
구체적 보류 사유 (`.artifacts/goods_dictionary_maintenance_20261028/four_source_result/item_type_check.json`, 현재 저장소에 없음).

### 두 원문의 근거가 명확한 부분집합

LC-MS와 동물이송진료 차량 원문에서 물품 3개·속성 관찰 3개만 선택한 묶음으로 실제 모델·API 적용을 검증했다.
원문 재파싱·재추출이나 두 문서 전체의 의미 정렬 검증은 아니다.

- 펌프·인버터와 기존 특성은 재사용했다.
- `large_animal_mobile_treatment_table`과 `large_animal_mobile_treatment_table_allowable_load`를 새 정의로 승인했다.
- 매핑 6개를 재판정해 한 transaction으로 적용했다. 보류 표현은 없었다.
- 영향 보고서에 관련 문서 참조 44건이 포함됐다. 서로 다른 물리 문서 44개를 뜻하지 않는다.
- 새 사전 스냅샷의 내용 checksum은 `6cc2b3e3ff4076e7ec0b5097f44b597e3bf8a62d88000c3bd765a0898e56e156`이다.
- 별도 검증 문서가 없는 development_only 실행이다. 모델 재검증을 독립 정확도 평가로 표시하지 않았다.

실제 일괄 적용 보고서 (`.artifacts/goods_dictionary_maintenance_20261028/focused_result/index.md`, 현재 저장소에 없음) ·
변경안 (`.artifacts/goods_dictionary_maintenance_20261028/focused_result/changeset.json`, 현재 저장소에 없음) ·
확정 사전 스냅샷 (`.artifacts/goods_dictionary_maintenance_20261028/focused_result/dictionary_standard.json`, 현재 저장소에 없음).

### 기존 Task 06 통합과 버전 재사용

같은 부분집합으로 기존 Task 06의 dictionary_reconcile 경로를 실제 실행했다.
원문 6개 재사용, 의미 6개 resolved·보류 0이며 사전 checksum이 유지됐다.
별도 문서처리 실행에서는 해당 스냅샷을 지정해 Codex 호출 없이 6개 표현을 해석했다.
이 검증은 Task 본문 실행이며 Prefect 배포 전체 실행·Data DB 완료 checkpoint 검증은 아니다.

기존 Task 통합 확인 (`.artifacts/goods_dictionary_maintenance_20261028/integrated_task_verification.json`, 현재 저장소에 없음) ·
고정 사전 재사용 확인 (`.artifacts/goods_dictionary_maintenance_20261028/snapshot_reuse_verification.json`, 현재 저장소에 없음).

## 코드 검사

- 마지막 전체 백엔드 검사: 724개 통과·79개 건너뜀.
- 후속 사전 해석 정책 fingerprint와 구조 검사: 14개 통과.
- 사전·문서·Compose 관련 묶음 검사: 92개 통과.
- Compose config·문서 링크 검사를 별도로 실행했다.
- 안정 ID·개정·병합·분리·영향 매핑/과거 문서 누락 차단·stale baseline·transaction rollback·멱등성·인증 actor·
  입력 중복 제거·검증 문서 분리·보류 후 우회 방지·단위 검사·스냅샷 checksum 변조 차단을 회귀 검사했다.

운영 산출물은 `/app/specification_artifacts/goods_dictionary_maintenance_20261028/` 아래에 있다.
원본·정상 실행 결과·이미지를 보존하고 임시 이미지 빌드 디렉터리만 제거했다.
