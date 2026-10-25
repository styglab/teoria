from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import re
import time
from urllib.parse import quote, quote_plus

from teoria.integrations.provider_api.executor import ProviderExecutor
from teoria.integrations.provider_api.request_builder import ProviderRequestBuilder
from teoria.integrations.provider_api.response_validator import ProviderResponseValidator
from teoria.integrations.data_operations.loader import PipelineLoader
from teoria.features.legal_information.collection.models import LawCatalog, LawResponse, LawTarget, LawVersion
from teoria.features.legal_information.collection.parsing import LawValidationError, parse_listing


def redact_xml(raw: bytes, credential: str | None) -> bytes:
    # Provider detail links echo OC, even when the payload is otherwise public.
    # Keep raw XML bytes with only credential echoes redacted; hash these bytes.
    if credential:
        for value in {credential, quote(credential, safe=""), quote_plus(credential)}:
            raw = raw.replace(value.encode(), b"REDACTED")
    return re.sub(rb"(?i)([?&](?:amp;)?OC=)[^&<\"'\s]*", rb"\1REDACTED", raw)


class MolegLawClient:
    def __init__(self, definition, *, path: Path, executor: ProviderExecutor,
                 requests_per_second: float = 1, page_size: int = 100, max_pages: int = 1000):
        if not 0 < requests_per_second <= 10 or not 1 <= page_size <= 100 or max_pages < 1:
            raise ValueError("invalid law collection limits")
        self.definition, self.path, self.executor = definition, path, executor
        self.page_size, self.max_pages = page_size, max_pages
        self.interval, self.last_request = 1 / requests_per_second, 0.0

    @classmethod
    def from_pipeline_root(cls, root: str | Path, **kwargs):
        catalog = PipelineLoader(root).load()
        return cls(catalog.connectors["moleg_law_api"].connector,
                   path=catalog.connector_paths["moleg_law_api"], **kwargs)

    async def request(self, operation: str, query: dict) -> LawResponse:
        request = ProviderRequestBuilder().build(self.definition, operation, {"query": query}, path=self.path)
        credential = self.executor.credential(request)
        delay = self.interval - (time.monotonic() - self.last_request)
        if delay > 0:
            await asyncio.sleep(delay)
        self.last_request = time.monotonic()
        response = await self.executor.execute(request)
        if ProviderResponseValidator().validate(self.definition, operation, response, path=self.path):
            raise LawValidationError("law_provider_contract_failed")
        if response.raw_body is None:
            raise LawValidationError("law_original_response_unavailable")
        return LawResponse(operation, dict(query), datetime.now(timezone.utc), response.content_type,
                           redact_xml(response.raw_body, credential))

    async def resolve_target(self, target: LawTarget) -> tuple[str, list[LawResponse]]:
        if target.law_id:
            return target.law_id, []
        responses = []
        candidates = set()
        expected_total = None
        count = 0
        for page in range(1, self.max_pages + 1):
            response = await self.request("list_law_versions", {
                "query": target.name, "nw": "3", "display": self.page_size, "page": page})
            responses.append(response)
            total, actual_page, rows = parse_listing(response.raw_body)
            if actual_page != page or (expected_total is not None and total != expected_total):
                raise LawValidationError("law_catalog_changed_during_fetch")
            expected_total = total
            key = lambda s: re.sub(r"[\sㆍ·]", "", s)
            candidates.update(row.law_id for row in rows if key(row.name) == key(target.name))
            count += len(rows)
            if count >= total:
                if count != total or len(candidates) != 1:
                    raise LawValidationError("law_target_not_unique_exact_match")
                return candidates.pop(), responses
            if not rows:
                raise LawValidationError("law_incomplete_catalog")
        raise LawValidationError("law_catalog_page_limit_exceeded")

    async def collect_catalog(self, law_id: str) -> LawCatalog:
        versions, responses, seen = [], [], set()
        expected_total = None
        for page in range(1, self.max_pages + 1):
            response = await self.request("list_law_versions", {
                "LID": law_id, "nw": "1,2,3", "display": self.page_size, "page": page})
            responses.append(response)
            total, actual_page, rows = parse_listing(response.raw_body)
            if actual_page != page or (expected_total is not None and total != expected_total):
                raise LawValidationError("law_catalog_changed_during_fetch")
            expected_total = total
            for row in rows:
                if row.law_id != law_id:
                    raise LawValidationError("law_id_filter_mismatch")
                if row.key in seen:
                    raise LawValidationError("law_duplicate_version")
                seen.add(row.key)
                versions.append(row)
            if len(versions) >= total:
                if not versions or len(versions) != total:
                    raise LawValidationError("law_incomplete_catalog")
                return LawCatalog(law_id, versions, responses)
            if not rows:
                raise LawValidationError("law_incomplete_catalog")
        raise LawValidationError("law_catalog_page_limit_exceeded")

    async def fetch_version(self, version: LawVersion) -> LawResponse:
        # No current-law or MST-only fallback: wrong-date text is a failed fetch.
        return await self.request("get_law_version", {
            "MST": version.mst, "efYd": version.effective_date.strftime("%Y%m%d")})
