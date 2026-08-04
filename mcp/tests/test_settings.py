from teoria_mcp.settings import bootstrap_mcp_settings


def test_mcp_settings_require_remote_runtime(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / "mcp.env"
    env_file.write_text(
        "TEORIA_MCP_RUNTIME_MODE=remote\n"
        "TEORIA_MCP_RUNTIME_API_URL=http://runtime-api:8000\n"
        "TEORIA_MCP_RUNTIME_API_TOKEN=test-token\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TEORIA_ENV_FILE", str(env_file))
    for name in (
        "TEORIA_MCP_RUNTIME_MODE",
        "TEORIA_MCP_RUNTIME_API_URL",
        "TEORIA_MCP_RUNTIME_API_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = bootstrap_mcp_settings(cwd=tmp_path)

    assert settings.runtime_mode == "remote"
    assert settings.runtime_api_url == "http://runtime-api:8000"
    assert settings.runtime_api_token == "test-token"
