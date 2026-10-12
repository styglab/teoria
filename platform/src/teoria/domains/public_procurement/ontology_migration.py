from pathlib import Path


def applied_ontology_migration_manifest(registry_path: Path) -> Path:
    """Preserve the procurement migration report selected by the Admin API."""
    return (registry_path.parent / "ontology_migrations" / "applied"
            / "2026_10_bid_notice_stable_key_correction" / "ontology_v2.yaml")
