# Connector provider references

Data Pipelines Connector의 근거 문서를 보존한다.

```text
pipelines/references/providers/{provider}/{connector}/
├── metadata.yaml
└── 문서 파일
```

Metadata는 `target: connector`와 Connector ID를 사용하고 `registry`는 `pipelines/` 기준 상대 경로로 기록한다. API 키, 개인정보와 전체 Live 응답은 저장하지 않는다.
