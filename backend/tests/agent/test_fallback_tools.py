"""兜底文件工具（LiteLLM 路径）的测试。

改写自旧项目 `backend/tests/test_openai_agent_runtime.py` 中针对
`OpenAICodegenWorkspace` 的用例（`test_workspace_only_exposes_bounded_scene_operations`、
`test_openai_tool_surface_has_no_shell_or_arbitrary_path_tool`）：旧版按镜头编号
读写 `scenes/scene_XX.py`，新版按工作区相对路径读写、越界由 `WriteScope` 决定。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from studio.agent.fallback_tools import (
    FALLBACK_TOOL_NAMES,
    MAX_READ_BYTES,
    MAX_WRITE_BYTES,
    build_fallback_tools,
)
from studio.agent.tools import ToolContext, ToolResult, invoke_tool
from studio.workspace.scope import WriteScope

SCOPE = WriteScope(writable=["topic/**"], tool_managed=["topic/managed.json"])


def _record(relpath: str, sha256: str) -> None:
    raise AssertionError("fallback tools model native edits; they must not record tool writes")


def _ctx(workdir: Path) -> ToolContext:
    return ToolContext(project_id="p", stage="topic", workdir=workdir, record_tool_write=_record)


async def _call(workdir: Path, name: str, **args: Any) -> ToolResult:
    spec = {spec.name: spec for spec in build_fallback_tools(SCOPE)}[name]
    return await invoke_tool(spec, _ctx(workdir), args)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_tool_surface_is_the_minimal_file_set_without_shell() -> None:
    names = {spec.name for spec in build_fallback_tools(SCOPE)}
    assert names == {"list_files", "read_file", "write_file", "edit_file"}
    assert names == FALLBACK_TOOL_NAMES


async def test_write_read_edit_list_round_trip(workdir: Path) -> None:
    written = await _call(workdir, "write_file", path="topic/brief.md", content="self.wait(1)")
    assert not written.is_error and "topic/brief.md" in written.text

    assert (await _call(workdir, "read_file", path="topic/brief.md")).text == "self.wait(1)"

    edited = await _call(
        workdir, "edit_file", path="topic/brief.md", old_text="wait(1)", new_text="wait(2)"
    )
    assert not edited.is_error
    assert (workdir / "topic" / "brief.md").read_text(encoding="utf-8") == "self.wait(2)"

    listed = await _call(workdir, "list_files")
    assert "topic/brief.md" in json.loads(listed.text)


async def test_list_files_filters_by_directory(workdir: Path) -> None:
    _write(workdir / "topic" / "a.md", "a")
    _write(workdir / "style" / "STYLE.md", "s")

    listed = await _call(workdir, "list_files", dir="style")

    assert json.loads(listed.text) == ["style/STYLE.md"]


async def test_read_outside_scope_is_allowed(workdir: Path) -> None:
    """只读目录（style/、upstream/）要能读：读取只检查路径安全，不检查可写范围。"""
    _write(workdir / "style" / "STYLE.md", "风格")
    assert (await _call(workdir, "read_file", path="style/STYLE.md")).text == "风格"


async def test_read_missing_file_is_an_error(workdir: Path) -> None:
    result = await _call(workdir, "read_file", path="topic/none.md")
    assert result.is_error


async def test_write_outside_scope_is_rejected(workdir: Path) -> None:
    result = await _call(workdir, "write_file", path="style/STYLE.md", content="x")

    assert result.is_error
    assert not (workdir / "style" / "STYLE.md").exists()


async def test_write_to_tool_managed_file_is_rejected(workdir: Path) -> None:
    result = await _call(workdir, "write_file", path="topic/managed.json", content="{}")
    assert result.is_error


@pytest.mark.parametrize("path", ["../escape.md", "/etc/passwd", "topic/../../x.md"])
async def test_unsafe_paths_are_rejected(workdir: Path, path: str) -> None:
    assert (await _call(workdir, "write_file", path=path, content="x")).is_error
    assert (await _call(workdir, "read_file", path=path)).is_error


async def test_edit_requires_exactly_one_match(workdir: Path) -> None:
    _write(workdir / "topic" / "a.md", "x x")

    missing = await _call(workdir, "edit_file", path="topic/a.md", old_text="y", new_text="z")
    twice = await _call(workdir, "edit_file", path="topic/a.md", old_text="x", new_text="z")

    assert missing.is_error and "精确匹配一次" in missing.text
    assert twice.is_error and "精确匹配一次" in twice.text
    assert (workdir / "topic" / "a.md").read_text(encoding="utf-8") == "x x"


async def test_edit_rejects_empty_old_text(workdir: Path) -> None:
    _write(workdir / "topic" / "a.md", "x")
    result = await _call(workdir, "edit_file", path="topic/a.md", old_text="", new_text="z")
    assert result.is_error


async def test_edit_outside_scope_is_rejected(workdir: Path) -> None:
    _write(workdir / "style" / "STYLE.md", "a")

    result = await _call(workdir, "edit_file", path="style/STYLE.md", old_text="a", new_text="b")

    assert result.is_error
    assert (workdir / "style" / "STYLE.md").read_text(encoding="utf-8") == "a"


async def test_write_size_limit(workdir: Path) -> None:
    result = await _call(
        workdir, "write_file", path="topic/big.md", content="x" * (MAX_WRITE_BYTES + 1)
    )

    assert result.is_error
    assert not (workdir / "topic" / "big.md").exists()


async def test_read_size_limit(workdir: Path) -> None:
    (workdir / "topic").mkdir()
    (workdir / "topic" / "big.md").write_bytes(b"x" * (MAX_READ_BYTES + 1))

    assert (await _call(workdir, "read_file", path="topic/big.md")).is_error
