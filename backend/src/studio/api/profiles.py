"""`/api/model-profiles`（任务简报 T7）：只读列表，不返回 key，只返回是否已配置。

`api_key_env` 为空表示该模型配置使用本机登录（决策记录 2026-09-27），不需要
任何环境变量，视为"已配置"；否则按环境变量名查询 `os.environ`。
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends
from sqlalchemy import Engine

from studio.api.deps import get_engine
from studio.api.schemas import ModelProfileOut
from studio.db.repo.profiles import ModelProfileValue, list_model_profiles

router = APIRouter(prefix="/api", tags=["model-profiles"])


def key_configured(value: ModelProfileValue) -> bool:
    if value.api_key_env is None:
        return True
    return bool(os.environ.get(value.api_key_env))


def _to_out(value: ModelProfileValue) -> ModelProfileOut:
    return ModelProfileOut(
        id=value.id,
        name=value.name,
        provider=value.provider,
        model=value.model,
        runtime=value.runtime,
        supports_vision=value.supports_vision,
        price_input=value.price_input,
        price_output=value.price_output,
        max_cost_per_turn=value.max_cost_per_turn,
        max_steps_per_turn=value.max_steps_per_turn,
        key_configured=key_configured(value),
    )


@router.get("/model-profiles", response_model=list[ModelProfileOut])
def list_model_profiles_endpoint(engine: Engine = Depends(get_engine)) -> list[ModelProfileOut]:
    return [_to_out(p) for p in list_model_profiles(engine)]
