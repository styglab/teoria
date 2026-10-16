# OpenMetadata 업그레이드 검증

검증·배포일: 2026-10-13. 격리 검증 후 운영 Server와 ingestion을 1.12.6에서
2.0.5로 업그레이드했다. 저장소 배포 기본값과 운영 `deploy/compose/.env`의
`OPENMETADATA_VERSION`은 2.0.5다. 운영 업그레이드는 아래 전환 순서에 따라
별도 수행했으며 기본값 변경만으로 DB migration을 대신하지 않는다.

[공식 안정 릴리스 2.0.5](https://github.com/open-metadata/OpenMetadata/releases/tag/2.0.5-release)는
2026-10-08 공개되었다. 사용자 관리 메타데이터 보존과 ingestion 회귀 수정,
보안 의존성 업데이트를 포함한다. 운영은 검증한 명시 버전을 고정하고
`latest`를 자동 추종하지 않는다.

## 격리 환경 검증 결과

운영 `openmetadata_db`의 custom-format 백업을 별도 PostgreSQL 17에 복원했다.
별도 Elasticsearch 9.3.0과 내부 Docker network를 사용했으며 운영 검색 인덱스를
공유하지 않았다. 메타데이터 ingestion만 운영 Data DB의 기존 read-only 계정으로
읽고 결과는 격리 OpenMetadata에 썼다. 운영 원문 샘플 수집은 수행하지 않았다.

| 검증 | 결과 |
|---|---|
| 1.12.6 DB에서 2.0.5 `openmetadata-ops.sh migrate` | 중간 Server를 실행하지 않고 직접 성공 |
| 전체 검색 `reindex --force` | 성공, Teoria 테이블 검색 응답 확인 |
| 테이블 53개의 ID·FQN·설명·소유자·태그·컬럼 | migration 직후 선택한 필드가 변경 전과 일치 |
| Database 1개·Schema 2개·DB Service 1개 | 기존 ID 전부 보존 |
| Glossary 1개·Term 1개·Tag 13개 | 기존 ID 전부 보존 |
| Teoria catalog DTO·Table 상세·기존 bearer token | 실제 연계 성공 |
| 설명 PATCH·Glossary Term 생성·컬럼 용어 할당 | 실제 연계 성공, 격리 환경에서만 쓰기 |
| Basic Test Suite·Test Case 생성 및 Test Case 조회 | 실제 연계 성공 |
| 샘플·프로파일 미수집 응답 | 정상 조회 및 미수집 구분 |
| 합성 샘플·프로파일 | 기본 마스킹·명시적 값 조회·DTO 변환 성공 |
| 공식 ingestion 2.0.5 | schema metadata 수집 성공, 오류 0건 |
| 빌드한 Teoria ingestion 이미지의 재수집 | 사용자 설명과 컬럼 Glossary 태그 보존 |
| 기존 Semantic Binding의 MetadataTargetRef 17개 | 변경 전후 모두 조회 가능한 참조로 유지 |
| 기존 버전 복구 | 원본 백업을 다른 DB에 복원하고 1.12.6 Server 기동·테이블 53개 조회 성공 |

Basic Test Suite의 `basicEntityReference`는 Table UUID가 아니라 FQN이다.
잘못된 UUID로 실행한 최초 검증의 404는 endpoint 제거 또는 버전 호환 결함이
아니었다. 올바른 FQN으로 기존 Teoria client의 API가 성공했다.
2.0.5 프로파일 입력 timestamp는 epoch milliseconds이며 Teoria 화면은 초·밀리초를
모두 처리한다. profile 결과가 없는 응답뿐 아니라 합성 profile로 지표 변환도 확인했다.

현재 운영 데이터에 Domain entity가 없으므로 기존 Domain 데이터의 migration 보존은
검증하지 못했다. 합성 데이터 검증은 실제 개인정보를 조회하거나 모델에 전달하는
운영 권한·정책 검증을 대신하지 않는다. 복구 검증은 DB 복원과 기존 Server/API까지이며
운영 검색 인덱스 복구는 별도 재색인이 필요하다.

Pipeline 테스트 324개, Platform 테스트 274개가 통과했다. 별도 Application DB가 필요한
14개 테스트는 skip되었다. Connector·Pipeline·Platform 참조 통합 검증과 Compose config도
통과했다. Compose config 검증에서는 기존 .env에 누락된 OPA token에 검증용 placeholder를
사용했으며 이 값으로 운영 서비스에 배포하지 않았다.

## 함께 변경한 배포 계약

- Compose의 Server·migration·ingestion image 기본값과 ingestion build argument.
- 얇은 ingestion Dockerfile과 `.env.example`의 버전 기본값.
- Prefect metadata deployment의 image parameter와 Flow 기본값.
- Metadata Worker의 exact image allowlist.
- version 관련 회귀 검증 및 설정 문서.

`teoria-openmetadata-ingestion:2.0.5` 이미지를 실제로 빌드했다. 일반 Pipeline Worker에는
OpenMetadata ingestion 패키지를 추가하지 않았다. Airflow도 추가하지 않으며 일정과
재시도는 계속 Prefect가 소유한다. Prefect 운영 deployment parameter와 Worker allowlist는
운영 전환 시 함께 갱신해야 한다.

## 운영 전환 순서

2026-10-13 운영 전환에서 최신 백업을 확보한 뒤 migration과 전체 reindex를
완료했다. 테이블 53개의 선택한 메타데이터 필드는 migration 직후 변경 전과
일치했다. 2.0.5 Server와 기존 Teoria Admin의 catalog status·Table 상세 조회,
검색·샘플·프로파일 endpoint가 정상 동작했다. 실제 Prefect 실행
`babafb13-4a32-485d-8ad3-e8241f6e25b8`이 새 ingestion 이미지로 완료됐다.
metadata deployment parameter·Worker allowlist를 함께 갱신하고 기존 매일 05:00 KST
schedule을 재개했다. 배포 등록 Job도 metadata-worker 이미지와 같은 코드를 사용한다.
조달 수집 워커와 Data DB는 이 전환에서 변경하지 않았다.

수집 후 컬럼 446개의 빈 `tags` 표현이 빈 배열과 누락 값 사이에서 정규화되었다.
빈 값을 동일하게 비교하면 실제 태그·컬럼 정보는 보존되며 사용자 설명·소유자·
테이블 태그도 유지됐다. 운영 Binding 대상 17개가 모두 조회 가능한 참조로 남았다.

정상 동작 확인 후 사용하지 않는 1.12.6 Server·ingestion 이미지와 이전 metadata-worker
이미지, 이번 검증에서 사용한 임시 Platform 이미지 태그를 정리했다.
변경 전 운영 DB 백업은 `.artifacts/openmetadata_upgrade/openmetadata_production_before_2_0_5.dump`에
권한을 제한해 보존한다. 이미지 정리는 백업 삭제를 포함하지 않는다.

재사용할 업그레이드·복구 절차는 [OpenMetadata 배포](../deployment/openmetadata.md)를 따른다.
위 결과는 2026-10-13의 특정 버전·데이터·환경에 대한 검증이다.

백업과 상세 로그는 `.artifacts/openmetadata_upgrade/`에 권한을 제한하여 보관한다.
DB 백업은 인증 설정을 포함할 수 있으므로 Git에 추가하지 않는다. 일회성 credential
파일과 검증 컨테이너·network는 검증 종료 후 제거한다.
