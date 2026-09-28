from __future__ import annotations

from pathlib import Path

import pytest


def test_settings_default_data_dir_is_repo_root_data() -> None:
    from studio.config import _REPO_ROOT, Settings

    settings = Settings()

    assert settings.data_dir == (_REPO_ROOT / "data").resolve()
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.max_concurrent_turns == 2
    assert settings.enable_fake_runtime is False


def test_settings_data_dir_overridable_via_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from studio.config import Settings

    custom_dir = tmp_path / "custom-data"
    monkeypatch.setenv("STUDIO_DATA_DIR", str(custom_dir))

    settings = Settings()

    assert settings.data_dir == custom_dir.resolve()


def test_settings_rejects_data_dir_inside_backend_src() -> None:
    from studio.config import _BACKEND_SRC_DIR, Settings, WorkspaceInsideSourceError

    with pytest.raises(WorkspaceInsideSourceError):
        Settings(data_dir=_BACKEND_SRC_DIR / "data")


def test_get_settings_returns_cached_singleton() -> None:
    from studio.config import get_settings

    first = get_settings()
    second = get_settings()

    assert first is second


def test_gateway_settings_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from studio.config import Settings

    monkeypatch.setenv("STUDIO_ANTHROPIC_BASE_URL", "https://anthropic-gw.example")
    monkeypatch.setenv("STUDIO_OPENAI_BASE_URL", "https://openrouter.example/api/v1")
    monkeypatch.setenv("STUDIO_OPENAI_MODEL", "openai/gpt-5")

    settings = Settings()

    assert settings.anthropic_base_url == "https://anthropic-gw.example"
    assert settings.openai_base_url == "https://openrouter.example/api/v1"
    assert settings.openai_model == "openai/gpt-5"


def test_gateway_settings_empty_string_means_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    from studio.config import Settings

    for name in ("STUDIO_ANTHROPIC_BASE_URL", "STUDIO_OPENAI_BASE_URL", "STUDIO_OPENAI_MODEL"):
        monkeypatch.setenv(name, "  ")

    settings = Settings()

    assert settings.anthropic_base_url is None
    assert settings.openai_base_url is None
    assert settings.openai_model is None
