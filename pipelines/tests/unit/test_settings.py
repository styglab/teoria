from pathlib import Path

from teoria_pipelines.settings import bootstrap_pipeline_settings


def test_pipeline_settings_use_pipeline_prefix(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / "pipeline.env"
    env_file.write_text(
        "TEORIA_PIPELINE_SOURCE_TIMEOUT_SECONDS=8\n"
        "TEORIA_PIPELINE_SOURCE_MAX_ATTEMPTS=2\n"
        "TEORIA_SOURCE_TIMEOUT_SECONDS=99\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TEORIA_ENV_FILE", str(env_file))
    monkeypatch.delenv("TEORIA_PIPELINE_SOURCE_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("TEORIA_PIPELINE_SOURCE_MAX_ATTEMPTS", raising=False)

    settings = bootstrap_pipeline_settings(cwd=tmp_path)

    assert settings.source_timeout_seconds == 8
    assert settings.source_max_attempts == 2
