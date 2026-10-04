"""`/api/styles`：风格库（磁盘目录存储 + 草稿；ADR 0019，计划 style-library T3）。

- 正式版本在 `data/styles/<id>/`，列表、详情、复制、删除直接读写目录；
- 编辑走草稿 `data/style-drafts/<id>/`：打开草稿、读写草稿文件、保存（校验通过才覆盖正式版本）、
  放弃。`POST /api/styles` 新建的是只有草稿的风格，保存之前在列表里标记为 `is_new`（找得回来）；
- 默认风格是 `settings.default_style_preset_id`，删除默认风格时清掉它。

错误映射：404 风格或文件不存在，400 草稿文件路径不合法，422 内容不合法（detail 逐条列出），
409 名称重复。会写目录的端点都写成 `async def`：同一套风格有对话轮次运行时要在事件循环上拒绝
写入（计划 T9），检查与写入之间不能 `await`。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import Engine

from studio.api.deps import get_engine, get_settings
from studio.api.schemas import (
    DraftFileOut,
    DraftFileWrite,
    DraftStatusOut,
    StyleOut,
    StyleSummaryOut,
)
from studio.config import Settings
from studio.db.repo.settings import get_all_settings, update_settings
from studio.styles import store

router = APIRouter(prefix="/api", tags=["styles"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, store.StyleNotFoundError):
        return HTTPException(status_code=404, detail=f"风格不存在：{exc}")
    if isinstance(exc, store.StylePathError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, store.StyleValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=409, detail=str(exc))


_STORE_ERRORS = (
    store.StyleNotFoundError,
    store.StylePathError,
    store.StyleValidationError,
    store.DuplicateStyleNameError,
    store.StyleExistsError,
)


def _default_id(engine: Engine) -> str | None:
    return get_all_settings(engine).default_style_preset_id


def _out(detail: store.StyleDetail, default_id: str | None) -> StyleOut:
    return StyleOut(
        id=detail.id,
        name=detail.name,
        category=detail.category,
        description=detail.description,
        files=detail.files,
        is_default=detail.id == default_id,
        modified_at=detail.modified_at,
    )


def _draft_out(status: store.DraftStatus) -> DraftStatusOut:
    return DraftStatusOut(
        id=status.id, is_new=status.is_new, dirty=status.dirty, files=status.files
    )


@router.get("/styles", response_model=list[StyleSummaryOut])
async def list_styles_endpoint(
    engine: Engine = Depends(get_engine), settings: Settings = Depends(get_settings)
) -> list[StyleSummaryOut]:
    default_id = _default_id(engine)
    return [
        StyleSummaryOut(
            id=s.id,
            name=s.name,
            category=s.category,
            description=s.description,
            reference_count=s.reference_count,
            exemplar_count=s.exemplar_count,
            is_default=s.id == default_id,
            has_draft=s.has_draft,
            is_new=s.is_new,
            modified_at=s.modified_at,
        )
        for s in store.list_styles(settings.data_dir)
    ]


@router.post("/styles", response_model=DraftStatusOut, status_code=201)
async def create_style_endpoint(settings: Settings = Depends(get_settings)) -> DraftStatusOut:
    """新建风格：生成带模板的草稿，保存之前在列表里标记为 `is_new`。"""
    style_id = store.create_new_draft(settings.data_dir)
    return _draft_out(store.draft_status(settings.data_dir, style_id))


@router.get("/styles/{style_id}", response_model=StyleOut)
async def get_style_endpoint(
    style_id: str, engine: Engine = Depends(get_engine), settings: Settings = Depends(get_settings)
) -> StyleOut:
    try:
        detail = store.get_style(settings.data_dir, style_id)
    except _STORE_ERRORS as exc:
        raise _http_error(exc) from exc
    return _out(detail, _default_id(engine))


@router.delete("/styles/{style_id}", status_code=204)
async def delete_style_endpoint(
    style_id: str, engine: Engine = Depends(get_engine), settings: Settings = Depends(get_settings)
) -> Response:
    try:
        store.delete_style(settings.data_dir, style_id)
    except _STORE_ERRORS as exc:
        raise _http_error(exc) from exc
    if _default_id(engine) == style_id:
        update_settings(engine, {"default_style_preset_id": None})
    return Response(status_code=204)


@router.post("/styles/{style_id}/duplicate", response_model=StyleOut, status_code=201)
async def duplicate_style_endpoint(
    style_id: str, engine: Engine = Depends(get_engine), settings: Settings = Depends(get_settings)
) -> StyleOut:
    try:
        detail = store.duplicate_style(settings.data_dir, style_id)
    except _STORE_ERRORS as exc:
        raise _http_error(exc) from exc
    return _out(detail, _default_id(engine))


@router.post("/styles/{style_id}/draft", response_model=DraftStatusOut)
async def open_draft_endpoint(
    style_id: str, settings: Settings = Depends(get_settings)
) -> DraftStatusOut:
    """打开草稿：没有就从正式版本复制一份，已有则原样返回。"""
    try:
        return _draft_out(store.open_draft(settings.data_dir, style_id))
    except _STORE_ERRORS as exc:
        raise _http_error(exc) from exc


@router.delete("/styles/{style_id}/draft", status_code=204)
async def discard_draft_endpoint(
    style_id: str, settings: Settings = Depends(get_settings)
) -> Response:
    try:
        store.discard_draft(settings.data_dir, style_id)
    except _STORE_ERRORS as exc:
        raise _http_error(exc) from exc
    return Response(status_code=204)


@router.get("/styles/{style_id}/draft/files", response_model=DraftStatusOut)
async def draft_status_endpoint(
    style_id: str, settings: Settings = Depends(get_settings)
) -> DraftStatusOut:
    try:
        return _draft_out(store.draft_status(settings.data_dir, style_id))
    except _STORE_ERRORS as exc:
        raise _http_error(exc) from exc


@router.get("/styles/{style_id}/draft/files/{path:path}", response_model=DraftFileOut)
async def read_draft_file_endpoint(
    style_id: str, path: str, settings: Settings = Depends(get_settings)
) -> DraftFileOut:
    try:
        return DraftFileOut(content=store.read_draft_file(settings.data_dir, style_id, path))
    except _STORE_ERRORS as exc:
        raise _http_error(exc) from exc


@router.put("/styles/{style_id}/draft/files/{path:path}", response_model=DraftStatusOut)
async def write_draft_file_endpoint(
    style_id: str,
    path: str,
    body: DraftFileWrite,
    settings: Settings = Depends(get_settings),
) -> DraftStatusOut:
    try:
        store.write_draft_file(settings.data_dir, style_id, path, body.content)
        return _draft_out(store.draft_status(settings.data_dir, style_id))
    except _STORE_ERRORS as exc:
        raise _http_error(exc) from exc


@router.delete("/styles/{style_id}/draft/files/{path:path}", status_code=204)
async def delete_draft_file_endpoint(
    style_id: str, path: str, settings: Settings = Depends(get_settings)
) -> Response:
    try:
        store.delete_draft_file(settings.data_dir, style_id, path)
    except _STORE_ERRORS as exc:
        raise _http_error(exc) from exc
    return Response(status_code=204)


@router.post("/styles/{style_id}/draft/save", response_model=StyleOut)
async def save_draft_endpoint(
    style_id: str, engine: Engine = Depends(get_engine), settings: Settings = Depends(get_settings)
) -> StyleOut:
    """校验草稿，通过后覆盖（或新建）正式版本并删除草稿；不合法 422，名称重复 409。"""
    try:
        detail = store.save_draft(settings.data_dir, style_id)
    except _STORE_ERRORS as exc:
        raise _http_error(exc) from exc
    return _out(detail, _default_id(engine))
