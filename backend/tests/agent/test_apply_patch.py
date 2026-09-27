"""WorkspaceApplyPatchEditor：增删改都经过 workspace.files，越界返回失败结果。"""

from __future__ import annotations

from pathlib import Path

from agents import ApplyPatchOperation, ApplyPatchResult
from agents.editor import ApplyPatchOperationType

from studio.agent.apply_patch import WorkspaceApplyPatchEditor
from studio.workspace.scope import WriteScope

SCOPE = WriteScope(writable=["topic/**"], tool_managed=["topic/managed.json"])


def _editor(workdir: Path) -> WorkspaceApplyPatchEditor:
    return WorkspaceApplyPatchEditor(workdir, SCOPE)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _op(
    kind: ApplyPatchOperationType, path: str, diff: str | None = None, move_to: str | None = None
) -> ApplyPatchOperation:
    return ApplyPatchOperation(type=kind, path=path, diff=diff, move_to=move_to)


class TestCreate:
    def test_creates_file_from_diff(self, workdir: Path) -> None:
        result = _editor(workdir).create_file(_op("create_file", "topic/a.md", "+hello\n+world"))

        assert result.status == "completed"
        assert (workdir / "topic" / "a.md").read_text(encoding="utf-8") == "hello\nworld"

    def test_absolute_path_inside_workdir_is_accepted(self, workdir: Path) -> None:
        path = str(workdir / "topic" / "b.md")
        result = _editor(workdir).create_file(_op("create_file", path, "+x"))

        assert result.status == "completed"
        assert (workdir / "topic" / "b.md").read_text(encoding="utf-8") == "x"

    def test_out_of_scope_create_is_rejected(self, workdir: Path) -> None:
        result = _editor(workdir).create_file(_op("create_file", "style/STYLE.md", "+x"))

        assert result.status == "failed"
        assert result.output is not None and "style/STYLE.md" in result.output
        assert not (workdir / "style" / "STYLE.md").exists()

    def test_path_outside_workdir_is_rejected(self, workdir: Path, tmp_path: Path) -> None:
        outside = tmp_path / "outside.md"
        result = _editor(workdir).create_file(_op("create_file", str(outside), "+x"))

        assert result.status == "failed"
        assert not outside.exists()

    def test_dotdot_is_rejected(self, workdir: Path) -> None:
        result = _editor(workdir).create_file(_op("create_file", "topic/../../x.md", "+x"))
        assert result.status == "failed"

    def test_tool_managed_file_is_rejected(self, workdir: Path) -> None:
        result = _editor(workdir).create_file(_op("create_file", "topic/managed.json", "+{}"))
        assert result.status == "failed"


class TestUpdate:
    def test_applies_diff(self, workdir: Path) -> None:
        _write(workdir / "topic" / "a.md", "a\nb\nc\n")

        result = _editor(workdir).update_file(
            _op("update_file", "topic/a.md", "@@\n a\n-b\n+B\n c")
        )

        assert result.status == "completed"
        assert (workdir / "topic" / "a.md").read_text(encoding="utf-8") == "a\nB\nc\n"

    def test_bad_context_is_a_failed_result(self, workdir: Path) -> None:
        _write(workdir / "topic" / "a.md", "a\n")

        result = _editor(workdir).update_file(_op("update_file", "topic/a.md", "@@\n-zzz\n+q"))

        assert result.status == "failed"
        assert (workdir / "topic" / "a.md").read_text(encoding="utf-8") == "a\n"

    def test_missing_file_is_a_failed_result(self, workdir: Path) -> None:
        result = _editor(workdir).update_file(_op("update_file", "topic/none.md", "@@\n-a\n+b"))
        assert result.status == "failed"

    def test_out_of_scope_update_leaves_file_untouched(self, workdir: Path) -> None:
        _write(workdir / "style" / "STYLE.md", "a\n")

        result = _editor(workdir).update_file(_op("update_file", "style/STYLE.md", "@@\n-a\n+b"))

        assert result.status == "failed"
        assert (workdir / "style" / "STYLE.md").read_text(encoding="utf-8") == "a\n"

    def test_move_to_writes_new_path_and_removes_old(self, workdir: Path) -> None:
        _write(workdir / "topic" / "a.md", "a\n")

        result = _editor(workdir).update_file(
            _op("update_file", "topic/a.md", "@@\n-a\n+b", move_to="topic/b.md")
        )

        assert result.status == "completed"
        assert not (workdir / "topic" / "a.md").exists()
        assert (workdir / "topic" / "b.md").read_text(encoding="utf-8") == "b\n"

    def test_move_out_of_scope_is_rejected_and_keeps_source(self, workdir: Path) -> None:
        _write(workdir / "topic" / "a.md", "a\n")

        result = _editor(workdir).update_file(
            _op("update_file", "topic/a.md", "@@\n-a\n+b", move_to="style/b.md")
        )

        assert result.status == "failed"
        assert (workdir / "topic" / "a.md").read_text(encoding="utf-8") == "a\n"
        assert not (workdir / "style" / "b.md").exists()


class TestDelete:
    def test_deletes_file(self, workdir: Path) -> None:
        _write(workdir / "topic" / "a.md", "a")

        result = _editor(workdir).delete_file(_op("delete_file", "topic/a.md"))

        assert result.status == "completed"
        assert not (workdir / "topic" / "a.md").exists()

    def test_out_of_scope_delete_is_rejected(self, workdir: Path) -> None:
        _write(workdir / "style" / "STYLE.md", "a")

        result = _editor(workdir).delete_file(_op("delete_file", "style/STYLE.md"))

        assert result.status == "failed"
        assert (workdir / "style" / "STYLE.md").exists()

    def test_missing_file_is_a_failed_result(self, workdir: Path) -> None:
        result = _editor(workdir).delete_file(_op("delete_file", "topic/none.md"))
        assert result.status == "failed"


def test_results_are_sdk_result_objects(workdir: Path) -> None:
    result = _editor(workdir).create_file(_op("create_file", "topic/a.md", "+x"))
    assert isinstance(result, ApplyPatchResult)
