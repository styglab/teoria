# Registry lifecycle

현재 Git 기반 단계에서는 작성된 YAML이 원본이다. 운영 Runtime은 검증·승인 후 발행된 불변 Bundle만 실행한다.

```text
draft → validate → review → approve → publish → deprecate
```

Bundle manifest는 ID, 생성 시각, Git commit, schema·Runtime·transform 버전과 checksum을 기록한다. 한 실행은 시작부터 끝까지 같은 Bundle을 사용하고 provenance에 Bundle ID를 남긴다.

발행된 ID는 삭제 대신 deprecate하고 비호환 변경은 새 content version으로 추가한다. Registry schema version, 정의 version과 Bundle version은 별개다. Console 수정은 draft를 만들 뿐 발행본을 직접 덮어쓰지 않는다.
