# 규격서 분석

명시적으로 입력한 규격서에서 물품·구성품·관계·속성·조건을 추출하고 원문 근거와 함께 저장한다.
현재 코드는 `backend/src/teoria/features/specification_processing/`에 있다.

## 읽는 순서

| 궁금한 것 | 문서 |
|---|---|
| 어떤 단계이며 Codex는 언제 쓰나 | [파이프라인](pipeline.md) |
| 사전에 무엇을 저장하고 조회하나 | [원문 표현·표준 정의·매핑](../platform/goods_dictionary.md) |
| 물품·구성품·분류·속성은 어떻게 표현하나 | [물품 모델](../architecture/specification_goods_model.md) |
| 승인한 표준은 어떻게 적용하나 | [정규화 프로파일](normalization_profiles.md) |
| 추출 품질은 어떻게 평가하나 | [평가 절차](evaluation.md) |
| 실제 운영에서 확인했나 | [Worker 반영·원본 처리](../verification/goods_relation_deployment_2026_10_28.md) |

화면 사용법은 [사용 안내](../platform-guide.md), 실행·재시도는 [Prefect](../pipelines/prefect.md)를 따른다.

## 현재 상태

원본부터 결과 저장까지 실행되며, 보류 항목이 있는 문서는 partial로 남긴다.
원문 표현 등록·승인 매핑 재사용과 구성 관계·방향 검증을 제공한다.
물품별 표준 의미 확대, 별칭·동일 대상·공통 조건의 정렬, 새 goods 모델의 게시·Runtime 연결은 후속 작업이다.

기존 [실행·검증 기록](../verification/index.md)은 현재 사용법과 구분한다.
폐기한 첨부 선별·서버 사전·검색 실험과 초기 설계는 [보관 문서](../../archive/documentation/index.md)에 있다.
