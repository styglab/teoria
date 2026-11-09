# goods native 의미 Draft 준비 검증 — 2026년 11월 9일

## 범위와 결과

기존 goods 1.0.0은 게시본이 아니라 Draft였다. 원본을 게시하거나 덮어쓰지 않고,
새 작성 입력으로 goods 2.0.0 Draft를 실제 Application DB에 준비했다.
의미 승인·게시·프로파일 승인·자동 연결 생성·Runtime 배포는 수행하지 않았다.

| 항목 | 확인 결과 |
|---|---|
| 원본 | `6bf176a6-913a-4b05-9a95-b8bbf6ba7866`, 1.0.0 Draft |
| 준비 결과 | `89712e6e-6d1c-494d-8377-6735f009d200`, 2.0.0 Draft |
| 원본 보존 | 적용 전후 전체 조회 결과 일치 |
| 새 모델 | Object 17개, Property 87개, Relationship 47개 |
| 개념 변경 | Stable Concept ID 140개 유지, 11개 추가, 20개 제외, 설명 1개 변경 |
| 게시 상태 | 두 버전 모두 Draft, publication 없음 |
| 주체 | 인증된 Admin principal `system:admin`; 사람의 의미 검토 이력으로 표시하지 않음 |
| 미게시 기반 | `based_on_version_id`는 비워 두고 원본·작성 입력·checksum을 감사 이벤트에 기록 |

새 작성 입력은 [goods.yaml](../../backend/authoring/ontology_blueprints/goods.yaml),
이관 분류는 [pending manifest](../../backend/authoring/ontology_migrations/pending/2026_11_goods_native_meaning/ontology_v2.yaml)를 따른다.
기존 메타 정의 Object `item_type`, `characteristic_definition`을 새 버전에서 제외하고
native `server`, `memory_module`과 그 Property를 추가했다. 제외한 원본 정의는 1.0.0에 남아 있다.
문서별 관찰에는 게시 개념 참조를 담는 별도 속성이 있으며, Draft key를 승인된 의미로 취급하지 않는다.

## 실행과 복구 근거

적용 전 `teoria_app`을 PostgreSQL custom archive로 백업하고 `pg_restore --list`로 읽기를 확인했다.
이는 archive 구조 확인이며 복원 리허설을 수행한 것은 아니다.

- 백업: `backups/teoria/20261109T054500Z_ontology_draft/teoria_app.dump`
- 백업 SHA-256: `0895217984bba1aef1a4da8200bfb70729ca2d9aa2fd9cf8677663b491c3e07d`
- 원본 checksum: `fd0123b1a0689a66a4f2e7c764228c878af508278f9db46708fb8c5713430e60`
- 검토한 계획 checksum: `7a6f766b001c0b5ac3af9ab6a9738f3bbf1ee54ca4df98dd780409d61efb33c9`
- 작성 입력 checksum: `5adb0e288b732f0f50d20c9b32294a3b95f06ed9b5bc566555d3f34a01f47225`
- 결과 checksum: `8ace7305c96e8ec69023a39c7d2956c0300cf3042263b4968e3b9d9ee8a8cb2f`

실행 중 Admin 이미지에는 새 작성 route가 없어, 같은 컨테이너 안의 임시 경로에 현재 코드를
복사하고 bearer 인증을 적용한 FastAPI ASGI HTTP 경계를 통해 preview·prepare를 실행했다.
DB 변경은 Admin router → Service → Repository의 잠금·transaction 경로로 처리했다.
직접 SQL 수정이나 이전 Draft의 임시 게시는 사용하지 않았다.
실행 후 기존 Admin HTTP 서비스의 버전 목록에서 두 Draft를 다시 조회했다.
현재 코드로 Admin 이미지를 영구 교체하는 배포는 이번 검증에 포함하지 않았다.

새 API는 [Ontology 안내](../platform/ontology.md)의 Blueprint 절차를 따른다.
계획 재확인, 같은 요청의 재사용, 원본·대상 수정 감지, 과거 key 재사용 차단을 제공한다.
규칙·지표가 있는 원본과 승인 Binding 대상 제거는 자동 준비를 차단한다.

## 실제 규격서 대조

실제 Data API의 `sample_ten_inventory_20261102_03/sample_09` 저장 결과를 읽었다.
대상은 대형언어모델 추론실험용 서버 XLSX이며 SHA-256은
`a8c7ad031dc585cfd104df9c9d4d27b83f2a866838ed6beba6d7a71233ce7a60`이다.
저장 결과는 엔티티 28개, 관계 29개, 속성 87개였고 원문 관찰을 변경하지 않았다.

| 관찰 | 현재 저장 결과 | 새 모델에 적용할 때 남은 검토 |
|---|---|---|
| 모듈 용량 | 32 GB, `per_module`, 소유 대상 `a02` 메모리 모듈 | native 모듈 Property와 의미 연결 검토 |
| CPU 소켓당 최대 용량 | 3 TB, `supported_capability`, scope `support_limit` | 프로파일 예시의 `per_socket`과 다름; 자동 변환하지 않음 |
| 총 슬롯 수 | 32개, `system_total`, 소유 대상 `a03` DIMM 슬롯 | native 서버 Property에 연결하려면 소유 대상 재검토 필요 |

[원문 대조 작성 그래프](../../backend/authoring/specification_examples/server_memory_graph.yaml)는
격리 PostgreSQL에서만 게시한 검증용 goods 정의에 연결해 Subject 2개·Property 3개의
게시 참조·개념 종류·소유 관계 검사를 통과했다. 참조를 추가해도 원문의 값·단위·역할·scope는 유지했다.
이 검증은 작성한 후보 그래프의 구조 검증이며 자동 추론의 정확도나 운영 의미 동등성 승인이 아니다.
실제 저장 추출이 같은 그래프를 자동 생성했다는 증거로 사용하지 않는다.

## 후속: 실제 관찰의 별도 해석 제안

기존 추출의 귀속·scope를 바꾸지 않고 `review-meanings` CLI로 별도 제안을 작성했다.
이번 제안은 에이전트가 원본 XLSX의 shared strings와 실제 저장 관찰을 대조해 작성한 것이며,
사람이 승인한 정답이나 모델 자동 연결 평가 결과가 아니다. 추출·파서 코드는 변경하지 않았다.

실행은 기존 규격서 Worker의 역할·credential을 사용했다. 현재 코드를 임시 경로에 복사해
CLI를 실행했으며 Worker 이미지를 영구 교체하거나 Prefect Flow를 재배포하지 않았다.
원본 result.json은 등록된 S3 URI와 바이트 SHA-256으로 읽고, 2.0.0 Draft는 Admin HTTP로
조회해 기존 결과 checksum을 재확인했다. DB 승인·게시·추출 결과 변경은 수행하지 않았다.

| 관찰 | 보존한 원래 해석 | 별도 제안 | 검사 결과 |
|---|---|---|---|
| 모듈 32GB | `a02`, `per_module` | `goods.memory_module.capacity` 연결 | `requires_review` |
| 소켓당 최대 3TB | `root`, `support_limit`, `supported_capability` | `goods.server.memory_capacity_per_socket_limit`, scope `per_socket` | `requires_review` |
| 총 슬롯 32개 | `a03` DIMM 슬롯, `system_total` | `goods.server.memory_slot_count`, 소유 대상 `root` 서버 | `requires_review` |

대상 2개와 속성 3개가 출처 인용·참조·Property 소유 유형·자료형·단위 검사를 통과했다.
변경 제안은 scope 1개와 소유 대상 1개다. 모든 선택은 검토 대기이며 의미 동등성을 승인하지 않았다.
전체 대상 28개 중 26개, 속성 87개 중 84개는 이번 선택에 포함하지 않았다.
32GB × 2를 전체 64GB라는 새 원문 사실로 생성하지 않았다.

- 입력: `s3://teoria-artifacts/specification_processing/meaning_reviews/server_memory_20261109_01/request.json`
- 입력 바이트 SHA-256: `e3b7cd36204a84e8abb658c6501bd2c9f0ce3ae0dde2db6e41fb959cd9372cd9`
- 검토: `s3://teoria-artifacts/specification_processing/meaning_reviews/server_memory_20261109_01/review.json`
- 검토 바이트 SHA-256: `cd03a229b22605214354fbe90bb68da0647a72a7faf6a6a02659157dbddf6613`
- 검토 본문 checksum: `abaa76cc0138064d8afcf3f49e2e934c19dd497848dd586cd9b90173c60d314c`

S3 쓰기 후 읽기 검증과 같은 CLI 요청의 재실행에서 동일한 참조·checksum을 확인했다.
원본 결과의 바이트 SHA-256 `2de33723ef466d63b8dea61b3c66201e433cb327dfef8a9f32e6a80fa87dfe86`과
Draft checksum은 그대로였고, 버전 목록도 1.0.0·2.0.0 모두 Draft였다.
임시 코드·로컬 원문/응답 복사본은 정리하고 운영 입력·검토 산출물은 S3에 유지한다.

첫 실행에서 Admin API의 S3 역할로 쓰기를 시도했으나 403으로 거절되었다.
정책을 확대하거나 처리 기준 prefix에 제안을 저장하지 않고, 기존 규격서 Worker의
`specification_processing/*` 쓰기 권한으로 실행했다. 실패 시도는 산출물을 생성하지 않았다.
제안 산출물을 프로파일 적용의 승인 근거로 전달하면 코드가 거절한다.

## 코드 검증과 남은 일

- 전체 백엔드: 1,258 passed, 95 skipped. 선택형 DB 테스트는 별도 실행했다.
- 격리 실제 SQL·인증 HTTP 테스트: 5 passed. 원본/게시 artifact 보존, Stable ID 유지,
  동시 재요청, 수정 감지, 롤백, 과거 key 재사용 차단, 인증 주체 기록을 확인했다.
- 문서 테스트: 9 passed. Compose config와 `git diff --check` 통과.

해석 제안 추가 후 전체 백엔드는 1,275 passed, 95 skipped였다. 신규 검토 검사 17개는
원문 보존·잘못된 인용·소유 대상·역할·scope·단위·정수형·변경된 Draft·불변 재실행·적용 차단을 포함한다.
추가한 CLI dispatch와 공개 계약 의존성 검사를 포함한 관련 검사 13개도 통과했다.
문서 테스트 9개·Compose config·`git diff --check`는 통과했다. 전체 문서 링크 검사에는
기존 archive 대상 누락 24건이 남아 있으며 이번에 추가한 경로의 링크 오류는 없었다.

다음 단계는 저장 추출의 scope·소유 대상과 native 의미를 대조한 사람 검토,
새 Draft 승인·게시, 고정 게시 참조를 사용하는 프로파일 승인·문서 적용 검증이다.
작성 API의 영구 배포도 별도 확인해야 한다. 게시 전 Runtime이 Draft를 읽는 경로를 만들지 않는다.
새 검토 CLI의 이미지 반영과 승인·적용 경로·UI도 후속이며 현재 검토 산출물을 운영 적용으로 표시하지 않는다.
