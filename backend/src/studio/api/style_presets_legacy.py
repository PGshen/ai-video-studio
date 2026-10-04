"""`/api/style-presets`：旧的数据库版风格库接口（style-library T4 删除，已被 `/api/styles` 取代）。

风格以 skill 形态的目录存放（入口 `STYLE.md` + `references/` + `exemplars/`），校验在
`db.repo.style_presets`。默认风格是 `settings.default_style_preset_id`，删除默认风格时清掉它。
创建项目时把所选风格复制进工作区（T3），之后与库脱钩，所以删除预设不影响已有项目。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import Engine

from studio.api.deps import get_engine
from studio.api.schemas import (
    StyleFileBody,
    StylePresetCreate,
    StylePresetOut,
    StylePresetPatch,
    StylePresetSummaryOut,
)
from studio.db.repo import style_presets as repo
from studio.db.repo.settings import get_all_settings, update_settings
from studio.db.repo.style_presets import StyleFile, StylePresetValue

router = APIRouter(prefix="/api", tags=["style-presets"])


def _files(files: list[StyleFileBody]) -> list[StyleFile]:
    return [StyleFile(name=f.name, text=f.text) for f in files]


def _summary(value: repo.StylePresetSummary, default_id: str | None) -> StylePresetSummaryOut:
    return StylePresetSummaryOut(
        id=value.id,
        name=value.name,
        category=value.category,
        description=value.description,
        reference_count=value.reference_count,
        exemplar_count=value.exemplar_count,
        is_default=value.id == default_id,
    )


def _out(value: StylePresetValue, default_id: str | None) -> StylePresetOut:
    return StylePresetOut(
        id=value.id,
        name=value.name,
        category=value.category,
        description=value.description,
        content=value.content,
        references=[StyleFileBody(name=f.name, text=f.text) for f in value.references],
        exemplars=[StyleFileBody(name=f.name, text=f.text) for f in value.exemplars],
        is_default=value.id == default_id,
        created_at=value.created_at,
    )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, repo.StylePresetNotFoundError):
        return HTTPException(status_code=404, detail=f"风格不存在：{exc}")
    if isinstance(exc, repo.StylePresetValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=409, detail=str(exc))


def _default_id(engine: Engine) -> str | None:
    return get_all_settings(engine).default_style_preset_id


@router.get("/style-presets", response_model=list[StylePresetSummaryOut])
def list_style_presets_endpoint(
    engine: Engine = Depends(get_engine),
) -> list[StylePresetSummaryOut]:
    default_id = _default_id(engine)
    return [_summary(v, default_id) for v in repo.list_style_preset_summaries(engine)]


@router.post("/style-presets", response_model=StylePresetOut, status_code=201)
def create_style_preset_endpoint(
    body: StylePresetCreate, engine: Engine = Depends(get_engine)
) -> StylePresetOut:
    try:
        value = repo.create_style_preset(
            engine,
            name=body.name,
            category=body.category,
            description=body.description,
            content=body.content,
            references=_files(body.references),
            exemplars=_files(body.exemplars),
        )
    except (repo.StylePresetValidationError, repo.DuplicateStylePresetError) as exc:
        raise _http_error(exc) from exc
    return _out(value, _default_id(engine))


@router.get("/style-presets/{preset_id}", response_model=StylePresetOut)
def get_style_preset_endpoint(
    preset_id: str, engine: Engine = Depends(get_engine)
) -> StylePresetOut:
    value = repo.get_style_preset(engine, preset_id)
    if value is None:
        raise _http_error(repo.StylePresetNotFoundError(preset_id))
    return _out(value, _default_id(engine))


@router.patch("/style-presets/{preset_id}", response_model=StylePresetOut)
def update_style_preset_endpoint(
    preset_id: str, body: StylePresetPatch, engine: Engine = Depends(get_engine)
) -> StylePresetOut:
    try:
        value = repo.update_style_preset(
            engine,
            preset_id,
            name=body.name,
            category=body.category,
            # 只有请求里真的带了 description 才改；带 null 表示清空。
            description=body.description if "description" in body.model_fields_set else repo.UNSET,
            content=body.content,
            references=_files(body.references) if body.references is not None else None,
            exemplars=_files(body.exemplars) if body.exemplars is not None else None,
        )
    except (
        repo.StylePresetNotFoundError,
        repo.StylePresetValidationError,
        repo.DuplicateStylePresetError,
    ) as exc:
        raise _http_error(exc) from exc
    return _out(value, _default_id(engine))


@router.delete("/style-presets/{preset_id}", status_code=204)
def delete_style_preset_endpoint(preset_id: str, engine: Engine = Depends(get_engine)) -> Response:
    try:
        repo.delete_style_preset(engine, preset_id)
    except repo.StylePresetNotFoundError as exc:
        raise _http_error(exc) from exc
    if _default_id(engine) == preset_id:
        update_settings(engine, {"default_style_preset_id": None})
    return Response(status_code=204)


@router.post("/style-presets/{preset_id}/duplicate", response_model=StylePresetOut, status_code=201)
def duplicate_style_preset_endpoint(
    preset_id: str, engine: Engine = Depends(get_engine)
) -> StylePresetOut:
    try:
        value = repo.duplicate_style_preset(engine, preset_id)
    except (
        repo.StylePresetNotFoundError,
        repo.StylePresetValidationError,
        repo.DuplicateStylePresetError,
    ) as exc:
        raise _http_error(exc) from exc
    return _out(value, _default_id(engine))
