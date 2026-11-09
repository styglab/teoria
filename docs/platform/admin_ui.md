# 관리 화면 경로와 프런트엔드 개발

화면 사용 순서는 [사용 안내](../platform-guide.md)를 따른다. 이 문서는 경로·API 경계·현재 제한과 개발 위치를 정리한다.
조회·승인·실행은 각각의 권한과 기능 활성화 상태를 따른다.

프런트엔드 소유 위치는 백엔드와 같은 책임 이름을 사용한다. Metadata 조회·진단·제안은
platform/data/metadata, Ontology·Binding은 platform/ontology/authoring·platform/ontology/bindings,
Capability는 platform/ontology/runtime, 인증은 platform/access_control에 둔다.
FormatID 화면은 apps/formatid이며 플랫폼 정의와 분리한다.
고객 이탈 테스트 폼은 `examples/customer_churn/`에 두고 shell이 공통 서빙 화면에 주입한다.
라우팅·메뉴는 shell에서 조립하고 기존 URL을 유지한다. 미사용 governance 전체 자산 스캔 화면은 제거했다.

## 작업 공간과 공통 운영

`semantic` 배포 모듈은 **데이터**와 **Ontology** 작업 공간을 제공한다.
별도 선택 모듈 `mlops`는 **MLOps** 작업 공간으로 표시한다. AI/AIP는 미구현이며 메뉴를 노출하지 않는다.
**공통 운영**에는 파이프라인과 연결·설정을, **업무 앱**에는 FormatID를 둔다.
기존 사전·의미 연결 URL은 검색 조건과 선택 대상을 보존해 새 소유 화면으로 연결한다. 홈의 작업 공간별 시작 링크와 현재 위치도 같은 메뉴 정의를 사용한다.
모듈 비활성화·모델 운영 권한 확인과 기존 관리자 인증은 그대로 적용한다.
도메인 관리의 물품 사전은 `semantic` 또는 `formatid` 활성화 시 표시한다. 프로파일 전용 편집과 범용 학습·모델 승인은 로드맵을 따른다.

## 작업에 맞는 화면 찾기

| 메뉴 | URL | 주요 작업 |
|---|---|---|
| 홈 | `/admin/overview` | 검토 대기·실패한 실행·최근 작업 |
| 데이터 자산 | `/admin/data-catalog` | 자산 검색·설명·스키마·품질·계보·진단 |
| 온톨로지 | `/admin/semantic-model/ontology` | 개념·관계·Draft·검토·게시 |
| 온톨로지 → 데이터·용어 연결 | `/admin/semantic-model/ontology?view=connections` | 개념·모델 범위의 자산·용어 연결 |
| 검토함 | `/admin/changes/review` | 제안·Binding·Ontology의 소유 검토 화면으로 이동 |
| 파이프라인 | `/admin/workflows` | 허용된 실행·스케줄·취소 요청·이력 |
| 업무 앱 → FormatID | `/admin/specifications` | 문서 입력·실행·저장 결과·원문 근거 |
| 모델 레지스트리 | `/admin/models` | 선택형 모델·버전·평가·학습 이력 |
| 추론 서비스 | `/admin/serving` | 선택형 배포 버전·추론 테스트·이력 |
| 연결 및 설정 | `/admin/operations` | 연결·관리자 인증·실행 도구 |
| 도메인 관리 → 물품 사전 | `/admin/domains/goods/dictionary` | 품목별 유형·속성·표현·연결·검토 대기, 게시 Ontology 조회·표현 연결 판정·과거 정의의 Draft 이관 |
| FormatID → 처리 기준 | `/admin/specifications/standards` | 규격서 처리용 표준·사전 묶음 승인 |
| 실행 계약·Capability | `/admin/developer/capabilities` | Source·Mapping·Capability의 연결·정적 검증 조회 |

모델 운영은 선택 기능이다. 파이프라인 화면은 모델 운영 활성화와 독립적이다.
홈·검토함은 조회 범위를 표시하며 전체 누적 통계나 개인 할당 작업으로 해석하지 않는다.

## 데이터 자산과 변경안

조회 결과는 OpenMetadata의 상태를 기준으로 표시한다. 공개 조회 허용과 변경·데이터 샘플 권한을 구분하고,
조회 실패를 빈 값으로 처리하지 않는다. [메타데이터 조회·진단·검토](metadata.md)를 참고한다.

자산 목록은 `GET /v1/admin/metadata/table-search`에 검색어·스키마·누락 유형·정렬·offset·limit를
전달한다. `GET /v1/admin/metadata/table-search/counts`는 동일 검색 범위의 전체·설명 없음·소유자 없음·태그 없음
건수를 조회한다. 목록 실패와 집계 실패는 구분하고, 집계 실패가 자산 탐색을 막지 않는다.
검색 색인의 반영 지연이 있을 수 있으며 결과가 10,000개를 넘으면 검색·스키마로 범위를 좁힌다.
전체 테이블을 브라우저에 수집하거나 Teoria DB에 복제하지 않는다.

## FormatID

앱은 규격서별 최종 처리 결과의 엔티티·관계·속성과 표준화 전후 값을 보여준다. 행 선택·키보드 Enter로 속성과 원문 근거를 함께 강조한다.
구매 범위·해석·보류·순환·복수 부모 관계를 물리적 구성으로 확정하지 않는다.
실행·스케줄·로그는 기존 Prefect 배포를 사용하는 파이프라인 화면에서 관리한다.

| 제한 | 현재 범위 |
|---|---|
| 업로드 | Compose에서 설정한 저장소, 요청당 파일 하나·40MB 이하·지원 형식 |
| 권한 | 업로드는 metadata_admin, 실행은 허용된 workflow 권한 |
| 결과 조회 | Data DB에 등록된 참조·허용 저장소 경계·checksum 검사 |
| JSON 미리보기 | 등록된 MinIO/S3 또는 허용된 개발용 로컬 참조, 5MB 이하 |
| 규격서 결과 | `tab=evidence`; 엔티티 목록·구성/포장 계층, 속성·관계·미해결 항목과 원문 근거 |
| 문서 선택 복원 | 목록은 `document=<catalog_id>`, 기존 `run` 링크 안에서는 `document=<document_id>` |
| 분류별 목록 | 서버 검색·필터·페이지 조회. 본문은 열 때만 조회. 동일 원문·분류·공고의 재처리는 묶고 이전 정상 결과 보존 |
| 문서 비교 | 같은 분류 2–4개, 확인된 동일 표준 스냅샷·대상·속성·역할·범위·단위만 정렬. 여러 대상 값과 조건 보존 |
| 이전 검토 링크 | `tab=review`는 결과 화면으로 연결하고 `review_revision`은 제거; 승인 작업을 실행하지 않음 |
| 후속 | K3s 업로드 저장소 연결·실환경 검증 |

최종 결과는 해당 실행의 산출물을 뜻한다. FormatID는 검토·승인 기능을 제공하지 않으며 미해결·실패 상태를 함께 표시한다.
상세는 구성 트리와 속성의 기본 2열이며 요청한 원문 근거만 추가 패널로 연다. 트리의 위·아래/Home/End는 초점 이동, 좌·우는 접기·펼치기, Enter는 대상 선택이다.
추출용 표준 초안을 Published Ontology로 표시하지 않는다. 미매핑은 추출 실패와 구별한다.

단계와 결과 파일은 [규격서 파이프라인](../domains/goods/specifications/pipeline.md)을 따른다.

## 관리자 연결

Admin token으로 `/v1/admin/auth/session`을 확인한다. 공개 상태 응답을 인증 성공으로 사용하지 않는다.
자산 화면도 공통 관리자 연결을 사용한다. token은 sessionStorage에 보관하고 로그아웃 또는 해당 token의
401 응답 때 제거한다. 늦게 도착한 이전 token의 실패가 새 연결을 해제하지 않도록 구분한다.
403은 권한 부족으로 처리하며 다른 조회 권한을 임의로 해제하지 않는다. OpenMetadata bot token과는 다른 값이다.
운영은 bearer 인증과 principal별 역할을 사용한다. [설정·권한](../deployment/configuration.md)을 참고한다.

## 프론트엔드 개발

| 위치 | 책임 |
|---|---|
| `frontend/src/shell/` | 플랫폼 화면 틀·라우팅·메뉴 |
| `frontend/src/{platform,domains,apps}/` | 기능별 화면 |
| `frontend/src/api/` | HTTP 전송·인증 오류·Query 공통 정책 |
| 각 소유 모듈의 `api.ts` | 업무 API client·응답 타입 |
| `frontend/src/components/ui/design_tokens.css` | 공통 색상·간격·글자 크기·컨트롤 크기 |
| `frontend/src/components/ui/button.tsx`, `button.css`, `input.tsx` | 실제 공유 버튼·입력 컴포넌트 |
| `frontend/src/components/ui/form_controls.css` | 관리자 화면의 입력 포커스·셀렉트 화살표·옵션 목록 |
| `backend/src/teoria/{platform,domains,apps}/` | 소유 기능의 HTTP 라우터 |
| `backend/src/teoria/entrypoints/` | 앱·lifespan·조립 |

```bash
npm --prefix frontend ci
npm --prefix frontend run test -- --run
npm --prefix frontend run build
npm --prefix frontend run test:e2e
```

입력 포커스와 단일 선택 셀렉트의 표현은 `components/ui/form_controls.css`를 기준으로 한다.
`main.tsx`에서 화면 CSS 다음에 한 번 적재하며, 화면별 규칙이 공통 포커스·셀렉트 표현을 덮지 않도록 한다.
기존 화면 CSS에는 레이아웃과 과거 입력 표현 규칙도 일부 남아 있으나 공통 모듈을 우선 적용한다.
입력은 기존 1px 테두리와 얇은 포커스 표시를 사용하고, 검색 그룹은 바깥 컨테이너에만 표시한다.
셀렉트는 기본 HTML 선택 동작을 유지한다. 지원 브라우저에서는 옵션 목록도 공통 모양으로 표시하고,
그 외에는 동일한 입력창 모양과 브라우저 기본 목록을 제공한다.
구현 기준은 [Chrome 공식 가이드](https://developer.chrome.com/blog/a-customizable-select)와
[MDN의 customizable select 안내](https://developer.mozilla.org/en-US/docs/Learn_web_development/Extensions/Forms/Customizable_select)를 따른다.
고대비 모드에서는 시스템 선택 모양과 명확한 포커스를 사용한다.

탐색 상태는 URL로 복원하고 큰 관계도는 필요할 때 적재한다.
Compose의 gateway는 UI와 내부 API proxy를, K3s는 UI와 서비스별 ingress 구성을 사용한다.
[배포 안내](../deployment/compose.md)와 [개발 경계](../development.md)를 따른다.


## 화면 회귀 검사와 조회 정책

`frontend/tests/browser/`는 고정 샘플만 사용하는 브라우저 검사다. 실제 API 인증정보와 원문을
baseline 이미지에 저장하지 않는다. 목록·입력 포커스·펼친 셀렉트·모바일 카드·상세·근거·비교의
9개 기준 이미지와 키보드 선택·오류 복구·스크롤/선택 복원·1,000개 대상 탐색을 검사한다.
CI의 `admin-ui-visual`과 같은 고정 Playwright 컨테이너에서 생성·비교한다.
기준 갱신은 `npm run test:e2e:update`, 일반 검증은 `npm run test:e2e`다.
실패한 비교의 이미지·trace는 CI artifact로 제공한다.

문서 탐색 요청은 조건 변경·화면 이탈 시 취소한다. 목록 갱신 중에는 기존 행을 유지하고
현재 조건의 응답을 기다린다는 상태를 표시한다. 분류·문서 오류와 재시도는 분리한다.
문서 조회 캐시는 메모리에서 최대 8개·30초이며 로그인 토큰이 달라지면 폐기한다.
관찰 본문을 localStorage/sessionStorage에 저장하지 않는다. 목록 스크롤과 비교 선택은
같은 탭의 메모리에서 최대 12개 조회 상태로 복원한다.

모바일은 규격서 카드와 접을 수 있는 필터를 사용한다. 표준 상세는 속성·요구값/단위/조건·근거의
3열로 제공하고 작은 화면에서는 세로로 배치한다. 원문 값과 내부 식별자는 펼쳐 확인한다.
문서 비교는 표준·단위·범위·역할·대상 연결이 다른 경우 빈 셀의 이유를 표시한다.
주요 업무 화면은 방문 시 적재하고 화면 오류에는 전체 앱 탐색을 유지하는 복구 화면을 제공한다.

Ontology 개념 상세의 데이터·용어 연결은 Stable Concept ID로 조회한다. 게시된 개념이 없는 범위에서는 새 연결 제안을 비활성화하고 게시 필요 사유를 표시한다. 기존 연결의 조회·검토는 유지한다.
