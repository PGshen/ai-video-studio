"""`model_profiles` 仓储：种子数据与只读查询（设计 §3.1、计划决策记录）。

种子的模型名与单价在 T15（2026-09-28）按各家官方页面核实：Claude 模型表
（`claude-sonnet-5`，$2/$10）、OpenAI 定价页（`gpt-5`，$1.25/$10）、DeepSeek 定价页
（`deepseek-chat` 已于 2026-07-24 停用，现名 `deepseek-flash`，按高峰价 $0.30/$1.20
计，宁可高估）。种子只插入不存在的配置，已有数据库里的旧行不会被更新——
例外是由配置（`Settings`）决定的网关字段（F2，2026-09-28）：`claude-sonnet` 的
`base_url` ← `anthropic_base_url`，`gpt` 的 `base_url` ← `openai_base_url`、`model` ←
`openai_model`。配置值非空时，新行用它插入，已有行在值不同时只更新这两个字段；
配置值为空时新行用默认值（无 `base_url`、`gpt-5`），已有行不动。OpenRouter 上
`openai/gpt-5` 的单价与 OpenAI 官方相同（$1.25/$10，OpenRouter `/api/v1/models`，
2026-09-28），单价不随网关变化。

`gpt` 的单价同样可由配置覆盖（`openai_price_input`/`openai_price_output`，G2，
2026-09-28）：换模型时（例如换成单价不同的 OpenRouter 型号）种子默认单价
（$1.25/$10，对应 `gpt-5`）会偏高，用同样的受控更新规则——配置值非空且与已有
行不同时才更新，配置值为空不清空已有值。换模型的背景见
`docs/references/openai-agents-sdk.md`（`apply_patch` 与 `gpt-5-2025-08-07` 不兼容
的核实记录）和计划「决策记录」。

`claude-login` 的 `api_key_env` 为空表示使用本机已登录的 Claude Code 订阅账号，
不新增字段，复用设计已有的 `api_key_env`。

`deepseek` 种子的 `supports_vision` 为 `False`（T15 误设为 `True`，2026-09-28 冒烟
run2/run3 实测纠正：`deepseek/deepseek-flash` 不支持图片输入，见
docs/references/openai-agents-sdk.md R2 结论）。种子只插入不存在的配置，已有库里
误设为 `True` 的 `deepseek` 行不会被这次改动自动更新（不扩展受控更新规则覆盖范围）；
需要手动 `UPDATE model_profiles SET supports_vision = 0 WHERE name = 'deepseek'`
或删库重建（见 docs/runbooks/dev-setup.md「已知限制」）。

M5 T6（2026-09-30）：模型配置可以在界面上增改删。名称、`provider`、`runtime` 建好后不可改
（会话按它们判断能否换模型）；内置配置（种子名和 `fake`）可以编辑但不能删除，否则下次启动
种子会把它加回来；被会话或阶段默认模型引用的配置不能删除。环境变量网关覆盖（上面说的
`base_url`/`model`/单价）仍然优先——`env_override_fields` 告诉界面哪些字段由环境变量决定。
校验是纯函数式的：先把改动合并成完整记录再整体检查，不合法时什么都不写。
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlsplit

from sqlalchemy import Engine, func, select

from studio.config import Settings
from studio.db.engine import session_scope
from studio.db.models import ModelProfile, Setting
from studio.db.models import Session as SessionRow


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


# Prices are USD per 1M tokens (checked 2026-09-28, see module docstring).
_SEED_PROFILES: list[dict[str, Any]] = [
    {
        "name": "claude-sonnet",
        "provider": "anthropic",
        "model": "claude-sonnet-5",
        "runtime": "claude",
        "api_key_env": "ANTHROPIC_API_KEY",
        "supports_vision": True,
        "price_input": 2.0,
        "price_output": 10.0,
    },
    {
        "name": "claude-login",
        "provider": "anthropic",
        "model": "claude-sonnet-5",
        "runtime": "claude",
        "api_key_env": None,
        "supports_vision": True,
        "price_input": 2.0,
        "price_output": 10.0,
    },
    {
        "name": "gpt",
        "provider": "openai",
        "model": "gpt-5",
        "runtime": "openai",
        "api_key_env": "OPENAI_API_KEY",
        "supports_vision": True,
        "price_input": 1.25,
        "price_output": 10.0,
    },
    {
        "name": "deepseek",
        "provider": "litellm",
        "model": "deepseek/deepseek-flash",
        "runtime": "openai",
        "api_key_env": "DEEPSEEK_API_KEY",
        "supports_vision": False,
        "price_input": 0.30,
        "price_output": 1.20,
    },
]

_FAKE_PROFILE: dict[str, Any] = {
    "name": "fake",
    "provider": "fake",
    "model": "fake",
    "runtime": "fake",
    "api_key_env": None,
}


def _gateway_overrides(settings: Settings | None) -> dict[str, dict[str, Any]]:
    """按种子 `name` 给出由配置决定、且配置值非空的字段（网关地址/模型/单价）。"""
    if settings is None:
        return {}
    candidates: dict[str, dict[str, Any]] = {
        "claude-sonnet": {"base_url": settings.anthropic_base_url},
        "gpt": {
            "base_url": settings.openai_base_url,
            "model": settings.openai_model,
            "price_input": settings.openai_price_input,
            "price_output": settings.openai_price_output,
        },
    }
    return {
        name: {field: value for field, value in fields.items() if value is not None}
        for name, fields in candidates.items()
    }


def seed_model_profiles(
    engine: Engine, *, enable_fake_runtime: bool, settings: Settings | None = None
) -> None:
    """插入种子模型配置；按 `name` 判断是否已存在，已存在则跳过（幂等）。

    `settings` 给出网关字段（见模块说明）：非空时用于新行，并更新已有行的这些字段。
    """
    specs = [_FAKE_PROFILE, *_SEED_PROFILES] if enable_fake_runtime else list(_SEED_PROFILES)
    overrides = _gateway_overrides(settings)

    with session_scope(engine) as session:
        existing = {row.name: row for row in session.scalars(select(ModelProfile))}
        for spec in specs:
            fields = overrides.get(spec["name"], {})
            row = existing.get(spec["name"])
            if row is None:
                session.add(ModelProfile(**{**spec, **fields}))
                continue
            for field, value in fields.items():
                if getattr(row, field) != value:
                    setattr(row, field, value)


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


# ---- M5 T6：增改删 ---------------------------------------------------------

USER_RUNTIMES: Final = ("claude", "openai")
"""界面里可以新建的运行时（`fake` 只用于测试，不能新建）。"""
_LOGIN_RUNTIMES: Final = ("claude", "fake")
"""`api_key_env` 可以为空的运行时：claude 用本机登录，fake 不需要 key。"""
BUILTIN_NAMES: Final = frozenset({str(spec["name"]) for spec in _SEED_PROFILES} | {"fake"})
_NAME = re.compile(r"^[\w.\-]{1,50}$")
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_EDITABLE_FIELDS: Final = (
    "model",
    "base_url",
    "api_key_env",
    "supports_vision",
    "price_input",
    "price_output",
    "max_cost_per_turn",
    "max_steps_per_turn",
)
_IMMUTABLE_FIELDS: Final = ("name", "provider", "runtime")


class ProfileValidationError(ValueError):
    """字段不合法（API 映射为 422）；`errors` 逐条列出问题。"""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("；".join(errors))
        self.errors = errors


class ProfileNotFoundError(LookupError):
    pass


class DuplicateProfileError(RuntimeError):
    """名称已被占用（API 映射为 409）。"""


class BuiltinProfileError(RuntimeError):
    """内置配置不能删除（API 映射为 409）。"""


class ProfileInUseError(RuntimeError):
    """配置正被会话或阶段默认模型引用，不能删除（API 映射为 409）。"""

    def __init__(self, name: str, session_count: int, stages: list[str]) -> None:
        reasons = []
        if session_count:
            reasons.append(f"被 {session_count} 个会话使用")
        if stages:
            reasons.append(f"是 {'、'.join(stages)} 阶段的默认模型")
        super().__init__(f"配置 {name} {'，'.join(reasons)}，不能删除")
        self.session_count = session_count
        self.stages = stages


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _validate_profile(
    fields: Mapping[str, Any], *, check_identity: bool, check_base_url: bool = True
) -> list[str]:
    """检查一条完整记录；`check_identity` 为假时不检查 `name`/`provider`/`runtime`
    （更新时它们不可改）；`check_base_url` 为假时不检查 `base_url`（更新时没改它：
    环境变量灌进库里的地址可能带账号密码，不能因此拒绝对其他字段的修改）。"""
    errors: list[str] = []
    runtime = fields["runtime"]
    if check_identity:
        if not isinstance(fields["name"], str) or _NAME.match(fields["name"]) is None:
            errors.append("名称只允许字母、数字、下划线、点和连字符，1–50 个字符")
        if not isinstance(fields["provider"], str) or not fields["provider"].strip():
            errors.append("provider 不能为空")
        if runtime not in USER_RUNTIMES:
            errors.append(f"运行时必须是 {' / '.join(USER_RUNTIMES)}")
    if not isinstance(fields["model"], str) or not fields["model"].strip():
        errors.append("模型名不能为空")
    base_url = fields["base_url"]
    if check_base_url and base_url is not None:
        parts = urlsplit(base_url) if isinstance(base_url, str) else None
        if parts is None or parts.scheme not in ("http", "https") or not parts.netloc:
            errors.append("base_url 必须是 http(s) 地址")
        elif parts.username or parts.password:
            errors.append("base_url 不能包含账号密码（密钥请放在环境变量里）")
    key_env = fields["api_key_env"]
    if key_env is None:
        if runtime not in _LOGIN_RUNTIMES:
            errors.append("只有 claude 运行时可以不填 API key 环境变量（使用本机登录）")
    elif not isinstance(key_env, str) or _ENV_NAME.match(key_env) is None:
        errors.append("api_key_env 必须是环境变量的名字（大写字母、数字、下划线），不是 key 本身")
    if not isinstance(fields["supports_vision"], bool):
        errors.append("supports_vision 必须是布尔值")
    for key in ("price_input", "price_output"):
        value = fields[key]
        if value is not None and (not _is_number(value) or value < 0):
            errors.append(f"单价（{key}）必须是非负的有限数字，或留空")
    cost = fields["max_cost_per_turn"]
    if cost is not None and (not _is_number(cost) or cost < 0):
        errors.append("单轮成本上限必须是非负的有限数字，或留空表示不限")
    steps = fields["max_steps_per_turn"]
    if steps is not None and (isinstance(steps, bool) or not isinstance(steps, int) or steps < 1):
        errors.append("单轮步数上限必须是正整数，或留空表示不限")
    return errors


def _row_fields(row: ModelProfile) -> dict[str, Any]:
    return {
        "name": row.name,
        "provider": row.provider,
        "model": row.model,
        "runtime": row.runtime,
        "base_url": row.base_url,
        "api_key_env": row.api_key_env,
        "supports_vision": row.supports_vision,
        "price_input": row.price_input,
        "price_output": row.price_output,
        "max_cost_per_turn": row.max_cost_per_turn,
        "max_steps_per_turn": row.max_steps_per_turn,
    }


def create_model_profile(
    engine: Engine,
    *,
    name: str,
    provider: str,
    model: str,
    runtime: str,
    base_url: str | None,
    api_key_env: str | None,
    supports_vision: bool,
    price_input: float | None,
    price_output: float | None,
    max_cost_per_turn: float | None,
    max_steps_per_turn: int | None,
) -> ModelProfileValue:
    """新建模型配置；不合法抛 `ProfileValidationError`（一次列出全部问题），名称重复抛
    `DuplicateProfileError`。"""
    fields: dict[str, Any] = {
        "name": name,
        "provider": provider,
        "model": model,
        "runtime": runtime,
        "base_url": base_url,
        "api_key_env": api_key_env,
        "supports_vision": supports_vision,
        "price_input": price_input,
        "price_output": price_output,
        "max_cost_per_turn": max_cost_per_turn,
        "max_steps_per_turn": max_steps_per_turn,
    }
    errors = _validate_profile(fields, check_identity=True)
    if errors:
        raise ProfileValidationError(errors)
    with session_scope(engine) as db:
        if db.scalars(select(ModelProfile).where(ModelProfile.name == name)).first() is not None:
            raise DuplicateProfileError(f"已有同名的模型配置：{name}")
        row = ModelProfile(**{**fields, "provider": provider.strip(), "model": model.strip()})
        db.add(row)
        db.flush()
        return _to_value(row)


def update_model_profile(
    engine: Engine, profile_id: str, patch: Mapping[str, Any]
) -> ModelProfileValue:
    """按补丁改字段（值为 `None` 表示清空可空字段）；`name`/`provider`/`runtime` 不可改。
    校验的是合并后的完整记录，不合法时什么都不写。"""
    errors = [
        f"不能修改 {key}" if key in _IMMUTABLE_FIELDS or key == "id" else f"未知字段 {key}"
        for key in patch
        if key not in _EDITABLE_FIELDS
    ]
    if errors:
        raise ProfileValidationError(errors)
    with session_scope(engine) as db:
        row = db.get(ModelProfile, profile_id)
        if row is None:
            raise ProfileNotFoundError(profile_id)
        merged = {**_row_fields(row), **patch}
        errors = _validate_profile(merged, check_identity=False, check_base_url="base_url" in patch)
        if errors:
            raise ProfileValidationError(errors)
        for key in patch:
            value = merged[key]
            setattr(row, key, value.strip() if key == "model" else value)
        db.flush()
        return _to_value(row)


def delete_model_profile(engine: Engine, profile_id: str) -> None:
    """删除自定义配置。内置配置抛 `BuiltinProfileError`；被会话或阶段默认模型引用时抛
    `ProfileInUseError`（带引用数量），都不删。"""
    with session_scope(engine) as db:
        row = db.get(ModelProfile, profile_id)
        if row is None:
            raise ProfileNotFoundError(profile_id)
        if row.name in BUILTIN_NAMES:
            raise BuiltinProfileError(f"内置配置 {row.name} 不能删除（可以编辑）")
        sessions = db.scalar(
            select(func.count())
            .select_from(SessionRow)
            .where(SessionRow.model_profile_id == row.id)
        )
        defaults = db.get(Setting, "stage_default_profile")
        stages = [
            stage
            for stage, pid in ((defaults.value if defaults else None) or {}).items()
            if pid == row.id
        ]
        if sessions or stages:
            raise ProfileInUseError(row.name, int(sessions or 0), stages)
        db.delete(row)


def env_override_fields(profile_name: str, settings: Settings | None) -> list[str]:
    """这条配置里由环境变量（`STUDIO_*`）决定的字段：启动时会覆盖库里的值，所以界面不让改。"""
    return list(_gateway_overrides(settings).get(profile_name, {}))
