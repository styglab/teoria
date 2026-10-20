# 컴퓨터서버 실제 10건의 초기 사전 구축

2026-10-20 실행 결과다. **사전 후보를 만들고 수정·재검증했지만 승인하지 않았다.**
후속 [속성 단위 감사](../attribute_registry.md#현재-초안의-과분리와-재검토)에서 표현 차이와
요구 문장이 정의에 섞인 것을 확인했다. 아래의 152개·보완안 189개는 초안 레이블 수이며
서로 다른 표준 속성 수가 아니다. 원문 해석 보류 19개만 해결하면 사전 품질이 통과하는
것으로 해석하지 않는다.
예전 속성 52개 사전은 입력에 사용하지 않았다. 기존에 보존한 규격서 원본 10건을
kordoc 4.22.15로 다시 파싱했다. OCR과 수식 OCR은 모두 껐다.

## 결과

| 항목 | 개수·상태 |
|---|---|
| 서로 다른 실제 공고 | 10건: HWP 6·HWPX 2·PDF 2 |
| 원문 관찰 | 385개 |
| 속성 조건 | 356개: 사전 연결 338·해석 보류 18 |
| 설치·소프트웨어·검증 작업 | 29개: 요구조건 보존, 속성 정의에서 제외 |
| 속성 정의 후보 | 152개 |
| 대상 유형 후보 | 25개: 발주묶음·서버 본체·구성요소 포함 |
| 정의가 관찰된 범위 | 한 공고만 107개 / 여러 공고 45개 |
| 최종 검토 | 583개 항목 자기검토, 미해결 문제 19개 |
| 로컬 승인·운영 게시 | 하지 않음 |

`server_06`은 컴퓨터서버 수집 표본에 포함됐지만 실제 문서는 워크스테이션 규격이다.
이를 일반 랙 서버 구성으로 강제하지 않았다. 이번 10건은 새 무작위 표본이 아니라
보존 원본의 재검증 표본이며 독립 precision/recall을 측정한 결과가 아니다.

## 무엇을 어떻게 실행했나

1. 공고 번호가 다른 10건의 원본·새 파싱·적합성 판정·파서 실행 기록을 고정했다.
2. Codex가 원문을 읽어 주요 구성·하위 대상·기보유 대상을 구분했다.
3. 기존 사전 ID 없이 원문 조건과 속성 의미 후보를 작성했다.
4. 의미 후보를 비교해 사전 정의와 원문 연결을 제안했다.
5. 코드 검사와 Codex 원문 대조에서 찾은 문제를 새 revision으로 수정했다.
6. 현재 입력에서 초안을 다시 계산하고 최종 검토와 해시를 검사했다.

의미 판단은 Codex가 직접 수행했다. 배치별 Python 파일은 그 판단을 JSON으로
저장하는 재현 기록이며 범용 의미 추출 알고리즘이 아니다. 외부 LLM API·내부 Qwen
모델은 호출하지 않았다. 원본 10건은 보존본과 SHA-256이 모두 일치했다.

## 실제로 수정한 문제

- 기보유 DDR4 호환 요구의 출처가 증빙서류 제출 위치에 연결된 오류를 수정했다.
- 서버 2대·랙 1식 발주에서 묶음과 서버 한 대의 규격 단위를 분리했다.
- 납품 메모리 모듈 수와 지원 슬롯 수, GPU 납품과 향후 확장 대안을 구분했다.
- 설치·검증 작업을 제품 속성으로 등록하지 않고 별도 원문 요구로 남겼다.
- 마지막 초안 157개에서 중복 정의 5쌍을 합쳐 152개로 정리했다. 모델의 지정·동등
  비교 방식은 요구조건 연산자에 남겼다. SSD/HDD와 장비 점유 높이/랙 수용 높이는 구분했다.
- Memory·RAM·메모리 용량에는 시스템 장착 메모리 문맥과 실제 원문 동의어 근거를 붙였다.
- 숫자 검사기가 공백을 제거해 DDR5와 512GB를 붙여 읽던 문제를 수정했다.
- 단위가 생략된 개수는 count 차원으로 검사하되 원문 단위는 null로 보존했다.
- 삭제한 중복 정의의 이전 검토 지적도 수정본에서 해결 여부를 확인하도록 했다.

## 왜 아직 승인하지 않았나

미해결 문제 19개는 해석 보류 18개와 원문 110W 확인 1개다. 전원 출력의 개별/전체
기준, CPU 클럭의 기본/부스트 기준, HBA의 32GB 표기, SSD SATA와 12Gbps의 병기,
랙의 필수/선택 여부 등이 해당한다. 110W를 1100W로 임의 교정하지 않았다.

또한 한 공고에서만 관찰된 정의 후보 107개를 모두 안정된 표준 속성으로 보기는 어렵다.
추가 중복·원자성·적용 범위 검토가 필요하다. **파이프라인 실행과 수정 경로는 확인했지만
사전 품질의 최종 통과를 선언한 결과는 아니다.** 다음 배치의 승인 사전으로 사용하지 않는다.

최종 build의 차단 코드 36개와 check의 차단 코드 93개는 같은 조건을 여러 검사가
보고한 결과다. 별개의 오류 93건이라는 뜻이 아니다. 종료 코드 2는 미해결 상태를
나타낸다. 원문 확인이 필요한 조건을 오류 목록에서 지워 통과시키지 않았다.

## 먼저 볼 파일

로컬 결과 폴더는 `.artifacts/procurement_specifications/server_dictionary_bootstrap_2026_10_20/`다.

- [쉬운 결과 설명](../../../.artifacts/procurement_specifications/server_dictionary_bootstrap_2026_10_20/result.md)
- [속성 후보 목록](../../../.artifacts/procurement_specifications/server_dictionary_bootstrap_2026_10_20/attribute_dictionary.md)
- [속성 CSV](../../../.artifacts/procurement_specifications/server_dictionary_bootstrap_2026_10_20/draft_r6/attributes.csv)
- [보류 조건 목록](../../../.artifacts/procurement_specifications/server_dictionary_bootstrap_2026_10_20/pending_review.csv)
- [실행·원본 무결성 요약](../../../.artifacts/procurement_specifications/server_dictionary_bootstrap_2026_10_20/result_summary.json)

최종 구성·관찰은 `source_r7`, 통합 제안은 `consolidation_r6.json`, 사전 초안은
`draft_r6`, 검토는 `final_review_r6.json`, 최종 검사는 `final_check_r6.json`이다.
이전 결과는 덮어쓰지 않았다. 결과 파일은 로컬 산출물이며 저장소에 배포되는 사전이 아니다.

## 코드 검증

초기 구축 테스트 **41개**를 포함해 Pipeline 전체 **266개 통과·16개 건너뜀**이었다.
기존 Prefect 그래프 생성 경고 1개가 있었으며 실행 시간은 49.35초였다.
이는 코드 계약 검사이며 실제 추출 정확도 측정을 대신하지 않는다.

실행 절차는 [초기 사전 구축](../dictionary_building_pipeline.md), 앞선 합성 계약 검증은
[구현 검증 기록](dictionary_bootstrap_2026_10_20.md)을 참고한다.

## 재개 세션의 추가 원문 검토

같은 작업 폴더에 다른 실행 경로의 변경이 계속 들어오는 것을 확인하여 재개 세션의
보완안은 `resume_review/`에 별도로 저장했다. 위의 r6 집계와 합산하거나 r6의 승인
근거로 사용하지 않는다. 추가 보완안은 같은 공고 10건의 관찰 423개·속성 후보 189개,
사전 연결 379개·해석 보류 16개·속성 외 작업 28개다. 유형 후보는 25개이며,
원문으로 확인한 유형 동의어 6개를 포함한다. 별도의 신규 공고 처리 실적은 아니다.

추가 보완안 역시 미승인이다. 복합 셀의 원자 조건·소프트웨어 버전 대안·동등성 범위,
문자열과 수치 표현 때문에 나뉜 정의의 중복 검토가 남아 있다. `960 GB × 2 이상`의
비교 범위도 별도 검토 항목으로 남겼다. 열린 검토 지적 35개와 검사 진단 169개는
서로 다른 집계이며, 코드 수를 독립적인 의미 오류 수로 해석하지 않는다.

- [추가 보완안 요약](../../../.artifacts/procurement_specifications/server_dictionary_bootstrap_2026_10_20/resume_review/summary.json)
- [추가 속성 후보 CSV](../../../.artifacts/procurement_specifications/server_dictionary_bootstrap_2026_10_20/resume_review/final_draft/attributes.csv)
- [추가 검토 지적 CSV](../../../.artifacts/procurement_specifications/server_dictionary_bootstrap_2026_10_20/resume_review/review_findings.csv)
- [추가 최종 검사](../../../.artifacts/procurement_specifications/server_dictionary_bootstrap_2026_10_20/resume_review/final_review_check.json)

재개 과정에서 기존 `author_source_review_r3.py`와 보조 스크립트 이름이 겹쳤다.
새 보완 스크립트는 `resume_review/author_amendments.py`로 이동했고, 기존 r3
진입점은 보존된 `source_r3` JSON을 재사용하는 재현 어댑터로 복구했다.
원래 보조 스크립트 텍스트를 복구한 것은 아니다. 원본·분석 JSON은 보존했으며
어댑터가 문서 10건의 저장 관찰·논리 그룹을 그대로 읽는 것을 확인했다.

## 속성 단위 판단의 원문·계약 재검증

이전의 76개 유지·7개 통합·27개 재구성·19개 문맥 이동·23개 보류는 수작업 제안이다.
이번 검증은 그 분류의 숫자를 정답으로 사용하지 않았다. 특히 포함/지원 문구만으로
속성에서 제외할 기준은 입증되지 않아 **19개 확정 제외라는 해석을 철회한다.**

### 실제 확인 범위

- r6 초안을 현재 입력에서 다시 계산해 저장본과 정확히 일치하는지 확인했다.
- 152개 정의의 매핑과 이전 분류표를 대조했고, 관찰 385개·인용 394개가 저장 파싱의
  문서·노드·인용에 연결되는지 확인했다. 모든 정의에는 연결 관찰이 있었다.
- 보존 원본 10건을 로컬 `kordoc_python` 0.8.0으로 다시 읽고 선택한 기술 문구 42개를
  모두 확인했다. OCR은 사용하지 않았다. 이 결과로 기존 kordoc 고정 입력을 교체하지 않았다.
- 원문 기반 의미 판단 16사례와 메모리 안에서만 실행하는 계약 시험 11개를 수행했다.

인용 394개 검사는 저장 파싱과의 일치다. 원본 재파싱은 선택한 42개 문구의 재확인이며
전체 문서의 독립 정확도 평가가 아니다. 의미 판단도 같은 개발 표본의 Codex 자기검토다.

### 확인된 결함과 구별해야 할 조건

NIC 모델 081/150은 같은 모델 의미가 집계·장착 상태 때문에 나뉜 사례로 확인했다.
포트 수 044/091과 네트워크 속도 021/069도 원문 표현용 정의와 표준 의미가 섞였다.
단, `Dual Port`, `16C`, `10K`를 수치로 강제 변환한 결과는 아니다. 미확정 값은 관찰에서
보류해야 하며 raw 표기라는 새 표준 속성을 만들 근거로 쓰지 않는다.

기본/부스트 클럭, 장착/최대 지원 메모리, 모듈당/시스템 용량, CPU당/서버 전체 코어,
장비 점유/랙 수용 높이의 5개 구분은 원문에서 확인했고 강제 통합 시 코드도 차단했다.
반면 NIC 상태 082/147은 같은 인용을 사용한다는 사실만으로 의미 중복을 단정할 수 없다.
전체 상태와 파생 플래그의 관리 정책을 정해야 한다.

### 코드 검사의 탐지 한계

기존 build의 차단 코드 36개를 기준으로 추가 진단이 생기는지 비교했다.

| 시험 | 추가 차단 |
|---|---|
| 같은 정의를 다른 ID·동의 이름으로 복제 | 없음 |
| 같은 수량을 다른 measurement_basis 문구로 분리 | 없음 |
| 기본 클럭 정의를 부스트 클럭으로 오명명 | 없음 |
| `128 GB 이상`의 GE를 LE로 뒤집고 operator_text=null 유지 | 없음 |
| 위의 서로 다른 의미 5쌍을 강제 통합 | 5개 시험 모두 차단 |
| 원문 문자열 포트 수를 수치형 속성에 직접 연결 | signature 불일치로 차단 |
| 같은 NIC 모델의 장착 상태 차이를 그대로 두고 통합 | signature 불일치로 차단 |

추가 차단이 없다는 것은 해당 새 문제를 검사가 탐지하지 못했다는 뜻이다. 기존 차단
항목 때문에 배치 전체는 여전히 미승인 상태이며, 승인 시도나 운영 반영은 하지 않았다.
현재 계약은 원문 값의 자료형과 표준 의미·값 해석을 충분히 분리하지 못한다. 단순히
중복 ID를 없애는 수정에 앞서 이 경계와 속성·구성·요구조건 기준을 정해야 한다.

유지 후보에도 온도·습도 범위가 text/none 차원으로 들어 있다. 성질의 유용성과
정규 값 계약의 완성도는 구별해야 하므로 **최종 적정 속성 수는 아직 검증되지 않았다.**

### 재현 기록

`granularity_audit/verification_v1/`에 저장했다.

- [검증 요약](../../../.artifacts/procurement_specifications/server_dictionary_bootstrap_2026_10_20/granularity_audit/verification_v1/summary.json)
- [원본 파일 재확인](../../../.artifacts/procurement_specifications/server_dictionary_bootstrap_2026_10_20/granularity_audit/verification_v1/original_file_checks.json)
- [16개 원문 의미 검토](../../../.artifacts/procurement_specifications/server_dictionary_bootstrap_2026_10_20/granularity_audit/verification_v1/semantic_findings.json)
- [11개 계약 시험](../../../.artifacts/procurement_specifications/server_dictionary_bootstrap_2026_10_20/granularity_audit/verification_v1/guard_probes.json)
- [152개 후보의 검증 상태](../../../.artifacts/procurement_specifications/server_dictionary_bootstrap_2026_10_20/granularity_audit/verification_v1/candidate_verification.csv)

각 실행 스크립트와 결과 checksum을 같은 폴더에 보존했다. 원본·두 초안·기존 검토와
승인 기록·실행 모듈을 변경하지 않았다.
