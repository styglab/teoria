# Kory Parser 평가·개선 도구

파서 실행 코드와 분리한 회귀 테스트·원문 평가·벤치마크·Codex 개선 루프 작업 공간이다.
파서는 `../kory_parser/`, Codex 스킬은 저장소 루트 `.agents/skills/improve_kory_parser/`에 있다.
파서 배포물에는 이 디렉터리를 포함하지 않는다. 의존성과 잠금은 파서 프로젝트의 개발
환경을 사용하며 별도 설치 패키지나 중복 lock을 만들지 않는다.

저장소 루트에서:

```bash
uv run --project archive/kory_parser --locked --group dev python -m pytest -c archive/kory_parser_evaluation/pytest.ini archive/kory_parser_evaluation/tests
```

평가·개선 명령은 이 작업 공간에서 실행한다.

```bash
cd archive/kory_parser_evaluation
uv run --project ../kory_parser --locked --group dev python -m evaluations --output .artifacts/evaluation_001
uv run --project ../kory_parser --locked --group dev python -m evaluations.improve --dry-run --output .artifacts/loop_preview
uv run --project ../kory_parser --locked --group dev python -m evaluations.compare --help
```

- [평가·개선 순환과 입력 계약](docs/evaluation_loop.md)
- [실문서 비교·회귀·채택 기준](docs/public_procurement_cycle.md)

라이브러리 동작 테스트는 `tests/test_*.py`, 평가 도구 자체 테스트는 `tests/evaluation/`에 있다.
기존 검증 조건과 고정 코퍼스는 보존한다. 실제 원문·결과·후보·사용 이력은 이 디렉터리의
`.artifacts/`에 두며 Git이나 파서 배포물에 포함하지 않는다.

기존 `archive/kory_parser/.artifacts/` 또는 `verification/` 자료가 별도로 존재하면 삭제하거나
초기화하지 않는다. 실행을 중지한 상태에서 원문·manifest·hash·사용 이력을 함께 확인해
옮겨야 하며, manifest 안의 절대 경로도 검증해야 한다. 이번 체크아웃에는 해당 자료가 없었다.

구조 기준은 [PyPA 패키징 가이드](https://packaging.python.org/en/latest/tutorials/packaging-projects/)와
[src layout 설명](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/),
공개 파서 [pdfplumber](https://github.com/jsvine/pdfplumber)와
[pypdf](https://github.com/py-pdf/pypdf)를 참고했다. `src` 분리와 명시적 배포 범위를 적용한다.
회귀 테스트까지 형제 작업 공간에 모은 것은 이 저장소의 사용자 요청에 따른 선택이며,
모든 Python 프로젝트에 필요한 일반 규칙은 아니다.

## 파서 공개 저장소 업데이트

Teoria 안의 `archive/kory_parser/`를 개발 원본으로 유지한다. 공개 저장소 업데이트에는
[업로드 스크립트](../publish_kory_parser.sh)를 사용한다. 저장소 루트에서:

```bash
# 변경 확인만 수행
bash archive/publish_kory_parser.sh

# 커밋과 main 업로드
bash archive/publish_kory_parser.sh --push --message "Fix document parsing"

# main에 PR을 요구하는 경우 새 브랜치로 업로드 후 GitHub에서 PR 생성
bash archive/publish_kory_parser.sh --push --branch fix-document-parsing --message "Fix document parsing"
```

Git과 tar가 필요하며 rsync는 필요하지 않다. 매번 원격 main을 임시 디렉터리에 clone한 뒤
파서의 `src/`·`docs/`·`third_party/`와 패키징·사용 안내·라이선스 파일만 반영한다.
평가 도구·Skill·실문서·가상환경은 올리지 않는다. 공개 저장소에만 있는 파일은 미러링 시
삭제 대상으로 표시되므로, 유지할 공개 파일은 파서 원본의 배포 범위에 함께 관리해야 한다.
변경이 없으면 커밋하지 않으며 force push를 사용하지 않는다. 보호 규칙이나 다른 사용자의
동시 업데이트로 push가 거절되면 오류로 종료한다. 임시 clone은 성공·실패 모두 삭제하고,
Teoria의 작업 파일·index·commit·remote는 변경하지 않는다. PyPI 게시도 수행하지 않는다.
