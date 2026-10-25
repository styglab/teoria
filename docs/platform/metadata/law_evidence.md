# 법령 근거 검색


법령 검색은 Platform **Admin 진단 API**다. 별도 Ontology,
임베딩 모델, 벡터 DB와 Neo4j를 사용하지 않는다. Runtime Capability나 MCP Tool로
등록하지 않았으며, 해당 경로를 추가할 때 Database Source·Mapping·Published
artifact 계약을 별도로 작성해야 한다. 검색 데이터는 Pipeline migration
`083_legal_information_search_views.sql`의 읽기 전용 view 두 개로 제공한다.
Runtime/Admin 공용 읽기 계정에는 view만 허용하고 원본 테이블·Raw에는 권한을
부여하지 않는다.

```text
POST /v1/admin/legal-information/search
GET /v1/admin/legal-information/documents/{snapshot_id}?path=...
```

검색 요청 예:

```json
{
  "query": "개인정보 민감정보",
  "assessment_date": "2026-10-12",
  "version_scope": "as_of",
  "match": "any",
  "limit": 10
}
```

`law_id`를 추가하면 법령 범위를 제한한다. 검색어는 최대 8개 키워드, 200자이며
`match=any`는 OR, `match=all`은 AND다. SQL wildcard는 리터럴 문자로 처리한다.
조문 제목·본문(하위 항·호·목 포함)·법령명을 검색하고 제목/본문 일치를 먼저
정렬한다. 형태소 분석, 동의어 확장이나 의미 검색은 하지 않는다.

`as_of`는 공포일·시행일을 이용해 법령별 후보 버전을 고른다. 기준일 이후 버전과
그 날짜에 아직 시행하지 않은 조항을 제외한다. 최신 후보의 본문이 미수집이면
이전 버전으로 대체하지 않고 `unavailable_versions`에 표시한다. 폐지된 후보를
제외할 때도 이전 버전을 다시 선택하지 않는다. 부칙·개별 적용례와 다른 법령의
예외까지 자동 판단하는 기능은 아니므로 `legal_applicability_confirmed=false`를
항상 반환한다. `version_scope=all`은 수집된 연혁·현행·예정 후보를 함께 검색한다.

결과는 시행 버전, snapshot ID, 원문 hash, parser version, 조항 path와 1,000자
발췌를 포함한다. 발췌는 잘림 여부를 표시한다. 공포본의 외부 화면 링크는
`source_publication_url`이며 분리시행 slice의 근거는 snapshot·path로 고정한다.
문서 조회는 같은 snapshot·path를 사용하므로 이후 원문이 정정되어도 기존 근거를
조회할 수 있다. 기본 20,000자, 최대 50,000자를 반환하며 잘림 여부를 표시한다.

## 구현과 데이터 준비

`backend/src/teoria/features/legal_information/search.py`가 Data DB read view를 조회하고
`admin_api.py`가 HTTP API를 제공한다. Admin 서비스 조립은 `admin/composition.py`가
담당하며 `TEORIA_ADMIN_DATA_DATABASE_URL`의 read-only 계정을 사용한다.

검색 전 [법령 수집](../../pipelines/domains/legal_information.md)과 migration 083을 적용한다.
법령 본문은 Application DB로 복제하지 않는다. 자산 진단은 snapshot·path·hash를
근거로 참조한다. [자산 진단](asset_assessment.md)의 findings는 법률 적용성 확정이나
자동 공개 승인을 대신하지 않는다.
