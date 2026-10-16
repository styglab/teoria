# 검증 기록

특정 날짜·데이터·version에서 확인한 실행 결과와 한계를 보존한다.
문서의 건수·기능 수·환경값은 검증 당시 관찰이며 현재 운영 상태를 뜻하지 않는다.
현재 실행·개발 방법은 [문서 목차](../index.md)의 해당 프로젝트 문서를 따른다.

| 기록 | 검증한 범위 |
|---|---|
| [Context vertical](vertical_slice_verification.md) | 대표 계약금액 질문의 의미 연결·실행·DB 대조 |
| [공고 Context vertical](bid_notice_vertical_verification.md) | 공고 질문·실행 계약·데이터 품질 |
| [공공조달 수집 점검: 2026-10-12](procurement_collection_2026_10_12.md) | 특정 과거 계약 구간의 원본·적재 결손 |
| [OpenMetadata 업그레이드: 2026-10-13](openmetadata_upgrade_2026_10_13.md) | DB 복원·migration·연계·재수집·기존 버전 복구 |
| [조달 탐색 단회 관측: 2026-10-13](procurement_exploration_2026_10_13.md) | 소비자가 보고한 검색 시간과 비교 한계 |
| [자산 진단: 2026-10-15](asset_assessment_2026_10_15.md) | 모델·Worker·API의 실행·결과 저장 경로 |
| [첨부문서 기능 보류: 2026-10-16](bid_document_archive_2026_10_16.md) | archive 이동·배포 제거·큐 요청 보존·한국시간 경계 |
| [Compose 수집 Worker 재배포: 2026-10-16](compose_pipeline_resources_2026_10_16.md) | 기존 실행 완료 대기·자원 상한·Queue 정책·실제 실행과 재시도 |

새 기록에는 기준일·version·입력 범위·검증 방법·결과·한계를 명시한다.
원본 credential·개인정보·비공개 응답은 기록하지 않는다. 실행 검증 성공과 의미·모델 품질
평가는 구분한다. 바뀐 운영 절차는 기록 본문을 복제하지 않고 현재 가이드에 반영한다.
