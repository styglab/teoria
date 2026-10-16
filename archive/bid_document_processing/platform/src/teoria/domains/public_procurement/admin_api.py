from typing import Any

from fastapi import APIRouter, HTTPException

from teoria.domains.public_procurement.bid_check import BidCheckReader
from teoria.registry.loader import RegistryCatalog


def create_bid_check_router(reader: BidCheckReader | None) -> APIRouter:
    router = APIRouter(tags=["bid-check"])

    @router.get("/v1/admin/bid-check/notices")
    def bid_check_notices(page: int = 1, page_size: int = 50,
                          query: str | None = None, bid_status: str | None = None,
                          work_type: str | None = None, extraction_status: str | None = None,
                          review_status: str | None = None) -> dict[str, Any]:
        if reader is None:
            raise HTTPException(status_code=503, detail={"code": "bid_check_database_unavailable"})
        return reader.list_notices(
            page=max(1, page), page_size=max(1, min(page_size, 100)), query=query,
            bid_status=bid_status, work_type=work_type, extraction_status=extraction_status,
            review_status=review_status,
        )

    @router.get("/v1/admin/bid-check/notices/{bid_notice_id}/requirements")
    def bid_check_requirements(bid_notice_id: str) -> dict[str, Any]:
        if reader is None:
            raise HTTPException(status_code=503, detail={"code": "bid_check_database_unavailable"})
        return {"requirements": reader.get_requirements(bid_notice_id)}

    return router


def create_eligibility_rule_router(resolved_catalog: RegistryCatalog) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/admin/eligibility-rules")
    async def list_eligibility_rules() -> dict[str, list[dict[str, Any]]]:
        return {
            "eligibility_rules": [
                {
                    "id": rule.id,
                    "name": rule.name or rule.id,
                    "description": rule.description,
                    "version": rule.version,
                    "evaluator": rule.evaluator,
                    "evaluability": rule.evaluability,
                    "arguments": [item.model_dump() for item in rule.arguments],
                    "required_facts": rule.required_facts,
                    "missing_fact_result": rule.missing_fact_result,
                }
                for rule in resolved_catalog.eligibility_rules.values()
            ]
        }


    return router
