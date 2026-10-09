"""OpenAI 原生 `ApplyPatchTool` 的编辑器（设计 §4.2、§4.3 事前拦截）。

模型给出 V4A diff，SDK 按操作调用 `create_file`/`update_file`/`delete_file`；
这里用 SDK 自带的 `apply_diff` 计算新内容，落盘一律经过 `workspace.files`
（ARCHITECTURE 规则 6），路径不安全或越出本阶段可写范围时返回
`status="failed"` 的结果（错误说明回给模型），不抛异常——抛异常 SDK 也会转成
失败结果，但会额外打一条错误日志。
"""

from __future__ import annotations

from pathlib import Path

from agents import ApplyPatchOperation, ApplyPatchResult, apply_diff

from studio.workspace import files
from studio.workspace.files import ScopeError
from studio.workspace.scope import WriteScope, is_writable


def to_workspace_relpath(workdir: Path, raw: str) -> str:
    """模型给出的路径 → 规范化的工作区相对路径；绝对路径须落在 `workdir` 内。

    不安全（越出工作区、含 `..`、空）时抛出 `ScopeError`。
    """
    if not Path(raw).is_absolute():
        return files.normalize_relpath(raw)
    relpath = files.relpath_within(workdir, raw)
    if not relpath:
        raise ScopeError(f"{raw} 是工作区本身，不是文件")
    return relpath


class WorkspaceApplyPatchEditor:
    """实现 SDK 的 `ApplyPatchEditor` 协议；路径相对 `workdir`（绝对路径须落在其内）。"""

    def __init__(self, workdir: Path, scope: WriteScope) -> None:
        self._workdir = workdir
        self._scope = scope

    def _relpath(self, raw: str) -> str:
        return to_workspace_relpath(self._workdir, raw)

    def _failed(self, raw_path: str, exc: Exception) -> ApplyPatchResult:
        allowed = "、".join(self._scope.writable) or "（无）"
        if isinstance(exc, ScopeError):
            message = f"{raw_path}：{exc}。本阶段可写：{allowed}"
        elif isinstance(exc, FileNotFoundError):
            message = f"{raw_path}：文件不存在"
        else:
            message = f"{raw_path}：{exc}"
        return ApplyPatchResult(status="failed", output=message)

    def create_file(self, operation: ApplyPatchOperation) -> ApplyPatchResult:
        try:
            relpath = self._relpath(operation.path)
            content = apply_diff("", operation.diff or "", mode="create")
            files.write_text(self._workdir, relpath, content, self._scope)
        except (ScopeError, OSError, ValueError) as exc:
            return self._failed(operation.path, exc)
        return ApplyPatchResult(status="completed", output=f"已创建 {relpath}")

    def update_file(self, operation: ApplyPatchOperation) -> ApplyPatchResult:
        try:
            relpath = self._relpath(operation.path)
            target = self._relpath(operation.move_to) if operation.move_to else relpath
            # Check both ends before touching anything, so a rejected move keeps the source.
            files.safe_path(self._workdir, target)
            for path in {relpath, target}:
                if not is_writable(self._scope, path):
                    raise ScopeError(f"不在可写范围内：{path}")
            updated = apply_diff(files.read_text(self._workdir, relpath), operation.diff or "")
            files.write_text(self._workdir, target, updated, self._scope)
            if target != relpath:
                files.delete_file(self._workdir, relpath, self._scope)
        except (ScopeError, OSError, ValueError) as exc:
            return self._failed(operation.path, exc)
        if target != relpath:
            return ApplyPatchResult(
                status="completed", output=f"已更新 {relpath} 并移动到 {target}"
            )
        return ApplyPatchResult(status="completed", output=f"已更新 {relpath}")

    def delete_file(self, operation: ApplyPatchOperation) -> ApplyPatchResult:
        try:
            relpath = self._relpath(operation.path)
            files.delete_file(self._workdir, relpath, self._scope)
        except (ScopeError, OSError, ValueError) as exc:
            return self._failed(operation.path, exc)
        return ApplyPatchResult(status="completed", output=f"已删除 {relpath}")
