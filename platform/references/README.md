# Provider references

Semantic Runtime이 직접 호출하는 Source의 근거 문서를 보존한다. Connector 문서는 `pipelines/references/`에 둔다.

```text
platform/references/providers/{provider}/{contract}/
├── metadata.yaml
└── 문서 파일
```

`metadata.yaml`은 `target: source`, Source ID, 수집일, 파일과 `platform/` 기준 Registry 경로를 기록한다. Source 작성 전에는 `status: draft`, 연결 후에는 `active`를 사용한다.

허용 형식은 `pdf`, `docx`, `xlsx`, `csv`, `json`, `xml`, `yaml`, `html`, `markdown`, `text`다. 원본은 수정하지 않고 변환본이 필요하면 별도 파일로 함께 등록한다.

API 키, 개인정보와 비공개 응답은 저장하지 않는다. Source의 `specification.source_document`는 등록된 파일명과 일치해야 한다.
