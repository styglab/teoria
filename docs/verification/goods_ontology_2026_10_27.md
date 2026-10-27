# 물품 Ontology 경계 이관

> 과거 작업의 검증 기록이다. 이 문서의 물품 모델·조회 기능·관찰 데이터는 후속
> [초기화](specification_goods_reset_2026_10_27.md)로 운영에서 삭제했다. 이전 산출물은 백업에 보관한다.

Compose 운영의 활성 의미 모델을 `computer_server`에서 `goods`로 이관했다.
물품 Ontology가 검토·게시 단위이고, 서버·메모리는 그 안의 개념이다.
물품분류 `4321150102`는 서버 프로파일의 적용 범위이며 별도 Ontology를 식별하지 않는다.
문서별 값·연산·범위·근거는 계속 관찰 데이터로 관리한다.

## 게시와 이력

| 대상 | 운영 상태 |
|---|---|
| 물품 Ontology | `goods` 0.2.0, published |
| 서버 프로파일 | `server_memory` 2.0.0, approved |
| 공개 Capability 3개·내부 조회 1개 | ID·입력·응답 구조 유지, 의미 참조 변경에 따라 version 2.0.0 |
| Registry·Runtime bundle | `2026.10.27.2` |
| 이전 `computer_server` 0.1.0 | deprecated; 원본 artifact·개념 ID·감사 보존 |
| 이전 프로파일 1.0.0·1.0.1 | deprecated; 승인 패키지·이력 보존 |
| 이전 Capability Binding 5개 | deprecated; 새 goods Binding 5개 승인 |

객체 2개·속성 4개·관계 1개의 의미를 유지했다. namespace 소유권이 달라 새 개념 ID를 생성했으며,
이전 ID를 바꾸거나 두 namespace의 ID를 동일하다고 간주하지 않는다.
7개 개념의 명시적 대응과 운영 version ID는
`backend/authoring/ontology_migrations/applied/2026_10_goods_ontology/receipt.yaml`에 기록했다.
기존 신규 제안 73건은 원래 Draft에 남아 있으며 새 Published 모델에 채택하지 않았다.
이전 상위 Flow의 승인 대기 상태는 역사적 실행이다. 새 표준관리 입력은 승인된 goods 프로파일을 사용해야 한다.

## 재적용과 조회 검증

이번 작업은 의미 경계 이관이다. 기존 운영 추출 checksum
`405129d0ebd476cc237e4d1a6c4b1f0a1328e2b9a026ba27f839032a9c2e7dd0`과 원본 2개를 검증해
새 승인 패키지로 재적용했으며 AI를 다시 호출하지 않았다.
병행 수정 중인 Parser는 배포하지 않았다. Worker에는 이전 검증 이미지의 Parser를 고정했다.

새 실행 `goods_server_memory_20261027_01`의 결과는 이전과 같이 `partial`이다.
요구조건 310건 중 서버 메모리 관찰 3건을 적용하고 307건은 보류했다.
서로 다른 원문 위치의 512GB 요구값 3개이며 문서 3개나 서버 3대를 뜻하지 않는다.
16GB 모듈 조건은 `raw` 연산·`per_module` 범위를 유지하며 숫자 관찰로 승격하지 않았다.

새 migration 094는 조회 view에 goods 관찰을 추가하고 이전 namespace의 관찰도 유지한다.
새 관찰 3개와 이전 관찰 3개의 값·단위·역할·범위·연산·한정자·원문 참조·소유자 등 17개 필드를
명시적 key 대응 후 비교하여 일치함을 확인했다. 이전 관찰·실행·본문은 수정하지 않았다.
새 bundle 전환 직전 이전 Runtime의 새로운 검색 요청도 이전 관찰 3건을 반환했다.

새 bundle에서 실제 인증 HTTP 요청으로 다음을 확인했다.

- 공개 discovery 3개, 인증 없는 요청 HTTP 401.
- 메모리 64GB 이상 검색: goods 관찰 3건. 이전 namespace 관찰을 중복 노출하지 않음.
- 600GB 이상 검색 및 raw 모듈 조건 검색: 0건.
- pagination: page_size 1의 두 번째 페이지 1건, 총 3건.
- 두 문서 비교: `not_comparable`; 정렬 가능한 조건이 없어 수치 차이를 생성하지 않음.
- 원문 근거: `verified`, 원문 구절과 추출 checksum 확인. 없는 observation은 `not_found`.

기존 Ontology·프로파일·Binding 사용 종료 후에도 gateway를 통한 이전 observation의 근거 조회가
`verified`를 반환했다. 같은 gateway의 새 검색은 goods 관찰 3건을 반환하며 Admin·Runtime health와
Ontology·API 문서 경로의 HTTP 200도 확인했다.

활성 bundle checksum은
`sha256:9bca0542483e97f34b1c039c97500c743c8402715905d1e51b610c36c143fe29`다.
게시 Ontology artifact 2개(`teoria`, `goods`), 승인 Binding 21개, Capability 4개를 포함한다.
이전 bundle은 원본 checksum으로 보존하여 조회 서비스 rollback에 사용할 수 있다.
새 bundle의 운영 동작은 독립적인 모델 정확도나 전체 표준화 완료를 의미하지 않는다.

## 검사와 산출물

백엔드 전체 검사 608 passed / 46 skipped. 실제 격리 PostgreSQL·OPA·checksum bundle을 사용하는
서버 경로 통합 검사 1 passed. Registry validate·명시적 manifest의 migration report·Compose config 통과.
원문 기반 소유자 검사에는 goods와 이전 computer_server namespace를 모두 포함한다.
문서 검사 7 passed이며 전체 최종 검사 합계는 615 passed / 46 skipped다. 격리 검증 컨테이너는 정리했다.

실행 입력·API 응답·검사 로그·ID 대응·실제 Runtime 응답은 `.artifacts/goods_ontology_2026_10_27/`에 있다.
운영 산출물은 기존과 같은 `teoria_specification-artifacts` volume에 새 run ID로 저장한다.
반영 전 Application DB와 규격서 Data 테이블 dump, checksum·이전 이미지·bundle 참조는
`backups/teoria/goods_ontology_20261027/`에 보존한다. 기존 전체 백업도 유지한다.

물품 Ontology 화면은 `/admin/semantic-model/ontology?version=1a95c9a3-6f85-410b-8cf4-083a5d2b0158`이다.
업무 개념의 속성과 관계도에서 서버·메모리·구성 관계를 확인할 수 있다.
