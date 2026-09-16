from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import psycopg
import re
from psycopg.types.json import Jsonb

from teoria_pipelines.models import (
    BidNoticeKey,
    CollectionWindow,
    LoadSummary,
    NormalizedBatch,
    NormalizedBidResultBatch,
    NormalizedBidNoticeBatch,
    RawProviderRecord,
)

from teoria_pipelines.persistence.postgres_store.support import (
    _filter_covered_unavailable_documents,
    _sanitize_postgres_value,
    _validate_industry_snapshot,
    eligibility_requires_review,
)


class EligibilityStoreMixin:
    """eligibility persistence operations."""

    def list_notices_for_eligibility_extraction(self, limit: int,
                                                download_max_attempts: int = 3,
                                                parse_max_attempts: int = 3,
                                                notice_keys: list[tuple[str, str]] | None = None,
                                                ) -> list[dict[str, Any]]:
        key_filter = ""
        parameters: list[Any] = [download_max_attempts, parse_max_attempts]
        if notice_keys:
            key_filter = (
                "AND (n.notice_number,n.notice_order) IN "
                "(SELECT * FROM unnest(%s::text[],%s::text[])) "
            )
            parameters.extend([
                [item[0] for item in notice_keys], [item[1] for item in notice_keys],
            ])
        parameters.append(limit)
        with psycopg.connect(self.database_url) as connection:
            notices = connection.execute(
                "SELECT n.notice_number, n.notice_order, n.source_record_hash, n.bid_deadline_at, "
                "n.source_payload->>'cmmnSpldmdMethdNm', "
                "n.participation_restriction_region_code, "
                "n.participation_restriction_region_name "
                "FROM public_procurement.bid_notices n WHERE (EXISTS (SELECT 1 FROM "
                "public_procurement.bid_notice_documents d WHERE d.notice_number=n.notice_number "
                "AND d.notice_order=n.notice_order AND d.parse_status='parsed' "
                "AND d.storage_status='active' AND d.parsed_object_key IS NOT NULL) OR EXISTS (SELECT 1 FROM "
                "public_procurement.bid_notice_license_restrictions l WHERE l.notice_number=n.notice_number "
                "AND l.notice_order=n.notice_order) OR EXISTS (SELECT 1 FROM "
                "public_procurement.bid_notice_participation_regions r WHERE r.notice_number=n.notice_number "
                "AND r.notice_order=n.notice_order) OR (n.participation_restriction_region_code IS NOT NULL "
                "AND n.participation_restriction_region_code <> '00')) AND NOT EXISTS (SELECT 1 FROM "
                "public_procurement.bid_notice_documents d WHERE d.notice_number=n.notice_number "
                "AND d.notice_order=n.notice_order AND (d.status IN ('pending','processing') "
                "OR (d.status='failed' AND d.attempts < %s) "
                "OR (d.status='stored' AND (d.parse_status IN ('pending','processing') "
                "OR (d.parse_status='failed' AND d.parse_attempts < %s))))) "
                + key_filter +
                "AND n.notice_kind_name IS DISTINCT FROM '취소공고' "
                "AND COALESCE(n.notice_kind_name, '') !~ '(평가|개찰|낙찰|계약).*(결과|결정)' "
                "AND COALESCE(n.notice_name, '') !~ '^\\s*(\\([^)]*\\)\\s*)?"
                "(제안서\\s*)?(평가|개찰|낙찰|계약).*(결과|결정|공개)' "
                "AND NOT EXISTS (SELECT 1 "
                "FROM public_procurement.bid_notices newer WHERE newer.notice_number=n.notice_number "
                "AND (COALESCE(CASE WHEN newer.notice_order ~ '^[0-9]+$' "
                "THEN newer.notice_order::numeric END,-1), newer.notice_order, "
                "COALESCE(newer.notice_published_at,'-infinity'::timestamptz)) > "
                "(COALESCE(CASE WHEN n.notice_order ~ '^[0-9]+$' THEN n.notice_order::numeric END,-1), "
                "n.notice_order, COALESCE(n.notice_published_at,'-infinity'::timestamptz))) "
                "ORDER BY n.notice_published_at DESC NULLS LAST, n.notice_number, n.notice_order DESC "
                "LIMIT %s", parameters
            ).fetchall()
            result = []
            for (number, order, notice_hash, deadline, consortium_method,
                 summary_region_code, summary_region_name) in notices:
                documents = connection.execute(
                    "SELECT document_id, file_name, checksum, parsed_object_key FROM "
                    "public_procurement.bid_notice_documents WHERE notice_number=%s AND notice_order=%s "
                    "AND parse_status='parsed' AND storage_status='active' "
                    "AND parsed_object_key IS NOT NULL ORDER BY document_slot", (number, order)
                ).fetchall()
                # 나라장터의 `표준공고서` URL은 원본 첨부파일과 같은 객체를 중복 제공한다.
                # AI 입력에는 checksum별 한 건만 전달하되 구체적인 파일명을 우선한다.
                documents = sorted(
                    documents,
                    key=lambda row: (str(row[1] or "").strip() == "표준공고서", str(row[1] or "")),
                )
                documents = list({row[2] or row[0]: row for row in reversed(documents)}.values())
                unavailable_documents = connection.execute(
                    "SELECT document_id, file_name, status, attempts, last_error_code, "
                    "parse_status, parse_attempts, parse_error_code, checksum FROM "
                    "public_procurement.bid_notice_documents WHERE notice_number=%s "
                    "AND notice_order=%s AND NOT (status='stored' AND parse_status='parsed') "
                    "AND NOT EXISTS (SELECT 1 FROM public_procurement.bid_notice_documents sibling "
                    "WHERE sibling.notice_number=bid_notice_documents.notice_number "
                    "AND sibling.notice_order=bid_notice_documents.notice_order "
                    "AND sibling.checksum=bid_notice_documents.checksum "
                    "AND sibling.status='stored' AND sibling.parse_status='parsed' "
                    "AND sibling.storage_status='active' AND sibling.parsed_object_key IS NOT NULL) "
                    "ORDER BY document_slot", (number, order)
                ).fetchall()
                unavailable_documents = _filter_covered_unavailable_documents(
                    documents, unavailable_documents
                )
                licenses = connection.execute(
                    "SELECT restriction_group_number, restriction_sequence, license_restriction_name, "
                    "permitted_industry_list, industry_main_field_list, business_type_name, source_record_hash "
                    "FROM public_procurement.bid_notice_license_restrictions "
                    "WHERE notice_number=%s AND notice_order=%s", (number, order)
                ).fetchall()
                regions = connection.execute(
                    "SELECT restriction_sequence, participation_region_code, participation_region_name, "
                    "business_type_name, source_record_hash "
                    "FROM public_procurement.bid_notice_participation_regions "
                    "WHERE notice_number=%s AND notice_order=%s", (number, order)
                ).fetchall()
                normalized_regions = [
                    dict(zip(("sequence", "code", "name", "business_type", "source_hash"),
                             row, strict=True))
                    for row in regions
                    if row[1] != "00" and str(row[2] or "").strip() != "전국"
                ]
                has_detailed_region_response = bool(regions)
                summary_has_limit = summary_region_code not in (None, "", "00")
                region_conflict = False
                if has_detailed_region_response:
                    if summary_region_code == "00" and normalized_regions:
                        region_conflict = True
                    elif summary_has_limit and not any(
                        item["code"] == summary_region_code
                        or (summary_region_name and item["name"] == summary_region_name)
                        for item in normalized_regions
                    ):
                        region_conflict = True
                if not normalized_regions and summary_region_code not in (None, "", "00"):
                    normalized_regions.append({
                        "sequence": "summary", "code": summary_region_code,
                        "name": summary_region_name, "business_type": None,
                        "source_hash": notice_hash,
                    })
                consortiums = []
                if consortium_method and consortium_method.strip() not in {"", "(없음)", "없음"}:
                    consortiums.append({
                        "sequence": "method",
                        "name": consortium_method.strip(),
                        "source_hash": notice_hash,
                    })
                total_documents = len(documents) + len(unavailable_documents)
                unavailable_count = len(unavailable_documents)
                completeness = (
                    "api_only" if total_documents == 0
                    else "partial" if unavailable_count else "complete"
                )
                result.append({
                    "notice_number": number, "notice_order": order,
                    "notice_hash": notice_hash, "bid_deadline_at": deadline.isoformat() if deadline else None,
                    "documents": [dict(zip(("document_id", "file_name", "checksum", "parsed_object_key"), row, strict=True)) for row in documents],
                    "unavailable_documents": [dict(zip(("document_id", "file_name", "status", "attempts", "error_code", "parse_status", "parse_attempts", "parse_error_code"), row[:8], strict=True)) for row in unavailable_documents],
                    "licenses": [dict(zip(("group", "sequence", "name", "permitted_industries", "main_fields", "business_type", "source_hash"), row, strict=True)) for row in licenses],
                    "regions": normalized_regions,
                    "consortiums": consortiums,
                    "coverage": {
                        "completeness": completeness,
                        "requires_review": unavailable_count > 0 or region_conflict,
                        "total_document_count": total_documents,
                        "parsed_document_count": len(documents),
                        "unavailable_document_count": unavailable_count,
                        "structured_requirement_count": len(licenses) + len(normalized_regions) + len(consortiums),
                        "participation_region_source": (
                            "detailed_api" if has_detailed_region_response else
                            "notice_summary" if summary_has_limit else "unrestricted_or_absent"
                        ),
                        "participation_region_conflict": region_conflict,
                    },
                })
        return result

    def completed_eligibility_fingerprints(self) -> set[str]:
        with psycopg.connect(self.database_url) as connection:
            rows = connection.execute(
                "SELECT input_fingerprint FROM public_procurement.bid_eligibility_extractions "
                "WHERE status='completed' OR (status='failed' AND finished_at>now()-interval '1 hour') "
                "OR (status='processing' AND started_at>now()-interval '1 hour')"
            ).fetchall()
        return {row[0] for row in rows}

    def claim_eligibility_extraction(self, notice: dict[str, Any], fingerprint: str,
                                     skill_version: str) -> bool:
        """Atomically lease one extraction fingerprint for one hour."""
        with psycopg.connect(self.database_url) as connection:
            claimed = connection.execute(
                "INSERT INTO public_procurement.bid_eligibility_extractions "
                "(extraction_id,notice_number,notice_order,input_fingerprint,schema_version,"
                "skill_version,status,started_at) VALUES (%s,%s,%s,%s,'1.1.0',%s,'processing',now()) "
                "ON CONFLICT (notice_number,notice_order,input_fingerprint) DO UPDATE SET "
                "status='processing',skill_version=EXCLUDED.skill_version,started_at=now(),"
                "finished_at=NULL,error_code=NULL WHERE "
                "(bid_eligibility_extractions.status='failed' AND "
                "bid_eligibility_extractions.finished_at<=now()-interval '1 hour') OR "
                "(bid_eligibility_extractions.status='processing' AND "
                "bid_eligibility_extractions.started_at<=now()-interval '1 hour') RETURNING 1",
                (uuid4(), notice["notice_number"], notice["notice_order"], fingerprint,
                 skill_version),
            ).fetchone()
        return claimed is not None

    def save_eligibility_failure(self, notice: dict[str, Any], fingerprint: str,
                                 error_code: str, raw_output_object_key: str | None,
                                 model_name: str | None, skill_version: str) -> None:
        coverage = notice["coverage"]
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "INSERT INTO public_procurement.bid_eligibility_extractions "
                "(extraction_id,notice_number,notice_order,input_fingerprint,schema_version,"
                "skill_version,model_name,status,raw_output_object_key,error_code,finished_at,"
                "completeness,requires_review,total_document_count,parsed_document_count,"
                "unavailable_document_count,unavailable_documents,structured_requirement_count) "
                "VALUES (%s,%s,%s,%s,'1.1.0',%s,%s,'failed',%s,%s,now(),%s,true,%s,%s,%s,%s,%s) "
                "ON CONFLICT (notice_number,notice_order,input_fingerprint) DO UPDATE SET "
                "status='failed',schema_version=EXCLUDED.schema_version,skill_version=EXCLUDED.skill_version,"
                "model_name=EXCLUDED.model_name,raw_output_object_key=EXCLUDED.raw_output_object_key,"
                "error_code=EXCLUDED.error_code,finished_at=now(),requires_review=true",
                (uuid4(), notice["notice_number"], notice["notice_order"], fingerprint,
                 skill_version, model_name, raw_output_object_key, error_code[:500], coverage["completeness"],
                 coverage["total_document_count"], coverage["parsed_document_count"],
                 coverage["unavailable_document_count"], Jsonb([
                     {**item, "document_id": str(item["document_id"])}
                     for item in notice["unavailable_documents"]
                 ]), coverage["structured_requirement_count"]),
            )

    def save_eligibility_extraction(self, notice: dict[str, Any], fingerprint: str,
                                    result: dict[str, Any], raw_output_object_key: str,
                                    model_name: str | None, skill_version: str) -> bool:
        result = _sanitize_postgres_value(result)
        extraction_id = uuid4()
        with psycopg.connect(self.database_url) as connection:
            existing = connection.execute(
                "SELECT 1 FROM public_procurement.bid_eligibility_extractions WHERE "
                "notice_number=%s AND notice_order=%s AND input_fingerprint=%s AND status='completed'",
                (notice["notice_number"], notice["notice_order"], fingerprint),
            ).fetchone()
            if existing:
                return False
            connection.execute(
                "INSERT INTO public_procurement.bid_eligibility_extractions "
                "(extraction_id,notice_number,notice_order,input_fingerprint,schema_version,skill_version,model_name,status,raw_output_object_key,finished_at,completeness,requires_review,total_document_count,parsed_document_count,unavailable_document_count,unavailable_documents,structured_requirement_count) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,'completed',%s,now(),%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (notice_number,notice_order,input_fingerprint) DO UPDATE SET "
                "extraction_id=EXCLUDED.extraction_id,status='completed',"
                "schema_version=EXCLUDED.schema_version,skill_version=EXCLUDED.skill_version,"
                "model_name=EXCLUDED.model_name,"
                "raw_output_object_key=EXCLUDED.raw_output_object_key,error_code=NULL,finished_at=now(),"
                "completeness=EXCLUDED.completeness,requires_review=EXCLUDED.requires_review,"
                "total_document_count=EXCLUDED.total_document_count,parsed_document_count=EXCLUDED.parsed_document_count,"
                "unavailable_document_count=EXCLUDED.unavailable_document_count,unavailable_documents=EXCLUDED.unavailable_documents,"
                "structured_requirement_count=EXCLUDED.structured_requirement_count",
                (extraction_id, notice["notice_number"], notice["notice_order"], fingerprint,
                 result["schema_version"], skill_version, model_name, raw_output_object_key,
                 notice["coverage"]["completeness"], eligibility_requires_review(notice, result),
                 notice["coverage"]["total_document_count"], notice["coverage"]["parsed_document_count"],
                 notice["coverage"]["unavailable_document_count"], Jsonb([
                     {**item, "document_id": str(item["document_id"])}
                     for item in notice["unavailable_documents"]
                 ]),
                 notice["coverage"]["structured_requirement_count"]),
            )
            connection.execute(
                "INSERT INTO public_procurement.bid_eligibility_requirement_sets "
                "(extraction_id,expression,unresolved_candidates) VALUES (%s,%s,%s)",
                (extraction_id, Jsonb(result["expression"]), Jsonb(result["unresolved_candidates"])),
            )
            for item in result.get("participation_findings", []):
                finding_id = uuid5(NAMESPACE_URL, f"teoria:{extraction_id}:{item['id']}")
                connection.execute(
                    "INSERT INTO public_procurement.bid_participation_findings "
                    "(finding_id,extraction_id,local_id,notice_number,notice_order,category,"
                    "finding_type,title,subject,stage,description,deadline_text,failure_effect,"
                    "importance,competitive_effect,legitimate_justification,review_status,confidence) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (finding_id, extraction_id, item["id"], notice["notice_number"],
                     notice["notice_order"], item["category"], item["type"], item["title"],
                     item["subject"], item["stage"], item["description"], item["deadline_text"],
                     item["failure_effect"], item["importance"], item["competitive_effect"],
                     item["legitimate_justification"], item["review_status"], item["confidence"]),
                )
                for evidence in item["evidence"]:
                    connection.execute(
                        "INSERT INTO public_procurement.bid_participation_finding_evidence "
                        "(evidence_id,finding_id,source_type,source_id,document_id,block_id,"
                        "page_number,section,excerpt) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (uuid4(), finding_id, evidence["source_type"], evidence["source_id"],
                         evidence["document_id"], evidence["block_id"], evidence["page"],
                         evidence["section"], evidence["excerpt"]),
                    )
            for item in result["requirements"]:
                requirement_id = uuid5(NAMESPACE_URL, f"teoria:{extraction_id}:{item['id']}")
                connection.execute(
                    "INSERT INTO public_procurement.bid_eligibility_requirements "
                    "(requirement_id,extraction_id,local_id,notice_number,notice_order,requirement_type,operator,value,original_text,proposition_text,proposition_start,proposition_end,holder_scope,reference_date_type,assessment_stage,failure_effect,comparison_mode,mandatory,review_status,confidence,standard_rule_id,standard_rule_version,rule_arguments) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (requirement_id, extraction_id, item["id"], notice["notice_number"],
                     notice["notice_order"], item["type"], item["operator"], Jsonb(item["value"]),
                     item["original_text"], item["proposition_text"], item["proposition_start"],
                     item["proposition_end"], item["holder_scope"], item["reference_date_type"],
                     item["assessment_stage"], item["failure_effect"], item["comparison_mode"],
                     item["mandatory"], item["review_status"], item["confidence"],
                     item.get("standard_rule_id"), item.get("standard_rule_version"),
                     Jsonb(item.get("rule_arguments") or {})),
                )
                for evidence in item["evidence"]:
                    connection.execute(
                        "INSERT INTO public_procurement.bid_eligibility_requirement_evidence "
                        "(evidence_id,requirement_id,source_type,source_id,document_id,block_id,page_number,section,excerpt) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (uuid4(), requirement_id, evidence["source_type"], evidence["source_id"],
                         evidence["document_id"], evidence["block_id"], evidence["page"],
                         evidence["section"], evidence["excerpt"]),
                    )
                for proof in item["proof_requirements"]:
                    proof_id = uuid5(
                        NAMESPACE_URL,
                        f"teoria:{extraction_id}:{item['id']}:{proof['id']}",
                    )
                    connection.execute(
                        "INSERT INTO public_procurement.bid_eligibility_requirement_proofs "
                        "(proof_id,requirement_id,local_id,document_type,submission_stage,deadline_text,mandatory,review_status) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        (proof_id, requirement_id, proof["id"], proof["document_type"],
                         proof["submission_stage"], proof["deadline_text"], proof["mandatory"],
                         proof["review_status"]),
                    )
                    for evidence in proof["evidence"]:
                        connection.execute(
                            "INSERT INTO public_procurement.bid_eligibility_requirement_proof_evidence "
                            "(evidence_id,proof_id,source_type,source_id,document_id,block_id,page_number,section,excerpt) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (uuid4(), proof_id, evidence["source_type"], evidence["source_id"],
                             evidence["document_id"], evidence["block_id"], evidence["page"],
                             evidence["section"], evidence["excerpt"]),
                        )
        return True
