from __future__ import annotations

from typing import Any

from teoria.registry.loader import RegistryCatalog


def build_ontology_graph(catalog: RegistryCatalog, ontology_ids: list[str]) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    for ontology_id in ontology_ids:
        ontology = catalog.ontologies[ontology_id]
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
    for ontology_id in ontology_ids:
        ontology = catalog.ontologies[ontology_id]
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
                        "description": "다른 Ontology에서 정의된 Object Type",
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
    if len(ontology_ids) == 1:
        ontology = catalog.ontologies[ontology_ids[0]]
        metadata = {"id": ontology.id, "name": ontology.name, "description": ontology.description}
    else:
        metadata = {
            "id": "all",
            "name": "전체 Ontology",
            "description": "모든 Ontology Object Type과 Ontology 간 Link를 통합해 표시한다.",
        }
    return {"ontology": metadata, "nodes": list(nodes.values()), "edges": edges}


def _qualified_object_id(ontology_id: str, reference: str) -> str:
    return reference if "." in reference else f"{ontology_id}.{reference}"
