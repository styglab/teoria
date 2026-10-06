from __future__ import annotations

from typing import Any

from teoria.registry.loader import RegistryCatalog


def build_runtime_contract_graph(
    catalog: RegistryCatalog, runtime_contract_ids: list[str],
) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    for ontology_id in runtime_contract_ids:
        ontology = catalog.runtime_contracts[ontology_id]
        for object_type in ontology.object_types:
            node_id = f"{ontology.id}.{object_type.id}"
            nodes[node_id] = {
                "id": node_id,
                "ontology": ontology.id,
                "object_type": object_type.id,
                "name": object_type.name,
                "description": object_type.description,
                "primary_key": object_type.primary_key,
                "external": False,
                "properties": [
                    {
                        "id": item.id,
                        "name": item.name,
                        "description": item.description,
                        "type": item.data_type or item.value_set,
                        "collection": item.collection,
                    }
                    for item in object_type.properties
                ],
            }
    for ontology_id in runtime_contract_ids:
        ontology = catalog.runtime_contracts[ontology_id]
        for link in ontology.link_types:
            source = _qualified_object_id(ontology.id, link.source)
            target = _qualified_object_id(ontology.id, link.target)
            for reference in (source, target):
                if reference not in nodes:
                    external_ontology, external_type = reference.split(".", 1)
                    nodes[reference] = {
                        "id": reference,
                        "ontology": external_ontology,
                        "object_type": external_type,
                        "name": external_type,
                        "description": "다른 Runtime domain에서 정의된 Object Type",
                        "primary_key": None,
                        "external": True,
                        "properties": [],
                    }
            edges.append(
                {
                    "id": f"{ontology.id}.{link.id}",
                    "ontology": ontology.id,
                    "link_type": link.id,
                    "name": link.name or link.id,
                    "description": link.description,
                    "source": source,
                    "target": target,
                }
            )
    if len(runtime_contract_ids) == 1:
        ontology = catalog.runtime_contracts[runtime_contract_ids[0]]
        metadata = {"id": ontology.id, "name": ontology.name, "description": ontology.description}
    else:
        metadata = {
            "id": "all",
            "name": "전체 Runtime Contract",
            "description": "모든 Runtime Object Type과 실행 관계를 통합해 표시한다.",
        }
    return {
        "runtime_contract": metadata,
        "nodes": list(nodes.values()),
        "edges": edges,
    }
def _qualified_object_id(ontology_id: str, reference: str) -> str:
    return reference if "." in reference else f"{ontology_id}.{reference}"
