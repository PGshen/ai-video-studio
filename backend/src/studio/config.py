"""后端配置。

`Settings` 从环境变量（前缀 `STUDIO_`）和 `backend/.env` 读取配置。
模型 API key 不进入 `Settings` 字段：由模型配置（`model_profiles` 表）的
`api_key_env` 字段按名读取对应的环境变量，运行时按需查找。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

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
    openai_price_input: float | None = None
    """种子 `gpt` 的输入单价，美元 / 百万 token（`STUDIO_OPENAI_PRICE_INPUT`）；换模型
    （例如 OpenRouter 上单价与 gpt-5 不同的型号）时用它覆盖种子默认单价 $1.25，
    未设置时不变（G2，2026-09-28）。"""
    openai_price_output: float | None = None
    """种子 `gpt` 的输出单价，美元 / 百万 token（`STUDIO_OPENAI_PRICE_OUTPUT`）；
    未设置时不变（默认 $10）。"""
    web_mode: Literal["tools", "native"] = "tools"
    """联网方式（`STUDIO_WEB_MODE`，决策 D1）。`tools`（默认）：头脑风暴/选题阶段用自建的
    `web_search`/`fetch_url`（Tavily，带「URL 来源」限制）；`native`：用运行时原生的联网能力
    （Claude WebSearch/WebFetch、OpenAI 托管 `WebSearchTool`），没有 URL 来源保护，不需要
    Tavily key。两种模式互斥。"""
    manim_timeout_seconds: float = 600.0
    """manim 全画质渲染子进程的超时时间（`STUDIO_MANIM_TIMEOUT_SECONDS`）。"""

    @field_validator(
        "anthropic_base_url",
        "openai_base_url",
        "openai_model",
        "openai_price_input",
        "openai_price_output",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("web_mode", mode="before")
    @classmethod
    def _blank_web_mode_is_default(cls, value: object) -> object:
        # `.env` 里写了 `STUDIO_WEB_MODE=` 但没填值：当作没设置，用默认的 tools。
        if isinstance(value, str) and not value.strip():
            return "tools"
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


def repo_root() -> Path:
    """仓库根目录（`<repo_root>/backend/src/studio/config.py` 向上 3 层）。

    公开只读访问点：`_REPO_ROOT` 等常量是模块私有实现细节，其它模块和测试
    不应直接 import（TD-3）。
    """
    return _REPO_ROOT


if __name__ == "__main__":
    # `dev.sh` 用这一行的输出取真正生效的绑定地址（TD-2）：Settings.host/port
    # 此前只是声明字段，没人读它们，改 STUDIO_PORT 不会影响 dev.sh 里写死的端口。
    _settings = Settings()
    print(f"{_settings.host} {_settings.port}")
