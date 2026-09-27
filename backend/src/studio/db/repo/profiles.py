"""`model_profiles` 仓储：种子数据与只读查询（设计 §3.1、计划决策记录）。

种子的模型名是临时值，等 T9/T10 核实各运行时的真实模型名后再更新（计划
「决策记录」2026-09-27）。`claude-login` 的 `api_key_env` 为空表示使用本机
已登录的 Claude Code 订阅账号，不新增字段，复用设计已有的 `api_key_env`。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, select

from studio.db.engine import session_scope
from studio.db.models import ModelProfile


@dataclass(frozen=True, slots=True)
class ModelProfileValue:
    """`model_profiles` 表一行的只读值对象。"""

    id: str
    name: str
    provider: str
    model: str
    runtime: str
    base_url: str | None
    api_key_env: str | None
    supports_vision: bool
    price_input: float | None
    """输入单价，美元 / 百万 token（OpenAIRuntime 据此计算成本，T10）。"""
    price_output: float | None
    """输出单价，美元 / 百万 token。"""
    max_cost_per_turn: float | None
    max_steps_per_turn: int | None


def _to_value(row: ModelProfile) -> ModelProfileValue:
    return ModelProfileValue(
        id=row.id,
        name=row.name,
        provider=row.provider,
        model=row.model,
        runtime=row.runtime,
        base_url=row.base_url,
        api_key_env=row.api_key_env,
        supports_vision=row.supports_vision,
        price_input=row.price_input,
        price_output=row.price_output,
        max_cost_per_turn=row.max_cost_per_turn,
        max_steps_per_turn=row.max_steps_per_turn,
    )


# 模型名为 T2 阶段的临时值，T9/T10 核实运行时行为后更新（计划决策记录）。
_SEED_PROFILES: list[dict[str, Any]] = [
    {
        "name": "claude-sonnet",
        "provider": "anthropic",
        "model": "claude-sonnet-5",
        "runtime": "claude",
        "api_key_env": "ANTHROPIC_API_KEY",
    },
    {
        "name": "claude-login",
        "provider": "anthropic",
        "model": "claude-sonnet-5",
        "runtime": "claude",
        "api_key_env": None,
    },
    {
        "name": "gpt",
        "provider": "openai",
        "model": "gpt-5",
        "runtime": "openai",
        "api_key_env": "OPENAI_API_KEY",
    },
    {
        "name": "deepseek",
        "provider": "litellm",
        "model": "deepseek/deepseek-chat",
        "runtime": "openai",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
]

_FAKE_PROFILE: dict[str, Any] = {
    "name": "fake",
    "provider": "fake",
    "model": "fake",
    "runtime": "fake",
    "api_key_env": None,
}


def seed_model_profiles(engine: Engine, *, enable_fake_runtime: bool) -> None:
    """插入种子模型配置；按 `name` 判断是否已存在，已存在则跳过（幂等）。"""
    specs = [_FAKE_PROFILE, *_SEED_PROFILES] if enable_fake_runtime else list(_SEED_PROFILES)

    with session_scope(engine) as session:
        existing_names = set(session.scalars(select(ModelProfile.name)))
        for spec in specs:
            if spec["name"] in existing_names:
                continue
            session.add(ModelProfile(**spec))


def list_model_profiles(engine: Engine) -> list[ModelProfileValue]:
    """按创建时间列出全部模型配置。"""
    with session_scope(engine) as session:
        rows = session.scalars(select(ModelProfile).order_by(ModelProfile.created_at)).all()
        return [_to_value(row) for row in rows]


def get_model_profile(engine: Engine, name: str) -> ModelProfileValue | None:
    """按 `name` 查询模型配置，不存在时返回 `None`。"""
    with session_scope(engine) as session:
        row = session.scalars(select(ModelProfile).where(ModelProfile.name == name)).one_or_none()
        return _to_value(row) if row is not None else None


def get_model_profile_by_id(engine: Engine, profile_id: str) -> ModelProfileValue | None:
    """按 id 查询模型配置（会话表存的是 `model_profile_id`），不存在时返回 `None`。"""
    with session_scope(engine) as session:
        row = session.get(ModelProfile, profile_id)
        return _to_value(row) if row is not None else None
