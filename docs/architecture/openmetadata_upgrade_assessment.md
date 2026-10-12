# OpenMetadata 업그레이드 검토

검토일: 2026-10-12. 현재 실행 중인 Server는 1.12.6이고, Compose 기본값,
custom ingestion Dockerfile, Prefect deployment와 이미지 allowlist도 같은 버전을
기준으로 한다. 1.12.6의 배포 정의는 2026-10-06에 도입되었다. 저장소에는 이
버전을 장기 유지해야 한다는 ADR 또는 최신 버전과의 비교 검증 기록이 없다.
현재 버전은 검증 기준의 고정값이지 최신 버전이라는 의미가 아니다.

[공식 최신 안정 릴리스](https://github.com/open-metadata/OpenMetadata/releases/tag/2.0.5-release)는
2026-10-08 공개된 2.0.5다. 메타데이터 보존·bot ingestion 수정과 보안 의존성
업데이트를 포함하므로 최신 안정 버전으로의 업그레이드 검증을 진행하는 것이
타당하다. 운영 이미지를 `latest`로 자동 추종하는 방식 대신 검증된 명시 버전을
고정한다.

## 이번 변경의 범위

1.12.6에서 샘플·프로파일 조회 기능을 추가했다. 2.0.5 소스에도 동일한
`/{id}/sampleData`, `/{fqn}/tableProfile/latest` 경로가 존재하는 것을 확인했다.
이 확인만으로 DB migration, bot 권한, 실제 응답과 ingestion 호환성을 검증했다고
간주하지 않는다. 운영 OpenMetadata 버전은 이번 작업에서 변경하지 않는다.

## 업그레이드 완료 조건

- 운영 Metadata DB의 백업을 복원한 격리 환경에서 공식 migration 수행.
- PostgreSQL·Elasticsearch와 JVM 환경의 공식 지원 버전 대조.
- Table·Column·Tag·Glossary·Owner·Custom Properties·Binding 대상 ID 보존 검증.
- 이번 샘플/프로파일 API와 권한 오류, 마스킹 동작 Live 검증.
- Server·ephemeral ingestion image·설정 schema·Prefect image allowlist 함께 변경.
- 메타데이터 ingestion으로 사용자 관리 태그·설명·Owner가 덮어써지지 않는지 검증.
- 공식 절차에 따라 검색 인덱스 재생성 검증.
- schema가 바뀐 DB에서 이미지 태그만 내리는 rollback 대신 백업 복원 절차 검증.

업그레이드 경로와 중간 버전 필요 여부는 공식 migration 지원 범위를 확인해
확정한다. Airflow는 기존 Teoria 운영 구조에 추가하지 않는다. Workflow schedule과
retry는 Prefect, ingestion은 격리된 공식 image 기반 Job으로 유지한다.

[공식 Docker 업그레이드 안내](https://docs.open-metadata.org/v2.0.x/deployment/upgrade/docker)는
Metadata DB 백업·migration, 재색인과 외부 ingestion client의 Server 버전 정합성을
안내한다.
