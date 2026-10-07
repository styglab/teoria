# Ontology migrations

이 디렉터리는 Published Ontology의 현재 권위 저장소가 아니다. 현재 Runtime 계약은
Application DB에서 게시되어 checksum으로 고정된 immutable Ontology Artifact다.

- `applied/`: 이미 검토·승인·게시된 이관 입력과 결정 기록이다. 기존 파일을 수정하지 않는다.
- `pending/`: 다음 Draft에 적용할 새 migration 묶음이 생길 때 생성한다.

각 migration 묶음은 `YYYY_MM_<purpose>` 이름을 사용한다. 적용 후에는 해당 묶음에
대상 Ontology version과 Artifact checksum을 기록하고 `applied/`로 이동한다.

`applied/2026_10_initial_unification/`은 `teoria@0.1.0`부터 `teoria@0.1.2`까지의
초기 통합 구성, 구형 Ontology 분류, Binding 계획을 보존한다. 일부 파일은 최종
구성 자체가 아니라 이관 과정의 중간 입력이며 재실행 대상이 아니다.
