# 백엔드 리소스 정리 — 2026-10-26

백엔드 폴더의 실행·작성·검증·복구 용도를 확인하고 사용하지 않는 예제와 중복 placeholder를 정리했다.
현재 기준 위치와 유지 이유는 [저장소 구조](../../../docs/architecture/repository-structure.md#백엔드-리소스의-용도)에 기록했다.

## 변경

- 일반 주문 ETL Python·Prefect 예제와 전용 테스트를 `archive/examples/db_sales/`로 이동했다.
  운영 등록이나 실행 경로를 추가하지 않았다. 전용 테스트 15개도 활성 테스트 모음에서 제외했다.
- `etl-example` dependency group과 외부 라이브러리 10종을 제거하고 `backend/uv.lock`을 갱신했다.
  Great Expectations·pandas·NumPy·SciPy 등의 예제 전용 의존성이다. 기존 패키지 version을 올리지 않았다.
- 과거 pending 분류 두 개를 `archive/ontology_migrations/pending/`로 이동했다.
  역사적 Registry snapshot을 검증하는 테스트도 보관 manifest를 명시하도록 바꿨다.
  현재 `2026_10_goods_focus` manifest와 모든 `applied/` 이력은 유지했다.
- 중복 `.gitkeep` 7개와 그중 내용 없는 Registry 하위 디렉터리를 제거했다.
- `.dockerignore`에 백업·로컬 개발 상태·중첩 가상환경과 캐시 제외를 추가했다.
  기존 백업 덤프는 삭제하거나 이동하지 않았다. 확인 당시 전체 백업은 약 8.3 MiB다.
- 오래된 주문 ETL 실행 안내를 현재 기능별 파이프라인 작성 안내와 보관 경로로 갱신했다.
- `entrypoints/composition/`은 API 서비스 조립 책임이 명확하므로 유지했다.
  기능 라우터·request dependency와는 다른 책임이다. FastAPI가 강제하는 이름은 아니다.

보관한 Python·YAML 원본 4개는 이동 전 Git 본문과 byte 단위로 동일하다.
보관 테스트는 파일 위치와 선택 의존성 안내만 수정했다. 적용된 Application/Data SQL과
Ontology `applied/` 이력에는 변경이 없다.

## 검증

| 대상 | 결과 |
|---|---|
| 백엔드·기능 간 계약 테스트 | 507 passed, 45 skipped |
| 생략 범위 | 격리 DB·S3·선택 Prefect 평가 설정이 필요한 opt-in 통합 테스트; 이번 실행에는 해당 자원을 구성하지 않음 |
| Registry | Source·Mapping·Capability 0개, data type 11개·value set 15개 검증 성공 |
| Connector·수집 정의·통합 계약 | 법령 Connector 1개·pipeline 1개 검증 성공 |
| 현재 물품 migration report | `2026_10_goods_focus` manifest의 분류 검증 valid; 게시 대상 DB 대조는 not_checked |
| 의존성 | lock 일치, 제거한 예제 라이브러리 없이 전체 extra/group 동기화 성공 |
| 정적 검사 | F821·F822·F823·F811 및 `git diff --check` 성공 |
| 문서 | 검사기 단위 테스트 7개 통과·로컬 링크 검사 성공 |
| Compose | 테스트 6개·`config --quiet` 성공 |
| Docker | `authoring`·`check` target build 성공, `check` 이미지의 실제 통합 계약 검증 성공 |
| 복구 자료 | SHA256SUMS의 파일 4개 체크섬 일치, backup script 문법 검사 성공 |

기존 Starlette TestClient의 HTTPX 관련 deprecation warning 1건이 남아 있다.
이번 정리는 소스·입력·개발 의존성 정리이며 운영 컨테이너를 교체하지 않았다.
운영의 직전 코드 배포 결과는 [백엔드 구조 정리 기록](backend_cleanup_2026_10_26.md)에 별도로 보존한다.

참고 기준: FastAPI 공식 [여러 파일과 APIRouter](https://fastapi.tiangolo.com/tutorial/bigger-applications/),
Cosmic Python 저자의 [Dependency Injection과 composition root](https://www.cosmicpython.com/book/chapter_13_dependency_injection).
