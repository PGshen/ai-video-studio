"""兜底文件工具：LiteLLM / Chat Completions 路径下代替原生文件工具（设计 §4.2）。

复制自旧项目 `backend/app/services/strategies/openai_agent_runtime.py` 的
`OpenAICodegenWorkspace` 后改写（legacy-assets 清单）：

- 旧版按镜头编号读写 `scenes/scene_XX.py`，新版按工作区相对路径读写任意文件；
  写入范围由本轮 `WriteScope` 决定（事前拦截，设计 §4.3），读取只检查路径安全，
  所以 `style/`、`upstream/` 等只读内容也能读到。
- 落盘经过 `workspace.files`（ARCHITECTURE 规则 6）。保留旧版的大小上限和
  `edit_file` "精确匹配一次" 的规则；去掉旧版的 `validate`（阶段专属，M2 作为
  业务工具提供）和取消检查（取消由运行时统一处理）。
- 它们是 agent 的"原生"编辑的替身，不是工具托管文件，所以**不**调用
  `ToolContext.record_tool_write`。

不提供 Shell（设计 §4.2；R1 的结论可能改变这一点，见 T15）。
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from studio.agent.tools import ToolContext, ToolResult, ToolSpec
from studio.workspace import files
from studio.workspace.scope import WriteScope

MAX_READ_BYTES = 2_000_000
MAX_WRITE_BYTES = 500_000

FALLBACK_TOOL_NAMES = frozenset({"list_files", "read_file", "write_file", "edit_file"})


class ListFilesArgs(BaseModel):
    dir: str = Field(
        default="", description="只列出这个目录（工作区相对路径）下的文件；空字符串表示全部"
    )


class ReadFileArgs(BaseModel):
    path: str = Field(description="工作区相对路径，例如 topic/brief.md")


class WriteFileArgs(BaseModel):
    path: str = Field(description="工作区相对路径，例如 topic/brief.md")
    content: str = Field(description="完整的新文件内容")


class EditFileArgs(BaseModel):
    path: str = Field(description="工作区相对路径")
    old_text: str = Field(description="要替换的原文，必须在文件中恰好出现一次")
    new_text: str = Field(description="替换后的文本")


def _list_files(ctx: ToolContext, args: ListFilesArgs) -> ToolResult:
    prefix = args.dir.strip("/")
    paths = files.list_tree(ctx.workdir)
    if prefix:
        paths = [path for path in paths if path.startswith(prefix + "/")]
    return ToolResult(text=json.dumps(paths, ensure_ascii=False))


def _read_file(ctx: ToolContext, args: ReadFileArgs) -> ToolResult:
    path = files.safe_path(ctx.workdir, args.path)
    if not path.is_file():
        raise ValueError(f"文件不存在：{args.path}")
    if path.stat().st_size > MAX_READ_BYTES:
        raise ValueError(f"文件过大：{args.path}")
    return ToolResult(text=files.read_text(ctx.workdir, args.path))


def _check_size(content: str) -> None:
    if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
        raise ValueError(f"内容超过大小限制（{MAX_WRITE_BYTES} 字节）")


def build_fallback_tools(scope: WriteScope) -> list[ToolSpec]:
    """本轮的兜底文件工具；`scope` 由闭包带入（`ToolContext` 里没有可写范围）。"""

    def write_file(ctx: ToolContext, args: WriteFileArgs) -> ToolResult:
        _check_size(args.content)
        files.write_text(ctx.workdir, args.path, args.content, scope)
        return ToolResult(text=f"已写入 {args.path}（{len(args.content)} 字符）")

    def edit_file(ctx: ToolContext, args: EditFileArgs) -> ToolResult:
        if not args.old_text:
            raise ValueError("old_text 不能为空")
        content = files.read_text(ctx.workdir, args.path)
        matches = content.count(args.old_text)
        if matches != 1:
            raise ValueError(f"old_text 必须精确匹配一次，当前匹配 {matches} 次")
        updated = content.replace(args.old_text, args.new_text, 1)
        _check_size(updated)
        files.write_text(ctx.workdir, args.path, updated, scope)
        return ToolResult(text=f"已更新 {args.path}")

    all_stages: set[str] = set()  # added by the runtime per turn, not filtered by stage
    return [
        ToolSpec(
            "list_files",
            "列出工作区中的文件（相对路径，JSON 数组）",
            ListFilesArgs,
            all_stages,
            _list_files,
        ),
        ToolSpec("read_file", "读取工作区中的一个文本文件", ReadFileArgs, all_stages, _read_file),
        ToolSpec(
            "write_file",
            "完整写入一个文件（只能写本阶段可写范围内的路径）",
            WriteFileArgs,
            all_stages,
            write_file,
        ),
        ToolSpec(
            "edit_file",
            "在文件中精确替换唯一一处文本（只能改本阶段可写范围内的文件）",
            EditFileArgs,
            all_stages,
            edit_file,
        ),
    ]
