from pathlib import Path

from teoria.settings import bootstrap_settings


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


def test_empty_optional_goods_view_environment_does_not_enable_a_runtime_reader():
    from teoria.settings import Settings
    settings = Settings(goods_runtime_view_path="", goods_runtime_view_sha256="")
    assert settings.goods_runtime_view_path is None
    assert settings.goods_runtime_view_sha256 is None
