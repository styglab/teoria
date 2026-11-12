# 보관 영역

이 폴더 전체가 실행과 무관하다는 의미는 아니다. 아래 의존 관계를 확인한 후 정리한다.

| 경로 | 현재 용도 | 활성 플랫폼과의 연결 |
|---|---|---|
| `kory_parser/` | 독립 Python 프로젝트·문서 파서 | 규격서 Job 이미지를 빌드할 때 포함한다. 별도 환경에서 CLI로 실행하며 Teoria 라이브러리로 import하지 않는다. |
| `kory_parser_evaluation/` | 파서 평가·회귀·개선 도구 | 파서 유지보수용이며 플랫폼 서비스로 배포하지 않는다. |
| `customer_churn/` | 독립 학습·서빙 이미지 예제 | 플랫폼 API·메뉴·Prefect 기본 배포에 연결하지 않는다. |
| `deploy/` | 이전 Compose 배포 자료 | 현재 배포 진입점에서 사용하지 않는다. 활성 배포는 `deploy/kubernetes/`다. |
| `publish_kory_parser.sh` | 파서 변경 확인·별도 저장소 게시 | 명시적인 파서 게시 작업에서만 사용한다. |

공고·계약·낙찰 등 과거 조달 서비스는 현재 checkout의 실행 코드와 배포에 없다.
`archive/procurement_services/`도 현재 checkout에는 없다. 과거 이력이 필요하면 Git 이력 또는 별도 보관본을 확인한다.
DB migration과 기존 게시 artifact의 이력은 이 폴더 유무와 관계없이 유지한다.

파서 게시 명령은 저장소 루트에서 실행한다.

```bash
# 변경 확인
bash archive/publish_kory_parser.sh
# 명시적인 게시
bash archive/publish_kory_parser.sh --push --branch fix-parser --message "Fix parser"
```
