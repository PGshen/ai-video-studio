"""`/api/projects/{id}/files*`（任务简报 T7；评审关注点 3）。

- **树**：隐藏 `.cache/`、`output/`（渲染中间产物/成片，不属于"工作区内容"）；
  `upstream/` 下的条目仍然列出，标记 `readonly: true`（供前端画布置灰）。
- **读单个文件**：不区分文本/二进制——统一按原始字节返回，`Content-Type`
  用标准库 `mimetypes` 按扩展名猜测（猜不出时是
  `application/octet-stream`；文本类型附 `charset=utf-8`）。这样文本文件
  前端可以直接当字符串用（`response.text`/`fetch().text()`），二进制文件
  （比如画布以后要显示的图片）也能被浏览器正确处理，不需要两个不同的
  端点或额外的"是否二进制"标志。
- **写**：body 是 JSON `{"content": <UTF-8 文本>}`；M1 的手动编辑只需要
  文本（CodeMirror 编辑器），不支持二进制上传。路径不合法（含 `..`、符号
  链接、越出工作区）→ 400；合法但不在指定 `stage` 的可写范围内（含
  `upstream/`、阶段的 `tool_managed` 文件）→ 403；未知阶段名 → 404；项目
  正在跑一轮 → 409。
"""

from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import Engine

from studio.agent.runner import TurnRunner
from studio.agent.stage import StageRegistry
from studio.api.deps import get_engine, get_registry, get_settings, get_turn_runner
from studio.api.schemas import FileEntry, FileTreeOut, FileWriteRequest, FileWriteResult
from studio.config import Settings
from studio.db.repo.projects import get_project
from studio.workspace import ScopeError, files, is_writable, project_dir
from studio.workspace.layout import EXCLUDED_TOP_DIRS

router = APIRouter(prefix="/api", tags=["files"])

# `upstream/` 仍然要在树里出现（标记只读），只隐藏 `.cache/`、`output/`。
_HIDDEN_TOP_DIRS = EXCLUDED_TOP_DIRS - {"upstream"}


def _require_project(engine: Engine, project_id: str) -> None:
    if get_project(engine, project_id) is None:
        raise HTTPException(status_code=404, detail=f"项目不存在：{project_id}")


def _is_hidden(relpath: str) -> bool:
    top = relpath.split("/", 1)[0]
    return top in _HIDDEN_TOP_DIRS


@router.get("/projects/{project_id}/files", response_model=FileTreeOut)
def list_files_endpoint(
    project_id: str,
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
) -> FileTreeOut:
    _require_project(engine, project_id)
    workdir = project_dir(settings.data_dir, project_id)
    entries = [
        FileEntry(path=path, readonly=path.startswith("upstream/"))
        for path in files.list_tree(workdir)
        if not _is_hidden(path)
    ]
    return FileTreeOut(files=entries)


def _guess_content_type(relpath: str) -> str:
    guessed, _encoding = mimetypes.guess_type(relpath)
    if guessed is None:
        return "application/octet-stream"
    if guessed.startswith("text/") or guessed == "application/json":
        return f"{guessed}; charset=utf-8"
    return guessed


@router.get("/projects/{project_id}/files/{path:path}")
def read_file_endpoint(
    project_id: str,
    path: str,
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
) -> Response:
    _require_project(engine, project_id)
    workdir = project_dir(settings.data_dir, project_id)
    try:
        abs_path = files.safe_path(workdir, path)
    except ScopeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if _is_hidden(path) or not abs_path.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在：{path}")

    data = files.read_bytes(workdir, path)
    return Response(content=data, media_type=_guess_content_type(path))


@router.put("/projects/{project_id}/files/{path:path}", response_model=FileWriteResult)
def write_file_endpoint(
    project_id: str,
    path: str,
    stage: str,
    body: FileWriteRequest,
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
    registry: StageRegistry = Depends(get_registry),
    turn_runner: TurnRunner = Depends(get_turn_runner),
) -> FileWriteResult:
    _require_project(engine, project_id)
    try:
        stage_definition = registry.get(stage)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"未知阶段：{stage}") from exc

    if turn_runner.is_project_busy(project_id):
        raise HTTPException(status_code=409, detail="项目正在运行中的一轮，请稍后再试")

    workdir = project_dir(settings.data_dir, project_id)
    try:
        files.safe_path(workdir, path)
    except ScopeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    scope = stage_definition.write_scope()
    if not is_writable(scope, path):
        raise HTTPException(status_code=403, detail=f"不在 {stage} 阶段的可写范围内：{path}")

    files.write_text(workdir, path, body.content, scope)
    return FileWriteResult(path=path)
