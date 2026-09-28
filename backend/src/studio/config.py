"""后端配置。

`Settings` 从环境变量（前缀 `STUDIO_`）和 `backend/.env` 读取配置。
模型 API key 不进入 `Settings` 字段：由模型配置（`model_profiles` 表）的
`api_key_env` 字段按名读取对应的环境变量，运行时按需查找。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 本文件路径：<repo_root>/backend/src/studio/config.py
_CONFIG_FILE = Path(__file__).resolve()
_BACKEND_SRC_DIR = _CONFIG_FILE.parents[1]  # <repo_root>/backend/src
_BACKEND_DIR = _CONFIG_FILE.parents[2]  # <repo_root>/backend
_REPO_ROOT = _CONFIG_FILE.parents[3]  # <repo_root>

_DEFAULT_DATA_DIR = _REPO_ROOT / "data"
_ENV_FILE = _BACKEND_DIR / ".env"


class WorkspaceInsideSourceError(RuntimeError):
    """`data_dir` 解析后落在 `backend/src` 之内。

    工作区数据不能和后端源码混在一起：uvicorn 的 `--reload-dir` 只监听
    `backend/src`，如果工作区落在里面，agent 改工作区文件会触发开发服务器
    重启（见 AGENTS.md 红线）。
    """


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="STUDIO_",
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Field(default=_DEFAULT_DATA_DIR)
    host: str = "127.0.0.1"
    port: int = 8000
    max_concurrent_turns: int = 2
    allowed_hosts: list[str] = Field(default_factory=lambda: ["127.0.0.1", "localhost"])
    """`TrustedHostMiddleware` 放行的 Host（不含端口）。防 DNS rebinding：恶意网页把
    自己的域名解析到 127.0.0.1 后，浏览器发来的 Host 仍是那个域名，会被拒绝（400）。"""
    enable_fake_runtime: bool = False
    fake_delay_seconds: float = Field(default=0, ge=0)
    """Fake 运行时默认脚本在回显和写文件之间睡的秒数（`STUDIO_FAKE_DELAY_SECONDS`），
    用于手动验证"运行中"状态和重启中断；默认 0。"""
    openai_history_turns: int = 20
    """OpenAI 运行时发给模型的会话历史只保留最近这么多轮（设计 §4.1“保留最近 N 轮”）。"""
    anthropic_base_url: str | None = None
    """Claude API key 模式（种子 `claude-sonnet`）走的网关地址（`STUDIO_ANTHROPIC_BASE_URL`）。
    由 `seed_model_profiles` 写进模型配置的 `base_url`；登录模式（`claude-login`）不受影响。"""
    openai_base_url: str | None = None
    """OpenAI 运行时（种子 `gpt`）的 base_url（`STUDIO_OPENAI_BASE_URL`），例如 OpenRouter
    `https://openrouter.ai/api/v1`；非 `api.openai.com` 时不提供原生 Shell，见 openai_runtime。"""
    openai_model: str | None = None
    """种子 `gpt` 的模型名（`STUDIO_OPENAI_MODEL`），例如 OpenRouter 上的 `openai/gpt-5`；
    未设置时用种子默认值 `gpt-5`。"""

    @field_validator("anthropic_base_url", "openai_base_url", "openai_model", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("data_dir")
    @classmethod
    def _resolve_and_validate_data_dir(cls, value: Path) -> Path:
        resolved = value.expanduser().resolve()
        if resolved == _BACKEND_SRC_DIR or _BACKEND_SRC_DIR in resolved.parents:
            raise WorkspaceInsideSourceError(
                f"data_dir 解析后落在 backend/src 之下（{resolved}），"
                "这会被 uvicorn --reload 监听到；请指向 backend/src 之外的目录。"
            )
        return resolved


@lru_cache
def get_settings() -> Settings:
    return Settings()
