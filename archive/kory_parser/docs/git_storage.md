# Git 보관 범위

이 패키지는 활성 서비스에 연결하지 않는 보관용 독립 파서다.

Git에는 `src/`, `tests/`, 작은 설명 문서인 `docs/`, `pyproject.toml`, `uv.lock`,
라이선스와 제삼자 고지를 보관한다. 새 평가 코드와 합성 코퍼스·정답은 `evaluations/`,
평가·반복 실행기의 회귀 테스트는 `tests/evaluation/`에 보관한다.
기본 `tests/`는 Git에 포함된 파일만으로 실행한다.
과거 평가 도구 자체의 테스트 5개 파일은 `verification/tests/`에서 별도로 관리한다.
실제 공고·원문 샘플과 실행 결과는 `.artifacts/`에 유지하며 Git에 넣지 않는다.
`.venv/`, 캐시, `dist/`, `verification/` 전체도 제외한다. 검증 JSON·HTML 결과,
과거 정답·manifest와 과거 실행 도구는 로컬에 남긴다. 문서의 과거 검증 링크 중 제외된
파일은 별도 보관본에서 확인한다. source distribution에도 환경·실험 자료를 포함하지 않는다.
제외 목록은 패키지 `.gitignore`에 있다.

이름 변경 전 `.artifacts/`와 검증 JSON의 과거 경로·패키지명·hash는 당시 기록으로
유지한다. 이름 변경 뒤의 실행 로그와 구분하며, 과거 전체 비교를 재실행하려면
당시 경로와 고정 환경을 복원해야 한다.

의존성 환경은 다음과 같이 다시 만든다.

```bash
uv sync --locked --project archive/kory_parser --group dev
uv run --locked --project archive/kory_parser python -m pytest archive/kory_parser/tests
```

단위 테스트의 합성 문서는 코드에서 생성한다. 실제 원문을 이용하는 비교·성능 검증은
별도로 보관한 `.artifacts/` 코퍼스, 고정 snapshot과 원본 kordoc 설치가 필요하다.
Git checkout만으로 과거의 전체 실문서 비교를 재현할 수 있다는 의미는 아니다.
새 평가와 Codex 반복 실행은 [평가·개선 순환](evaluation_loop.md)을 따른다.

로컬에 평가 도구가 있을 때만 별도 테스트를 실행한다.

```bash
uv run --locked --project archive/kory_parser python -m pytest archive/kory_parser/verification/tests
```

추가 전에는 `git add --dry-run archive/kory_parser`으로 목록을 확인한다.
제외 파일을 포함하는 `git add -f`는 사용하지 않는다.

## 사이클 종료 후 정리

보고서 생성이 끝나면 불필요한 성공 표본과 재생성 가능한 중간 출력을 정리한다.
고정 회귀 원문, 원문 정답·문제 사례, 사용 이력, manifest·hash·수치 보고서, baseline과
candidate 소스는 보존한다. 아직 평가하지 않은 새 표본과 적용 전 검토 중인 후보는 지우지 않는다.

`evaluations.public_procurement.report`는 최종 보고서를 쓴 뒤 이 정리를 기본 수행한다.
디버깅에 전체 중간 출력이 필요하면 `--keep-intermediates`를 지정한다. 삭제한 원문도
이력의 SHA-256·공고번호는 유지하므로 새 표본으로 다시 선택되지 않는다.
삭제 내역과 할당 용량은 `cleanup.json`에 기록한다.

```bash
uv run --locked python -m evaluations.public_procurement.cleanup \
  --cycle-root .artifacts/cycle_002
uv run --locked python -m evaluations.public_procurement.cleanup \
  --cycle-root .artifacts/cycle_002 --apply
```

오래된 비교용 `.venv`, `install_base`, `install_native`, `install_wheel`, OCR reference의
`node_modules`와 초기 비교 실험의 모델 캐시는 `--legacy-environments`로 별도 정리할 수 있다.
실행 중인 환경과 원문을 포함한 디렉터리는 건너뛴다. 현재 패키지의 `.venv`와 공통 kordoc
비교 설치는 유지한다. 과거 설치 검증의 환경은 lock·requirements·버전 기록으로 재구성해야 한다.
다른 업무의 누적 평가 로그는 이 파서 정리 작업에서 삭제하지 않는다.

사용자가 추가로 승인한 2026-10-23 보관 정리에서는 과거 전체 파싱 출력과 보호 원문에
대응하는 바이트 동일 사본을 제거했다. 고정 회귀 원문·새 표본·현재 성능 비교 본문은
유지했다. 오래된 개별 출력의 경로가 남은 기록은 소스와 원문에서 재생성해야 한다.
삭제 파일의 hash·사유·대응 원문과 압축 자료의 원문 hash는 로컬
`.artifacts/maintenance_cleanup/result.json`에 기록했다. 이 기록은 원문을 대체하지 않는다.

추가 보관 정리에서는 구버전 배포 파일, 현재 사용하지 않는 과거 OCR 모델과 캐시를
제거했다. 배포 파일은 Kory Parser 0.9.1과 0.9.2를 유지한다. 큰 과거 평가 JSON 4개는
원문 SHA-256을 검증한 뒤 `.json.gz`로 압축했으며, 필요하면 `gzip -dk <파일.json.gz>`로
복원한다. 내역은 `.artifacts/archive_cleanup_result.json`에 기록했다.
