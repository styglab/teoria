# Provider references

외부 제공기관이 배포한 API 문서와 Registry 작성에 사용한 텍스트 문서를 Source별로 보존한다. `original`, `extracted` 같은 고정 하위 폴더는 만들지 않는다.

```text
references/providers/{provider}/{source}/
├── metadata.yaml   출처, 수집일과 연결된 Source Registry
└── 문서 파일       PDF, DOCX, Markdown 등
```

모든 문서는 형식과 관계없이 같은 Source 폴더에 둔다. `metadata.yaml`에는 제공기관, Source ID, 제목, 수집일, 공식 URL, 문서 목록과 연결된 Source Registry를 기록한다.

```yaml
provider: 국세청
source: nts_business_registration
title: 사업자등록정보 진위확인 및 상태조회 서비스 문서
retrieved_at: "2026-07-30"
official_url: null
files:
  - path: API문서.md
    media_type: text/markdown
registry: registries/sources/nts_business_registration.yaml
```

`path`와 `registry`는 안전한 상대 경로여야 한다. Source의 `specification.source_document`는 `files` 중 하나와 일치해야 한다. 전체 검증은 metadata 스키마, 문서 존재 여부, Source 및 Registry 경로 연결을 함께 확인한다.

제공기관에서 받은 원본 파일은 직접 수정하지 않는다. 변환한 문서가 필요하면 별도 파일로 추가하고 둘 다 metadata에 등록한다. 인증정보, 실제 개인정보와 비공개 응답은 이 디렉터리에 저장하지 않는다.

- `references/`: Registry 작성의 근거 자료
- `registries/`: Teoria가 검증하고 실행하는 정의
- `docs/`: Teoria 자체 설계와 사용법
- `archive/`: 특정 시점의 검증 결과와 과거 설계
