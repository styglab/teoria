from __future__ import annotations

import hashlib
import re
from datetime import date
from uuid import UUID


from teoria.domains.legal_information.search import LawSearchRequest
from teoria.intelligence.asset_assessment.models import AssessmentJob, LawQueries
from teoria.intelligence.asset_assessment.prompts import LAW_QUERY_INSTRUCTION


def law_search_queries(columns: list[dict], generated: list[str]) -> list[str]:
    """Korean retrieval expansion only; these keywords do not classify a column."""
    text = " ".join(
        str(c.get("name", "")) + " " + str(c.get("description") or "") for c in columns
    ).lower()
    seeds = []
    for terms, keyword in (
        (("resident", "rrn", "주민등록"), "주민등록번호"),
        (
            (
                "representative",
                "name",
                "email",
                "phone",
                "address",
                "성명",
                "이름",
                "전화",
                "주소",
            ),
            "개인정보",
        ),
        (("health", "medical", "건강", "질병"), "민감정보"),
    ):
        if any(term in text for term in terms):
            seeds.append(keyword)
    korean = [query for query in generated if (re.search("[가-힣]", query))]
    return list(dict.fromkeys(seeds + korean + ["공공데이터"]))[:3]


async def collect_law_evidence(
    job: AssessmentJob,
    columns: list[dict],
    context: dict,
    evidence: dict,
    model,
    law_reader,
) -> tuple[list[dict], bool]:
    partial = False
    diagnostics = []
    if "disclosure_assessment" in job["scopes"]:
        if law_reader is None:
            partial = True
            diagnostics.append(
                {
                    "scope": "disclosure_assessment",
                    "summary": "법령 저장소가 설정되지 않아 진단 근거를 확인하지 못했습니다.",
                    "code": "law_reader_unavailable",
                }
            )
        else:
            queries = await model.generate(
                instruction=LAW_QUERY_INSTRUCTION,
                context=context,
                output_type=LawQueries,
            )
            documents = []
            seen_documents = set()
            for query in law_search_queries(columns, queries.queries):
                result = await law_reader.search(
                    LawSearchRequest(
                        query=query,
                        assessment_date=date.fromisoformat(str(job["assessment_date"])),
                        limit=3,
                    )
                )
                if result["unavailable_versions"]:
                    partial = True
                    diagnostics.append(
                        {
                            "scope": "disclosure_assessment",
                            "summary": "평가 기준일에 해당하는 일부 법령 버전이 수집되지 않았습니다.",
                            "code": "law_version_unavailable",
                        }
                    )
                for hit in result["items"]:
                    identity = (str(hit["snapshot_id"]), hit["path"])
                    if identity in seen_documents or len(documents) >= 5:
                        continue
                    document = await law_reader.get_document(
                        UUID(str(hit["snapshot_id"])), hit["path"], max_chars=12000
                    )
                    if not document or document["content_truncated"]:
                        partial = True
                        continue
                    seen_documents.add(identity)
                    key = f"law:{len(documents) + 1}"
                    documents.append({"evidence_id": key, **document})
                    evidence[key] = {
                        "evidence_type": "law_snapshot",
                        "source_ref": f"legal_information://snapshot/{hit['snapshot_id']}?path={hit['path']}",
                        "content_hash": hashlib.sha256(
                            document["content"].encode()
                        ).hexdigest(),
                        "provenance": {
                            k: str(hit.get(k) or "")
                            for k in (
                                "law_id",
                                "mst",
                                "law_name",
                                "effective_date",
                                "snapshot_id",
                                "path",
                            )
                        }
                        | {"assessment_date": str(job["assessment_date"])},
                    }
            context["law_documents"] = documents
            if not documents:
                partial = True
                diagnostics.append(
                    {
                        "scope": "disclosure_assessment",
                        "summary": "확인 가능한 법령 근거를 찾지 못했습니다. 추가 법령 검토가 필요합니다.",
                        "code": "law_evidence_not_found",
                    }
                )
    return diagnostics, partial
