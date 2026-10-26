# 검증 기록

- [Compose 자원 상한 적용](compose_resource_limits_2026_10_26.md): 전체 서비스·임시 Job CPU/RAM 제한과 운영 실실행 검증

- [HTTP 진입점 통합](http_gateway_consolidation_2026_10_26.md): Compose nginx 통합 운영 반영·K3s Traefik 직접 라우팅 검증

- [운영 컨테이너 정리](container_cleanup_2026_10_26.md): 구형 MCP·검증 DB 5개 제거, MCP 연결별 실행과 자동 정리

- [계약 구조 변경 운영 재배포](backend_contract_structure_deployment_2026_10_26.md): 운영 서비스 8개 교체·실제 법령/metadata 완료·MCP 클라이언트 보완

- [계약·작성 입력·Prefect 배포 구조 정리](backend_contract_structure_2026_10_26.md): 경로 이관·Source/Connector 근거·역할별 이미지·기존 artifact 호환

- [백엔드 리소스 정리](backend_resource_cleanup_2026_10_26.md): 예제·과거 manifest 보관, 불필요 의존성 제거, 복구 자료 보존

- [백엔드 책임·FastAPI 구조 정리](backend_cleanup_2026_10_26.md): 앱·라우터·Service/Repository·lifespan·의존 경계·567개 검증과 운영 반영

- [통합 백엔드 운영 재배포](backend_consolidation_deployment_2026_10_25.md): 새 이미지 9개 서비스 전환·DB migration·법령/metadata 실실행·기존 artifact 보존

- [백엔드 기능 모듈 통합](backend_consolidation_2026_10_25.md): 단일 Python 프로젝트·프런트엔드 이동·격리 DB/S3·역할별 이미지·기존 artifact 호환 검증

- [법령 수집·조회 복구](law_recovery_2026_10_25.md): 전용 Worker·정기 수집·인증 조회·AI 근거 연결 재개

- [규격서·물품 Ontology 운영 배포](goods_focus_deployment_2026_10_25.md): 새 bundle·migration·Worker·인증·초안과 실제 기동 검증
- [규격서·물품 Ontology 중심 재구성](goods_focus_reconfiguration_2026_10_25.md): 활성 업무 정리, 운영 수집 중단, 테스트·이미지 검증과 미배포 범위

특정 날짜·데이터·version에서 확인한 실행 결과와 한계를 보존한다.
문서의 건수·기능 수·환경값은 검증 당시 관찰이며 현재 운영 상태를 뜻하지 않는다.
현재 실행·개발 방법은 [문서 목차](../index.md)의 해당 프로젝트 문서를 따른다.

| 기록 | 검증한 범위 |
|---|---|
| [비동기 배포·수집 상태: 2026-10-16](async_deployment_collection_2026_10_16.md) | API·실제 Worker·재시도·checkpoint·분류 조회·남은 수집 잔량 |
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
