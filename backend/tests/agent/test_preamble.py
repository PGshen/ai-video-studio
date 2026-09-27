from __future__ import annotations

from studio.agent.preamble import (
    DIFF_MAX_CHARS_PER_FILE,
    PreambleInputs,
    RollbackNotice,
    UpstreamChange,
    build_preamble,
    compose_user_text,
)
from studio.workspace import ModifiedFile, WorkspaceDiff


def _diff(
    added: list[str] | None = None,
    removed: list[str] | None = None,
    modified: list[ModifiedFile] | None = None,
) -> WorkspaceDiff:
    return WorkspaceDiff(added=added or [], removed=removed or [], modified=modified or [])


def _modified(path: str, text_diff: str | None) -> ModifiedFile:
    return ModifiedFile(path=path, old_sha256="a", new_sha256="b", text_diff=text_diff)


def test_empty_inputs_give_empty_preamble() -> None:
    assert build_preamble(PreambleInputs()) == ""
    # an empty diff is "nothing to say" as well
    assert build_preamble(PreambleInputs(user_edits=_diff())) == ""


def test_user_edits_list_files_and_truncated_diff() -> None:
    long_diff = "@@ -1 +1 @@\n" + "+x\n" * DIFF_MAX_CHARS_PER_FILE
    text = build_preamble(
        PreambleInputs(
            user_edits=_diff(
                added=["topic/new.md"],
                removed=["topic/old.md"],
                modified=[
                    _modified("topic/brief.md", "-old line\n+new line\n"),
                    _modified("topic/long.md", long_diff),
                    _modified("topic/pic.png", None),
                ],
            )
        )
    )

    assert "用户手动修改" in text
    for path in ("topic/new.md", "topic/old.md", "topic/brief.md", "topic/pic.png"):
        assert path in text
    assert "+new line" in text
    assert "（diff 已截断）" in text
    assert len(text) < 2 * DIFF_MAX_CHARS_PER_FILE + 1000


def test_all_sections_rendered() -> None:
    text = build_preamble(
        PreambleInputs(
            upstream_changes=[
                UpstreamChange(stage="topic", diff=_diff(modified=[_modified("topic/b.md", "")]))
            ],
            restored_paths=["style/STYLE.md"],
            rollback=RollbackNotice(
                rollback_snapshot_id="snap-r",
                target_snapshot_id="snap-t",
                diff=_diff(removed=["topic/draft.md"]),
            ),
            status_summary="topic/ 下有 1 个文件",
            handoff_files=["topic/brief.md"],
        )
    )

    assert "上游新定稿" in text and "topic/b.md" in text and "upstream/topic/" in text
    assert "被还原" in text and "style/STYLE.md" in text
    assert "回滚" in text and "snap-t" in text and "topic/draft.md" in text
    assert "topic/ 下有 1 个文件" in text
    assert "交接" in text and "topic/brief.md" in text


def test_compose_user_text() -> None:
    assert compose_user_text("", "你好") == "你好"
    composed = compose_user_text("前言", "你好")
    assert composed.startswith("前言") and composed.endswith("你好")
