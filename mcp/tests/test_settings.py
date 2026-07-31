from pathlib import Path

from teoria_mcp.settings import bootstrap_mcp_settings


def test_mcp_settings_use_mcp_prefix(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / "mcp.env"
    env_file.write_text(
        "TEORIA_MCP_RUNTIME_MODE=embedded\n"
        "TEORIA_MCP_EMBEDDED_REGISTRY_PATH=custom/registries\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TEORIA_ENV_FILE", str(env_file))
    monkeypatch.delenv("TEORIA_MCP_RUNTIME_MODE", raising=False)
    monkeypatch.delenv("TEORIA_MCP_EMBEDDED_REGISTRY_PATH", raising=False)
    monkeypatch.delenv("TEORIA_REGISTRY_PATH", raising=False)

    settings = bootstrap_mcp_settings(cwd=tmp_path)

    assert settings.runtime_mode == "embedded"
    assert settings.embedded_registry_path == Path("custom/registries")
