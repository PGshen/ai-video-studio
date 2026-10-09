from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_settings_default_data_dir_is_repo_root_data() -> None:
    from studio.config import Settings, repo_root

    settings = Settings()

    assert settings.data_dir == (repo_root() / "data").resolve()
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
    from studio.config import Settings, WorkspaceInsideSourceError, repo_root

    backend_src_dir = repo_root() / "backend" / "src"
    with pytest.raises(WorkspaceInsideSourceError):
        Settings(data_dir=backend_src_dir / "data")


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


def test_openai_price_settings_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from studio.config import Settings

    monkeypatch.setenv("STUDIO_OPENAI_PRICE_INPUT", "0.10")
    monkeypatch.setenv("STUDIO_OPENAI_PRICE_OUTPUT", "0.50")

    settings = Settings()

    assert settings.openai_price_input == 0.10
    assert settings.openai_price_output == 0.50


def test_openai_price_settings_empty_string_means_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    from studio.config import Settings

    monkeypatch.setenv("STUDIO_OPENAI_PRICE_INPUT", "  ")
    monkeypatch.setenv("STUDIO_OPENAI_PRICE_OUTPUT", "  ")

    settings = Settings()

    assert settings.openai_price_input is None
    assert settings.openai_price_output is None


def test_main_prints_host_and_port(tmp_path: Path) -> None:
    """TD-2：`dev.sh` 靠 `python -m studio.config` 的 stdout 拿绑定地址，
    改端口后 uvicorn 必须真的换端口，而不是脚本里写死的 8000。"""
    env = dict(os.environ)
    env["STUDIO_PORT"] = "9123"
    env["STUDIO_HOST"] = "0.0.0.0"
    env["STUDIO_DATA_DIR"] = str(tmp_path / "data")

    result = subprocess.run(
        [sys.executable, "-m", "studio.config"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )

    assert result.stdout.strip() == "0.0.0.0 9123"


def test_web_mode_defaults_to_tools_and_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from studio.config import Settings

    assert Settings().web_mode == "tools"
    monkeypatch.setenv("STUDIO_WEB_MODE", "native")
    assert Settings().web_mode == "native"


def test_web_mode_rejects_unknown_value(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import ValidationError

    from studio.config import Settings

    monkeypatch.setenv("STUDIO_WEB_MODE", "both")
    with pytest.raises(ValidationError):
        Settings()


def test_blank_web_mode_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from studio.config import Settings

    monkeypatch.setenv("STUDIO_WEB_MODE", "  ")
    assert Settings().web_mode == "tools"


def test_allow_unsandboxed_exec_defaults_to_false_and_reads_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from studio.config import Settings

    monkeypatch.delenv("STUDIO_ALLOW_UNSANDBOXED_EXEC", raising=False)
    assert Settings().allow_unsandboxed_exec is False
    monkeypatch.setenv("STUDIO_ALLOW_UNSANDBOXED_EXEC", "true")
    assert Settings().allow_unsandboxed_exec is True
    monkeypatch.setenv("STUDIO_ALLOW_UNSANDBOXED_EXEC", "")
    assert Settings().allow_unsandboxed_exec is False
