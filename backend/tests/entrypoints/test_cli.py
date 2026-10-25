from pathlib import Path
from unittest.mock import patch

import pytest
from teoria.entrypoints.cli import main
from teoria.settings import Settings

REGISTRIES = (Path(__file__).resolve().parents[3] / 'backend') / "registries"


def test_validate_command_executes_registry_validation_and_reports_counts(capsys):
    with patch("sys.argv", ["teoria", "validate", str(REGISTRIES)]):
        assert main() == 0
    assert "Validated" in capsys.readouterr().out


def test_ontology_command_without_database_fails_before_any_write(capsys):
    with (
        patch("teoria.entrypoints.cli.bootstrap_settings", return_value=Settings()),
        patch(
            "sys.argv",
            ["teoria", "apply-ontology-blueprint", "--manifest", "missing.yaml"],
        ),
    ):
        assert main() == 1
    assert "TEORIA_APP_DATABASE_URL is required" in capsys.readouterr().out


@pytest.mark.parametrize(
    "operation,manifest_name",
    [
        ("apply_ontology_blueprint", "OntologyBlueprint"),
        ("apply_ontology_extension", "OntologyExtensionManifest"),
    ],
)
async def test_ontology_commands_dispatch_to_authoring_operations(
    operation, manifest_name
):
    from argparse import Namespace
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from teoria.entrypoints.commands import ontology

    repository, manifest = object(), object()
    operation_mock = AsyncMock(return_value={"status": "draft"})
    with (
        patch.object(ontology, operation, operation_mock),
        patch.object(ontology, "OntologyAuthoringRepository", return_value=repository),
        patch.object(
            ontology, manifest_name, SimpleNamespace(load=Mock(return_value=manifest))
        ),
    ):
        handler = getattr(ontology, "run_" + operation)
        assert (
            await handler(
                Namespace(manifest=Path("reviewed.yaml"), actor="user:reviewer"),
                Settings(app_database_url="postgresql://synthetic"),
            )
            == 0
        )
    operation_mock.assert_called_once_with(repository, manifest, actor="user:reviewer")
