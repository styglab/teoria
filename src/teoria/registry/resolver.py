from collections.abc import Iterator

from teoria.registry.schema.common import FieldDefinition
from teoria.registry.schema.source import FieldContainer, SourceRegistry


def iter_fields(container: FieldContainer | FieldDefinition) -> Iterator[FieldDefinition]:
    for field in container.fields:
        yield field
        yield from iter_fields(field)
        if field.items is not None:
            yield field.items
            yield from iter_fields(field.items)


def iter_source_fields(registry: SourceRegistry) -> Iterator[FieldDefinition]:
    source = registry.source
    for obj in source.components.objects:
        for field in obj.fields:
            yield field
            yield from iter_fields(field)
    for operation in source.operations:
        if operation.request:
            for container in (operation.request.query, operation.request.header, operation.request.body):
                if container:
                    yield from iter_fields(container)
        if operation.response.control:
            yield from iter_fields(operation.response.control)
        for field in operation.response.data.fields:
            yield field
            yield from iter_fields(field)

