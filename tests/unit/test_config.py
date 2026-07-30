from pathlib import Path

from teoria.config import bootstrap_settings


def test_loads_explicit_env_file_and_validates_types(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / "local.env"
    env_file.write_text(
        "TEORIA_SOURCE_TIMEOUT_SECONDS=7.5\n"
        "TEORIA_SOURCE_MAX_ATTEMPTS=2\n"
        "TEORIA_SOURCE_MAX_PAGES=12\n"
        "TEORIA_CAPABILITY_TIMEOUT_SECONDS=45\n",
        encoding="utf-8",
    )
    names = [
        "TEORIA_SOURCE_TIMEOUT_SECONDS",
        "TEORIA_SOURCE_MAX_ATTEMPTS",
        "TEORIA_SOURCE_MAX_PAGES",
        "TEORIA_CAPABILITY_TIMEOUT_SECONDS",
    ]
    for name in names:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TEORIA_ENV_FILE", str(env_file))

    settings = bootstrap_settings(cwd=tmp_path)

    assert settings.source_timeout_seconds == 7.5
    assert settings.source_max_attempts == 2
    assert settings.source_max_pages == 12
    assert settings.capability_timeout_seconds == 45
    for name in names:
        monkeypatch.delenv(name, raising=False)


def test_supports_legacy_registry_variable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEORIA_ENVIRONMENT", "production")
    monkeypatch.setenv("TEORIA_REGISTRIES", "legacy-registries")
    monkeypatch.delenv("TEORIA_REGISTRY_PATH", raising=False)

    settings = bootstrap_settings(cwd=tmp_path)

    assert settings.registry_path == Path("legacy-registries")
