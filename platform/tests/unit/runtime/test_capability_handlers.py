import asyncio
from pathlib import Path

import pytest

from teoria.registry.loader import RegistryCatalog, RegistryLoader
from teoria.registry.schema.capability import CapabilityDefinition
from teoria.runtime.capability.contracts import CapabilityExecutionError, CapabilityResult
from teoria.runtime.capability.handlers import CapabilityHandlers
from teoria.runtime.capability.runner import CapabilityRunner
from teoria.runtime.composition import create_capability_handlers


def compute_catalog(processor="example.calculate"):
    return RegistryCatalog(
        root=Path("."), sources={}, source_paths={}, data_types={},
        capabilities={"calculate": CapabilityDefinition(
            id="calculate", name="Calculate", description="Test compute handler",
            kind="compute", processor=processor, returns=["example.result"],
        )},
    )


@pytest.mark.asyncio
async def test_injected_processor_executes_without_domain_composition():
    handlers = CapabilityHandlers()

    async def calculate(runner, catalog, capability_id, inputs):
        return CapabilityResult(capability_id=capability_id, outcome={"value": inputs["value"] * 2})

    handlers.register_processor("example.calculate", calculate)
    result = await CapabilityRunner(handlers=handlers).run(compute_catalog(), "calculate", {"value": 3})
    assert result.outcome == {"value": 6}


@pytest.mark.asyncio
async def test_unregistered_processor_is_not_imported():
    with pytest.raises(CapabilityExecutionError) as exc:
        await CapabilityRunner(handlers=CapabilityHandlers()).run(compute_catalog("os.system"), "calculate", {})
    assert exc.value.code == "unknown_capability_processor"
    assert exc.value.capability_id == "calculate"


@pytest.mark.asyncio
async def test_injected_processor_obeys_runner_deadline():
    handlers = CapabilityHandlers()

    async def stalled(*args):
        await asyncio.Event().wait()

    handlers.register_processor("example.calculate", stalled)
    with pytest.raises(CapabilityExecutionError) as exc:
        await CapabilityRunner(handlers=handlers, timeout_seconds=0.01).run(compute_catalog(), "calculate", {})
    assert exc.value.code == "capability_timeout"
    assert exc.value.retryable is True


@pytest.mark.parametrize("method", ["register_processor", "register_query_hook"])
def test_duplicate_registration_cannot_replace_existing_handler(method):
    handlers = CapabilityHandlers()

    async def handler(*args):
        pass

    register = getattr(handlers, method)
    register("example.calculate", handler)
    with pytest.raises(ValueError, match="duplicate"):
        register("example.calculate", handler)


@pytest.fixture(scope="module")
def catalog():
    return RegistryLoader(Path(__file__).parents[3] / "registries").load()


def test_default_handlers_cover_existing_registry_processor_contracts(catalog):
    handlers = create_capability_handlers()
    processors = {capability.processor for capability in catalog.capabilities.values() if capability.kind != "query"}
    assert processors
    assert all(handlers.processor(processor) is not None for processor in processors)


@pytest.mark.asyncio
async def test_query_hook_runs_after_database_query_materialization(catalog):
    events = []

    class EmptyDatabase:
        def execute(self, *args):
            events.append("database")
            return []

    async def hook(runner, catalog, result, observed_at):
        events.append("hook")
        assert result.objects == []
        assert observed_at.tzinfo is not None
        return result.model_copy(update={"outcome": {"enriched": True}})

    handlers = CapabilityHandlers()
    handlers.register_query_hook("search_bid_notices", hook)
    result = await CapabilityRunner(handlers=handlers, database_executor=EmptyDatabase()).run(
        catalog, "search_bid_notices", {
            "notice_published_at_from": "2026-10-01T00:00:00",
            "notice_published_at_to": "2026-10-02T00:00:00",
        },
    )
    assert events == ["database", "hook"]
    assert result.outcome == {"enriched": True}
