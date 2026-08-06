# Registry lifecycle

현재 Git 기반 단계에서는 작성된 YAML이 원본이다. 운영 Runtime은 검증·승인 후 발행된 불변 Bundle만 실행한다.

```text
draft → validate → review → approve → publish → deprecate
```

Registry release version은 `YYYY.MM.DD.REVISION` 형식을 사용한다. 같은 날 첫 릴리스는
`2026.08.05.1`, 다음 릴리스는 `2026.08.05.2`처럼 증가시킨다. 다음 명령은 전체 검증 후
Registry 루트의 `.release.json`을 갱신하고, 선택적으로 버전별 불변 산출물을 만든다.

```bash
uv run --locked --package teoria-platform \
  teoria publish platform/registries \
  --version 2026.08.05.1 \
  --output dist/registry
```

Manifest는 version, 생성 시각, Git commit과 의미 기준으로 정규화한 Registry checksum을 기록한다.
발행 이후 YAML이 달라지면 Admin API의 상태는 `modified`가 되며,
`TEORIA_REGISTRY_REQUIRE_PUBLISHED=true`인 Runtime은 시작을 거부한다. Capability 실행 응답에도
Registry release 정보를 포함하여 어떤 의미 계약으로 결과를 만들었는지 추적한다.

발행된 ID는 삭제 대신 deprecate하고 비호환 변경은 새 content version으로 추가한다. Registry schema version, 정의 version과 Bundle version은 별개다. Admin UI 수정 기능을 추가하더라도 draft를 만들 뿐 발행본을 직접 덮어쓰지 않는다.
