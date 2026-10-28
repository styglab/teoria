> **과거 자료·비활성**: 아래 설계·명령·건수는 작성 당시의 기록이다. 현재 사용 안내는 [문서 목차](../../../../docs/index.md)를 따른다.

# 실험 산출물 정리 — 2026-10-24


> 후속 정리: 이 문서의 과거 압축 보관본·manifest는 삭제했다. 중복 샘플·HTML·빈 폴더와 미사용 함수도 제거했으며, 현재 원본·핵심 JSON·Markdown 결과는 보존한다. 아래는 당시 기록이다.
현재 [규격서 추출 실험](../../../../docs/procurement_specification_processing/pipeline.md)에 필요한 코드·입력·결과를 남기고,
과거 조달·파서·이전 IE 실험을 압축 보관했다. 활성 서비스 코드는 변경하지 않았다.

## 남긴 구조

```text
.artifacts/
├─ index.md                산출물 탐색 시작점
├─ sample/                   원본 샘플 4개
├─ ie_engine/                현재 추출 코드·입력·결과·테스트
└─ archive/
   ├─ history_20261024.tar.gz
   ├─ history_20261024_manifest.json
   └─ cleanup_20261024.json
```

## 압축 보관한 자료

- `old_20261020/`, `procurement_specifications/`, `kordoc_python/`,
  `specification_intelligence_20261023/`, 구성품 정답 메모
- IE의 이전 `runs/`, `comparison/`, `structure_first/`와 과거 실행·복구·출력 스크립트
- `entity_pipeline`의 이전 후보 추출 방식·샘플 출력·실행 로그
- 이전 방식만 검사하는 9개 테스트와 그 구현 코드

29개 파일·디렉터리 묶음의 일반 파일 **8,840개**를 압축했다. 각 파일의 해시가
압축본과 일치하는지 전부 확인한 뒤 원래의 펼쳐진 자료를 제거했다. 원본 샘플과
현재 추출·평가 결과는 보관본으로 옮기지 않았다. 다시 만들 수 있는 Python 캐시는
압축 대상에서 제외하고 제거했다.

파일 수치는 `archive/history_20261024_manifest.json`에, 정리 요약은
`archive/cleanup_20261024.json`에 있다. 압축 보관된 파일은 약 313.5 MB,
압축본은 약 105.7 MB다. 전체 `.artifacts` 디스크 사용량은 약 357 MiB에서
129 MiB로 줄었다. 캐시 생성 등에 따라 이후 크기는 달라질 수 있다.

## 현재 실행의 의존성 처리

현재 실행기가 과거 조달 실험의 manifest를 참조하던 것을
`ie_engine/inputs/sample_manifest.json`으로 옮겼다. 현재 트리 테스트에 필요한
기존 그래프 한 개도 `entity_pipeline/tests/fixtures/`로 분리했다.
현재 구성 추출 실행기에서 이전 `structure_first` 경로 의존성을 제거했다.
Parser 어댑터·모델 호출·기준 수량 단위 처리에 실제 사용하는 helper는 남겼다.

원본 샘플은 `spec_sample/`에서 발견했다. 네 파일 모두 기존 manifest의 SHA-256과
일치함을 확인한 뒤 `sample/`로 옮겼다. 이전 문서에서 원본이 없다고 안내했던 상태를
현재 기준 문서에서 정정했다. 과거 실행의 provenance·절대 경로는 소급 수정하지 않는다.

## 확인 결과

현재 파이프라인 테스트 **36개 통과**. 이전 테스트 45개 중 과거 방식 전용 9개는
코드와 함께 보관했다. 현재 테스트가 실패해서 제외한 것은 아니다.
현재 샘플 네 개의 원본·파싱 해시와 원시 응답 재처리 결과의 동일성도 확인했다.
새 LLM 호출·재파싱·현재 결과 덮어쓰기는 실행하지 않았다.

## 과거 자료 찾기와 복원

압축 내부 경로는 정리 전 `.artifacts` 기준 상대 경로다. 과거 문서의 경로는
manifest의 `files[].path`에서 찾는다. 과거 기록의 명령은 현재 실행 명령으로 사용하지 않는다.

```bash
# 압축 보관한 파일 목록
 tar -tzf .artifacts/archive/history_20261024.tar.gz

# 별도 디렉터리에 필요한 실험 하나만 복원
mkdir -p /tmp/teoria_artifact_restore
tar -xzf .artifacts/archive/history_20261024.tar.gz \
  -C /tmp/teoria_artifact_restore \
  ie_engine/comparison
```

복원한 과거 실행의 절대 경로·환경 의존성은 별도로 확인해야 한다.
현재 실험 폴더 위에 일괄 복원하지 않는다.
