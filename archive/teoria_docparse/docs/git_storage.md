# Git 보관 범위

이 패키지는 활성 서비스에 연결하지 않는 보관용 독립 파서다.

Git에는 `src/`, `tests/`, 작은 설명 문서인 `docs/`, `pyproject.toml`, `uv.lock`,
라이선스와 제삼자 고지를 보관한다. 기본 `tests/`는 Git에 포함된 파일만으로 실행한다.
평가 도구 자체의 테스트 5개 파일은 `verification/tests/`에서 별도로 관리한다.
실제 공고·원문 샘플과 실행 결과는 `.artifacts/`에 유지하며 Git에 넣지 않는다.
`.venv/`, 캐시, `dist/`, `verification/` 전체도 제외한다. 검증 JSON·HTML 결과,
정답·manifest와 과거 실행 도구는 로컬에 남긴다. 문서의 과거 검증 링크 중 제외된
파일은 별도 보관본에서 확인한다. source distribution에도 환경·실험 자료를 포함하지 않는다.
제외 목록은 패키지 `.gitignore`에 있다.

이름 변경 전 `.artifacts/`와 검증 JSON의 과거 경로·패키지명·hash는 당시 기록으로
유지한다. 이름 변경 뒤의 실행 로그와 구분하며, 과거 전체 비교를 재실행하려면
당시 경로와 고정 환경을 복원해야 한다.

의존성 환경은 다음과 같이 다시 만든다.

```bash
uv sync --locked --project archive/teoria_docparse --group dev
uv run --locked --project archive/teoria_docparse python -m pytest archive/teoria_docparse/tests
```

단위 테스트의 합성 문서는 코드에서 생성한다. 실제 원문을 이용하는 비교·성능 검증은
별도로 보관한 `.artifacts/` 코퍼스, 고정 snapshot과 원본 kordoc 설치가 필요하다.
Git checkout만으로 과거의 전체 실문서 비교를 재현할 수 있다는 의미는 아니다.

로컬에 평가 도구가 있을 때만 별도 테스트를 실행한다.

```bash
uv run --locked --project archive/teoria_docparse python -m pytest archive/teoria_docparse/verification/tests
```

추가 전에는 `git add --dry-run archive/teoria_docparse`으로 목록을 확인한다.
제외 파일을 포함하는 `git add -f`는 사용하지 않는다.
