# 원문 표현 등록의 기존 파이프라인 통합 검증

2026-10-27 기존 05 추출 검증 → 06 원문 표현 조회·자동 등록·재사용 → 07 표준 적용 → 08 저장에 통합했다.
별도 dictionary_authoring 모드·dictionary_graphs 입력·dictionary_processing 모듈·전용 Flow를 제거했다.
Prefect의 procurement-goods-dictionary는 배포·실행 중 작업이 없음을 확인하고 메타데이터를 보관한 뒤 삭제했다.
기존 사전 항목·감사·Data DB 이력·원본 산출물과 적용 migration은 유지한다. Data migration 098을 적용했다.

Worker 이미지: teoria-pipelines:goods-pipeline-integrated-20261027
최종 이미지 ID: 077e3a08eab22e8c2aef56162c35918e8a876283acbb1b58e54c77a361f62606

실제 standard_management 실행:
- run_id: goods_pipeline_dictionary_integration_20261027_02
- Prefect run: 7f4e5a4c-e43f-4f7e-97b2-310a771b4cc8
- 신규 승인 0, 재사용 2, 보류 0. 표준 미정렬과 부분 입력으로 결과는 partial이다.
- 동물 차량 원문을 재파싱한 근거에 연결된 인버터·정격출력 3 kW 이상 관찰 checkpoint를 사용했다.
  수동 작성된 일부 관찰의 통합 검증이며 신규 LLM 추출이나 전체 정확도 평가는 아니다.
- source_term_alignment.json은 source_term_ref를 사용하며 canonical type_ref·characteristic_ref를 채우지 않는다.
- 원본 추출은 보존하며 문서 명세는 proposed로 유지한다. Published Ontology·Runtime을 게시하지 않았다.

전체 backend 및 documentation 테스트: 664 passed, 45 skipped. Compose config 검증 성공.
로컬 증적: .artifacts/goods_pipeline_integration_20261027/ (테스트 로그·실행 로그·퇴역 Flow 메타데이터).

45개 등록 항목은 표준 개념 사전이 아니다. 원문 표현 등록 → 범위·근거가 있는 매핑 → 표준 개념 정의가 필요하다.
