"""`/api/model-profiles`：列表与增改删（任务简报 T7；计划 M5 T6）。

永远不返回 key 的值，只返回 `key_configured`；返回环境变量的**名字**（`api_key_env`，界面要
编辑它）和 `base_url`（账号密码打码，写入时也不允许带账号密码）。`api_key_env` 为空表示该配置
使用本机登录，不需要任何环境变量，视为"已配置"；否则按环境变量名查询 `os.environ`。

环境变量网关覆盖（`STUDIO_ANTHROPIC_BASE_URL` 等）仍然优先：`env_override` 列出被环境变量决定
的字段，界面里不让改（改了下次启动也会被覆盖）。
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import Engine

from studio.agent.runtime import RuntimeFactory
from studio.api.deps import get_engine, get_runtime_factory, get_settings
from studio.api.schemas import ModelProfileCreate, ModelProfileOut, ModelProfilePatch
from studio.config import Settings
from studio.db.repo import profiles as repo
from studio.db.repo.profiles import ModelProfileValue

router = APIRouter(prefix="/api", tags=["model-profiles"])


def key_configured(value: ModelProfileValue) -> bool:
    if value.api_key_env is None:
        return True
    return bool(os.environ.get(value.api_key_env))


def _mask_base_url(url: str | None) -> str | None:
    """账号密码打码：`https://user:pw@host/v1` → `https://***@host/v1`。"""
    if url is None:
        return None
    parts = urlsplit(url)
    if not (parts.username or parts.password):
        return url
    host = parts.hostname or ""
    netloc = f"***@{host}" + (f":{parts.port}" if parts.port else "")
    return parts._replace(netloc=netloc).geturl()


def _to_out(value: ModelProfileValue, settings: Settings) -> ModelProfileOut:
    return ModelProfileOut(
        id=value.id,
        name=value.name,
        provider=value.provider,
        model=value.model,
        runtime=value.runtime,
        base_url=_mask_base_url(value.base_url),
        api_key_env=value.api_key_env,
        supports_vision=value.supports_vision,
        price_input=value.price_input,
        price_output=value.price_output,
        max_cost_per_turn=value.max_cost_per_turn,
        max_steps_per_turn=value.max_steps_per_turn,
        key_configured=key_configured(value),
        builtin=value.name in repo.BUILTIN_NAMES,
        env_override=repo.env_override_fields(value.name, settings),
    )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, repo.ProfileNotFoundError):
        return HTTPException(status_code=404, detail=f"模型配置不存在：{exc}")
    if isinstance(exc, repo.ProfileValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=409, detail=str(exc))


@router.get("/model-profiles", response_model=list[ModelProfileOut])
def list_model_profiles_endpoint(
    engine: Engine = Depends(get_engine), settings: Settings = Depends(get_settings)
) -> list[ModelProfileOut]:
    return [_to_out(p, settings) for p in repo.list_model_profiles(engine)]


@router.post("/model-profiles", response_model=ModelProfileOut, status_code=201)
def create_model_profile_endpoint(
    body: ModelProfileCreate,
    engine: Engine = Depends(get_engine),
    runtimes: RuntimeFactory = Depends(get_runtime_factory),
    settings: Settings = Depends(get_settings),
) -> ModelProfileOut:
    if body.runtime in repo.USER_RUNTIMES and not runtimes.has(body.runtime):
        raise HTTPException(status_code=422, detail=f"运行时未启用：{body.runtime}")
    try:
        value = repo.create_model_profile(engine, **body.model_dump())
    except (repo.ProfileValidationError, repo.DuplicateProfileError) as exc:
        raise _http_error(exc) from exc
    return _to_out(value, settings)


@router.patch("/model-profiles/{profile_id}", response_model=ModelProfileOut)
def update_model_profile_endpoint(
    profile_id: str,
    body: ModelProfilePatch,
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
) -> ModelProfileOut:
    patch = body.model_dump(exclude_unset=True)
    current = repo.get_model_profile_by_id(engine, profile_id)
    if current is None:
        raise _http_error(repo.ProfileNotFoundError(profile_id))
    locked = sorted(set(patch) & set(repo.env_override_fields(current.name, settings)))
    if locked:
        raise HTTPException(
            status_code=422,
            detail=(
                f"这些字段由环境变量决定，界面里不能改：{'、'.join(locked)}；"
                "请修改 backend/.env 里对应的 STUDIO_* 变量后重启（改了库里的值下次启动也会被覆盖）"
            ),
        )
    try:
        value = repo.update_model_profile(engine, profile_id, patch)
    except (repo.ProfileValidationError, repo.ProfileNotFoundError) as exc:
        raise _http_error(exc) from exc
    return _to_out(value, settings)


@router.delete("/model-profiles/{profile_id}", status_code=204)
def delete_model_profile_endpoint(
    profile_id: str, engine: Engine = Depends(get_engine)
) -> Response:
    try:
        repo.delete_model_profile(engine, profile_id)
    except (
        repo.ProfileNotFoundError,
        repo.BuiltinProfileError,
        repo.ProfileInUseError,
    ) as exc:
        raise _http_error(exc) from exc
    return Response(status_code=204)
