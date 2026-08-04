from teoria.registry.diagnostics import Diagnostic
from teoria.registry.loader import RegistryCatalog


def validate_references(catalog: RegistryCatalog, diagnostics: list[Diagnostic]) -> None:
    project_root = catalog.root.parent.resolve()
    for source_id, reference in catalog.references.items():
        metadata_path = catalog.reference_paths[source_id]
        for index, item in enumerate(reference.files):
            if not (metadata_path.parent / item.path).is_file():
                diagnostics.append(Diagnostic("reference_file_not_found", f"reference file '{item.path}' does not exist", metadata_path, location=f"files.{index}.path"))

    for source_id, source_registry in catalog.sources.items():
        if source_registry.source.type != "api":
            continue
        source_document = source_registry.source.specification.source_document
        reference = catalog.references.get(source_id)
        if source_document and reference is None:
            diagnostics.append(Diagnostic("missing_source_reference", f"source '{source_id}' declares source_document but has no provider reference metadata", catalog.source_paths[source_id], location="source.specification.source_document"))
            continue
        if reference is None:
            continue
        metadata_path = catalog.reference_paths[source_id]
        if reference.target != "source":
            diagnostics.append(Diagnostic("reference_target_mismatch", f"reference for source '{source_id}' must use target: source", metadata_path, location="target"))
        if reference.status == "draft":
            diagnostics.append(Diagnostic("draft_reference_for_registered_source", f"source '{source_id}' is registered but its provider reference is still draft", metadata_path, location="status"))
            continue
        registry_path = (project_root / reference.registry).resolve()
        expected_registry_path = catalog.source_paths[source_id].resolve()
        if registry_path != expected_registry_path:
            diagnostics.append(Diagnostic("reference_registry_mismatch", f"reference registry points to '{reference.registry}', expected '{catalog.source_paths[source_id]}'", metadata_path, location="registry"))
        file_names = {item.path for item in reference.files}
        if source_document and source_document not in file_names:
            diagnostics.append(Diagnostic("source_document_mismatch", f"source_document '{source_document}' is not listed in provider reference files", catalog.source_paths[source_id], location="source.specification.source_document"))

    for source_id, reference in catalog.references.items():
        if reference.status == "active" and source_id not in catalog.sources:
            diagnostics.append(Diagnostic("unknown_reference_target", f"provider reference points to unknown source '{reference.source}'", catalog.reference_paths[source_id], location="source"))
