from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from teoria.runtime.capability.binder import CapabilityBinder
from teoria.runtime.mapping.decoder import MappedFragment, MappingDecoder
from teoria.runtime.mapping.materializer import MaterializedLink, MaterializedObject, OntologyMaterializer
from teoria.runtime.source.executor import SourceExecutor
from teoria.runtime.source.errors import SourceExecutionError
from teoria.runtime.source.response import ExecutionResponse
from teoria.runtime.source.request_builder import SourceRequestBuilder
from teoria.runtime.source.response_validator import SourceResponseValidator
from teoria.registry.loader import RegistryCatalog


class CapabilityExecutionError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        capability_id: str,
        source_id: str | None = None,
        operation_id: str | None = None,
        page: int | None = None,
        attempts: int | None = None,
        retryable: bool = False,
    ) -> None:
        self.code = code
        self.capability_id = capability_id
        self.source_id = source_id
        self.operation_id = operation_id
        self.page = page
        self.attempts = attempts
        self.retryable = retryable
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "capability": self.capability_id,
            "source": self.source_id,
            "operation": self.operation_id,
            "page": self.page,
            "attempts": self.attempts,
            "retryable": self.retryable,
        }


class CapabilityResult(BaseModel):
    capability_id: str
    objects: list[MaterializedObject] = Field(default_factory=list)
    links: list[MaterializedLink] = Field(default_factory=list)
    responses: list[ExecutionResponse] | None = None


class CapabilityRunner:
    def __init__(
        self,
        executor: Any | None = None,
        *,
        timeout_seconds: float = 120.0,
        max_pages: int = 100,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if max_pages < 1:
            raise ValueError("max_pages must be at least one")
        self.binder = CapabilityBinder()
        self.request_builder = SourceRequestBuilder()
        self.executor = executor or SourceExecutor()
        self.response_validator = SourceResponseValidator()
        self.decoder = MappingDecoder()
        self.materializer = OntologyMaterializer()
        self.timeout_seconds = timeout_seconds
        self.max_pages = max_pages

    async def run(
        self,
        catalog: RegistryCatalog,
        capability_id: str,
        inputs: dict[str, Any],
        *,
        include_raw_responses: bool = False,
    ) -> CapabilityResult:
        capability = catalog.capabilities.get(capability_id)
        if capability is None:
            raise CapabilityExecutionError("unknown_capability", f"unknown capability '{capability_id}'", capability_id=capability_id)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                return await self._run(catalog, capability_id, inputs, include_raw_responses=include_raw_responses)
        except TimeoutError as exc:
            raise CapabilityExecutionError(
                "capability_timeout",
                f"capability exceeded its {self.timeout_seconds:g} second deadline",
                capability_id=capability_id,
                retryable=True,
            ) from exc

    async def _run(
        self,
        catalog: RegistryCatalog,
        capability_id: str,
        inputs: dict[str, Any],
        *,
        include_raw_responses: bool,
    ) -> CapabilityResult:
        capability = catalog.capabilities[capability_id]
        allowed_objects = {item.split(".", 1)[1] for item in capability.returns if self._is_object(catalog, item)}
        allowed_links = {item.split(".", 1)[1] for item in capability.returns if not self._is_object(catalog, item)}
        fragments: list[MappedFragment] = []
        raw_responses: list[ExecutionResponse] = []
        observed_at = datetime.now(timezone.utc)

        for step in capability.steps:
            source_id, operation_id = step.call.split(".", 1)
            source = catalog.sources[source_id]
            operation = next(item for item in source.source.operations if item.id == operation_id)
            base_input = self.binder.bind(catalog, capability, step, inputs)
            page = 1
            while True:
                if page > self.max_pages:
                    raise CapabilityExecutionError(
                        "source_page_limit_exceeded",
                        f"source pagination exceeded the configured {self.max_pages} page limit",
                        capability_id=capability_id,
                        source_id=source_id,
                        operation_id=operation_id,
                        page=page,
                    )
                input_data = deepcopy(base_input)
                if operation.pagination:
                    self._set_request_value(input_data, operation.pagination.page.request, page)
                request = self.request_builder.build(catalog, source_id, operation_id, input_data)
                try:
                    response = await self.executor.execute(request)
                except SourceExecutionError as exc:
                    raise CapabilityExecutionError(
                        exc.code,
                        str(exc),
                        capability_id=capability_id,
                        source_id=source_id,
                        operation_id=operation_id,
                        page=page,
                        attempts=exc.attempts,
                        retryable=exc.retryable,
                    ) from exc
                diagnostics = self.response_validator.validate(catalog, source_id, operation_id, response)
                if diagnostics:
                    raise CapabilityExecutionError(
                        "source_response_invalid",
                        "\n".join(map(str, diagnostics)),
                        capability_id=capability_id,
                        source_id=source_id,
                        operation_id=operation_id,
                        page=page,
                    )
                if include_raw_responses:
                    raw_responses.append(response)
                fragments.extend(self.decoder.decode(catalog, source_id, operation_id, response, record_key_prefix=str(page)))
                if not operation.pagination or not self._has_next_page(operation, request, response, page):
                    break
                page += 1

        objects, links = self.materializer.materialize(catalog, fragments, observed_at, allowed_objects, allowed_links)
        return CapabilityResult(
            capability_id=capability_id,
            objects=objects,
            links=links,
            responses=raw_responses if include_raw_responses else None,
        )

    def _has_next_page(self, operation: Any, request: Any, response: ExecutionResponse, page: int) -> bool:
        pagination = operation.pagination
        total = int(self.decoder._resolve_path(response.body, pagination.total_count))
        section, field = pagination.page_size.request.split(".", 1)
        page_size = int(getattr(request, section).get(field, 0))
        records = self.decoder._resolve_path(response.body, operation.response.data.record_path)
        returned = len(records) if isinstance(records, list) else 1
        return returned > 0 and page_size > 0 and page * page_size < total

    @staticmethod
    def _set_request_value(input_data: dict[str, Any], reference: str, value: Any) -> None:
        section, field = reference.split(".", 1)
        input_data.setdefault(section, {})[field] = value

    @staticmethod
    def _is_object(catalog: RegistryCatalog, reference: str) -> bool:
        ontology_id, item_id = reference.split(".", 1)
        ontology = catalog.ontologies[ontology_id]
        return item_id in {item.id for item in ontology.object_types}
