# 관리 화면 사용과 개발

기본 주소는 `http://localhost:8081/`다. 홈에서 작업을 고르거나 메뉴로 이동한다.
조회·승인·실행은 각각의 권한과 기능 활성화 상태를 따른다.

## 작업에 맞는 화면 찾기

| 메뉴 | URL | 주요 작업 |
|---|---|---|
| 홈 | `/admin/overview` | 검토 대기·실패한 실행·최근 작업 |
| 데이터 자산 | `/admin/data-catalog` | 자산 검색·설명·스키마·품질·계보·진단 |
| 온톨로지 | `/admin/semantic-model/ontology` | 개념·관계·Draft·검토·게시 |
| 의미 연결 | `/admin/semantic-model/bindings` | 자산·용어·개념 연결 |
| 검토함 | `/admin/changes/review` | 제안·Binding·Ontology의 소유 검토 화면으로 이동 |
| 파이프라인 | `/admin/workflows` | 허용된 실행·스케줄·취소 요청·이력 |
| 규격서 분석 | `/admin/specifications` | 문서 입력·실행·저장 결과·원문 근거 |
| 모델 레지스트리 | `/admin/models` | 선택형 모델·버전·평가·학습 이력 |
| 추론 서비스 | `/admin/serving` | 선택형 배포 버전·추론 테스트·이력 |
| 연결 및 설정 | `/admin/operations` | 연결·관리자 인증·실행 도구 |
| 개발 도구 | `/admin/developer/capabilities` | 실행 계약·Runtime 개발 |

모델 운영은 선택 기능이다. 파이프라인 화면은 모델 운영 활성화와 독립적이다.
홈·검토함은 조회 범위를 표시하며 전체 누적 통계나 개인 할당 작업으로 해석하지 않는다.

## 데이터 자산과 변경안

1. 자산을 검색해 현재 설명·스키마·품질·계보를 확인한다.
2. 설명 변경안 또는 필요한 항목의 AI 진단을 요청한다.
3. 검토함에서 현재 값·제안·근거와 원천 version을 대조한다.
4. 승인 후 적용 서비스가 원천 version을 다시 검사하고 결과를 기록한다.

제출만으로 OpenMetadata를 바꾸지 않는다. 원천 조회 실패를 빈 값으로 표시하지 않는다.
[자산 맥락](metadata/asset_context.md) · [진단](metadata/asset_assessment.md) ·
[제안·적용·복구](metadata/suggestions.md)를 참고한다.

## 규격서 분석

```text
문서 입력 → 처리 방식/고정 표준 선택 → 실행 → 문서별 결과 → 대상·속성·원문 근거
```

표준관리와 문서처리는 기존 Prefect 배포를 사용한다. 실행 운영·로그는 파이프라인 화면에서 확인한다.
저장된 추출 결과는 명시적 구성 트리·대상별 속성·근거로 탐색한다.
구매 범위·해석·보류·순환·복수 부모 관계를 화면에서 물리적 구성으로 확정하지 않는다.
관계가 확인되지 않은 대상과 대상 미확정 속성은 별도로 표시한다.

| 제한 | 현재 범위 |
|---|---|
| 업로드 | Compose에서 설정한 저장소, 요청당 파일 하나·40MB 이하·지원 형식 |
| 권한 | 업로드는 metadata_admin, 실행은 허용된 workflow 권한 |
| 결과 조회 | Data DB에 등록된 참조·허용 저장소 경계·checksum 검사 |
| JSON 미리보기 | 5MB 이하 로컬 artifact |
| 후속 | S3 본문 미리보기·K3s 업로드 저장소 연결 |

추출 결과를 Published Ontology나 승인된 제품 성능으로 표시하지 않는다.
단계와 결과 파일은 [규격서 파이프라인](../procurement_specification_processing/pipeline.md)을 따른다.

## 관리자 연결

Admin token으로 `/v1/admin/auth/session`을 확인한다. 공개 상태 응답을 인증 성공으로 사용하지 않는다.
token은 sessionStorage에 보관하고 로그아웃 때 제거한다. OpenMetadata bot token과는 다른 값이다.
운영은 bearer 인증과 principal별 역할을 사용한다. [설정·권한](../deployment/configuration.md)을 참고한다.

## 프론트엔드 개발

| 위치 | 책임 |
|---|---|
| `frontend/src/app/` | 앱·라우팅·메뉴 |
| `frontend/src/features/` | 기능별 화면 |
| `frontend/src/api/` | API client·HTTP 계약 |
| `backend/src/teoria/features/` | 소유 기능의 HTTP 라우터 |
| `backend/src/teoria/entrypoints/` | 앱·lifespan·조립 |

```bash
npm --prefix frontend ci
npm --prefix frontend run test -- --run
npm --prefix frontend run build
```

탐색 상태는 URL로 복원하고 큰 관계도는 필요할 때 적재한다.
Compose의 gateway는 UI와 내부 API proxy를, K3s는 UI와 서비스별 ingress 구성을 사용한다.
[배포 안내](../deployment/compose.md)와 [개발 경계](development.md)를 따른다.
