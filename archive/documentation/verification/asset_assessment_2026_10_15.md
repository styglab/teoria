# 자산 진단 실행 검증: 2026-10-15

이 문서는 당시 환경의 실행 결과다. 현재 설정과 사용 절차는
[자산 진단](../../../docs/platform/metadata/asset_assessment.md)을 따른다.

## 검증 환경

현재 운영의 로컬 Qwen3.8-27B는
8,192토큰 문맥으로 실행되므로 출력 한도를 2,048로 두고 소수 컬럼부터 진단한다.
대량 컬럼·긴 법령을 처리하려면 더 큰 문맥의 모델이나 입력 분할이 필요하다.
기존 모델 컨테이너는 `teoria_default` 네트워크의 `metadata-model` 별칭으로 연결한다.
이 컨테이너를 재생성하면 네트워크 별칭도 다시 연결해야 한다.

## 결과

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
