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
    enable_fake_runtime: bool = False
    openai_history_turns: int = 20
    """OpenAI 运行时发给模型的会话历史只保留最近这么多轮（设计 §4.1“保留最近 N 轮”）。"""

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
