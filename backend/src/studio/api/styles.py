"""`/api/styles`：风格库（磁盘目录存储 + 草稿；ADR 0019，计划 style-library T3）。

- 正式版本在 `data/styles/<id>/`，列表、详情、复制、删除直接读写目录；
- 编辑走草稿 `data/style-drafts/<id>/`：打开草稿、读写草稿文件、保存（校验通过才覆盖正式版本）、
  放弃。`POST /api/styles` 新建的是只有草稿的风格，保存之前在列表里标记为 `is_new`（找得回来）；
- 截图（ADR 0022）：草稿里上传、删除、调整顺序（改动类，同样受忙碌检查），正式版本和草稿各有一个
  只读的取图端点；上传的图片先在线程里规范化成 WebP，422 表示不是可用的图片或超出数量上限；
- 默认风格是 `settings.default_style_preset_id`，删除默认风格时清掉它。

错误映射：404 风格或文件不存在，400 草稿文件路径不合法，422 内容不合法（detail 逐条列出），
409 名称重复，或这套风格有对话轮次排队/运行中（改草稿的操作被拒绝，读取和打开草稿不受限）。
会写目录的端点都写成 `async def`：忙碌检查与写入之间不能 `await`（TurnRunner 在事件循环上调度）。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import Engine
from starlette.datastructures import UploadFile

from studio.agent.runner import TurnRunner
from studio.agent.runtime import RuntimeFactory
from studio.api.deps import get_engine, get_runtime_factory, get_settings, get_turn_runner
from studio.api.schemas import (
    DraftFileOut,
    DraftFileWrite,
    DraftStatusOut,
    ScreenshotOrder,
    SessionCreate,
    SessionOut,
    StyleOut,
    StyleSummaryOut,
)
from studio.api.sessions import session_out
from studio.config import Settings
from studio.db.repo.profiles import get_model_profile_by_id
from studio.db.repo.sessions import create_session, delete_subject_sessions, list_sessions
from studio.db.repo.settings import get_all_settings, update_settings
from studio.styles import store
from studio.styles.screenshots import MAX_UPLOAD_BYTES, ScreenshotError, normalize_image

STYLE_STAGE = "style"

router = APIRouter(prefix="/api", tags=["styles"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, store.StyleNotFoundError):
        return HTTPException(status_code=404, detail=f"风格不存在：{exc}")
    if isinstance(exc, store.StylePathError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, (store.StyleValidationError, ScreenshotError)):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=409, detail=str(exc))


_STORE_ERRORS = (
    store.StyleNotFoundError,
    store.StylePathError,
    store.StyleValidationError,
    store.DuplicateStyleNameError,
    store.StyleExistsError,
    ScreenshotError,
)


def _ensure_idle(runner: TurnRunner, style_id: str) -> None:
    """这套风格有对话轮次（排队或运行中）时，改草稿的操作被拒绝：AI 正在改同一份草稿。
    读取和「打开草稿」（幂等）不受限。写端点都是 `async def`，检查与写入之间不 `await`。"""
    if runner.is_subject_busy(style_id):
        raise HTTPException(
            status_code=409, detail="AI 正在修改这套风格，请等这一轮结束（或先停止它）"
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
        screenshots=detail.screenshots,
        is_default=detail.id == default_id,
        modified_at=detail.modified_at,
    )


def _draft_out(status: store.DraftStatus, runner: TurnRunner | None = None) -> DraftStatusOut:
    busy = runner.is_subject_busy(status.id) if runner is not None else False
    return DraftStatusOut(
        id=status.id,
        is_new=status.is_new,
        dirty=status.dirty,
        files=status.files,
        screenshots=status.screenshots,
        busy=busy,
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
            cover=s.cover,
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
    style_id: str,
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
    runner: TurnRunner = Depends(get_turn_runner),
) -> Response:
    _ensure_idle(runner, style_id)
    try:
        store.delete_style(settings.data_dir, style_id)
    except _STORE_ERRORS as exc:
        raise _http_error(exc) from exc
    delete_subject_sessions(engine, style_id)
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
    style_id: str,
    settings: Settings = Depends(get_settings),
    runner: TurnRunner = Depends(get_turn_runner),
) -> DraftStatusOut:
    """打开草稿：没有就从正式版本复制一份，已有则原样返回。"""
    try:
        return _draft_out(store.open_draft(settings.data_dir, style_id), runner)
    except _STORE_ERRORS as exc:
        raise _http_error(exc) from exc


@router.delete("/styles/{style_id}/draft", status_code=204)
async def discard_draft_endpoint(
    style_id: str,
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
    runner: TurnRunner = Depends(get_turn_runner),
) -> Response:
    _ensure_idle(runner, style_id)
    try:
        store.discard_draft(settings.data_dir, style_id)
    except _STORE_ERRORS as exc:
        raise _http_error(exc) from exc
    if not store.style_known(settings.data_dir, style_id):
        # 从未保存的新风格整个消失了，它的对话也一起清掉。
        delete_subject_sessions(engine, style_id)
    return Response(status_code=204)


@router.get("/styles/{style_id}/draft/files", response_model=DraftStatusOut)
async def draft_status_endpoint(
    style_id: str,
    settings: Settings = Depends(get_settings),
    runner: TurnRunner = Depends(get_turn_runner),
) -> DraftStatusOut:
    try:
        return _draft_out(store.draft_status(settings.data_dir, style_id), runner)
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
    runner: TurnRunner = Depends(get_turn_runner),
) -> DraftStatusOut:
    _ensure_idle(runner, style_id)
    try:
        store.write_draft_file(settings.data_dir, style_id, path, body.content)
        return _draft_out(store.draft_status(settings.data_dir, style_id), runner)
    except _STORE_ERRORS as exc:
        raise _http_error(exc) from exc


@router.delete("/styles/{style_id}/draft/files/{path:path}", status_code=204)
async def delete_draft_file_endpoint(
    style_id: str,
    path: str,
    settings: Settings = Depends(get_settings),
    runner: TurnRunner = Depends(get_turn_runner),
) -> Response:
    _ensure_idle(runner, style_id)
    try:
        store.delete_draft_file(settings.data_dir, style_id, path)
    except _STORE_ERRORS as exc:
        raise _http_error(exc) from exc
    return Response(status_code=204)


_IMAGE_HEADERS = {
    "Cache-Control": "private, max-age=31536000, immutable",
    "X-Content-Type-Options": "nosniff",
}
"""截图文件名里带内容哈希：同一个名字永远是同一份内容，可以放心长期缓存；`nosniff` 保证浏览器
只按 `image/webp` 解释它。"""


def _screenshot_response(style_id: str, name: str, settings: Settings, *, draft: bool) -> Response:
    try:
        path = store.screenshot_path(settings.data_dir, style_id, name, draft=draft)
    except _STORE_ERRORS as exc:
        raise _http_error(exc) from exc
    return FileResponse(path, media_type="image/webp", headers=_IMAGE_HEADERS)


@router.get("/styles/{style_id}/screenshots/{name}")
async def get_screenshot_endpoint(
    style_id: str, name: str, settings: Settings = Depends(get_settings)
) -> Response:
    return _screenshot_response(style_id, name, settings, draft=False)


@router.get("/styles/{style_id}/draft/screenshots/{name}")
async def get_draft_screenshot_endpoint(
    style_id: str, name: str, settings: Settings = Depends(get_settings)
) -> Response:
    return _screenshot_response(style_id, name, settings, draft=True)


def _too_large() -> HTTPException:
    return HTTPException(
        status_code=422, detail=f"图片大小超过上限 {MAX_UPLOAD_BYTES // (1024 * 1024)} MB"
    )


@router.post("/styles/{style_id}/draft/screenshots", response_model=DraftStatusOut)
async def upload_screenshot_endpoint(
    style_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
    runner: TurnRunner = Depends(get_turn_runner),
) -> DraftStatusOut:
    """上传一张截图（multipart，字段 `file`），规范化成 WebP 后追加到草稿末尾。"""
    _ensure_idle(runner, style_id)
    # 没有（或写坏了）Content-Length 就没法在解析之前挡住超大的请求体：直接拒绝。
    length = request.headers.get("content-length", "")
    if not length.isdigit():
        raise HTTPException(status_code=422, detail="请求缺少有效的 Content-Length")
    if int(length) > MAX_UPLOAD_BYTES + 64 * 1024:
        raise _too_large()
    try:
        form = await request.form()
    except Exception as exc:  # malformed multipart bodies surface as several error types
        raise HTTPException(status_code=422, detail="请求体不是合法的 multipart/form-data") from exc
    try:
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise HTTPException(status_code=422, detail="没有收到文件，字段名应为 file")
        data = await upload.read(MAX_UPLOAD_BYTES + 1)
    finally:
        await form.close()
    if len(data) > MAX_UPLOAD_BYTES:
        raise _too_large()
    try:
        webp = await asyncio.to_thread(normalize_image, data)
        # 上面的 await 期间可能已经开始了对话轮次：检查和写入之间不能再 await。
        _ensure_idle(runner, style_id)
        store.add_draft_screenshot(settings.data_dir, style_id, webp)
        return _draft_out(store.draft_status(settings.data_dir, style_id), runner)
    except _STORE_ERRORS as exc:
        raise _http_error(exc) from exc


@router.put("/styles/{style_id}/draft/screenshots/order", response_model=DraftStatusOut)
async def reorder_screenshots_endpoint(
    style_id: str,
    body: ScreenshotOrder,
    settings: Settings = Depends(get_settings),
    runner: TurnRunner = Depends(get_turn_runner),
) -> DraftStatusOut:
    _ensure_idle(runner, style_id)
    try:
        store.reorder_draft_screenshots(settings.data_dir, style_id, body.names)
        return _draft_out(store.draft_status(settings.data_dir, style_id), runner)
    except _STORE_ERRORS as exc:
        raise _http_error(exc) from exc


@router.delete("/styles/{style_id}/draft/screenshots/{name}", response_model=DraftStatusOut)
async def delete_screenshot_endpoint(
    style_id: str,
    name: str,
    settings: Settings = Depends(get_settings),
    runner: TurnRunner = Depends(get_turn_runner),
) -> DraftStatusOut:
    _ensure_idle(runner, style_id)
    try:
        store.delete_draft_screenshot(settings.data_dir, style_id, name)
        return _draft_out(store.draft_status(settings.data_dir, style_id), runner)
    except _STORE_ERRORS as exc:
        raise _http_error(exc) from exc


@router.post("/styles/{style_id}/draft/save", response_model=StyleOut)
async def save_draft_endpoint(
    style_id: str,
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
    runner: TurnRunner = Depends(get_turn_runner),
) -> StyleOut:
    """校验草稿，通过后覆盖（或新建）正式版本并删除草稿；不合法 422，名称重复 409。"""
    _ensure_idle(runner, style_id)
    try:
        detail = store.save_draft(settings.data_dir, style_id)
    except _STORE_ERRORS as exc:
        raise _http_error(exc) from exc
    return _out(detail, _default_id(engine))


def _require_known(settings: Settings, style_id: str) -> None:
    if not store.style_known(settings.data_dir, style_id):
        raise _http_error(store.StyleNotFoundError(style_id))


@router.post("/styles/{style_id}/sessions", response_model=SessionOut, status_code=201)
async def create_style_session_endpoint(
    style_id: str,
    body: SessionCreate,
    engine: Engine = Depends(get_engine),
    runtime_factory: RuntimeFactory = Depends(get_runtime_factory),
    settings: Settings = Depends(get_settings),
) -> SessionOut:
    """新建这套风格的对话会话（从未保存的新风格也可以）；同一风格的旧会话取消活动。"""
    _require_known(settings, style_id)
    profile = get_model_profile_by_id(engine, body.model_profile_id)
    if profile is None:
        raise HTTPException(status_code=400, detail=f"模型配置不存在：{body.model_profile_id}")
    if not runtime_factory.has(profile.runtime):
        raise HTTPException(status_code=400, detail=f"运行时未启用：{profile.runtime}")
    session = create_session(
        engine,
        project_id=None,
        stage=STYLE_STAGE,
        subject_id=style_id,
        model_profile_id=profile.id,
        runtime=profile.runtime,
    )
    return session_out(session)


@router.get("/styles/{style_id}/sessions", response_model=list[SessionOut])
async def list_style_sessions_endpoint(
    style_id: str, engine: Engine = Depends(get_engine), settings: Settings = Depends(get_settings)
) -> list[SessionOut]:
    _require_known(settings, style_id)
    return [session_out(s) for s in list_sessions(engine, None, STYLE_STAGE, subject_id=style_id)]
