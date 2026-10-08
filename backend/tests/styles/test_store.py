"""风格目录存储：正式版本、草稿、原子保存（计划 style-library T2）。"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import pytest

from studio.styles import store
from studio.styles.layout import draft_dir, style_dir, styles_root
from studio.styles.store import (
    DuplicateStyleNameError,
    StyleExistsError,
    StyleNotFoundError,
    StylePathError,
    StyleValidationError,
)
from studio.styles.validate import StyleFiles, parse_frontmatter


def _entry(name: str = "暖纸双色", category: str | None = "概念传记", body: str = "") -> str:
    lines = ["---", f"name: {name}", "description: 暖色纸张质感的双色风格"]
    if category is not None:
        lines.append(f"category: {category}")
    return "\n".join([*lines, "---", "", f"# {name}", body]) + "\n"


def _files(name: str = "暖纸双色", category: str | None = "概念传记") -> StyleFiles:
    return {
        "STYLE.md": _entry(
            name, category, "先读 `references/color.md`，再看 `exemplars/e1.json`。"
        ),
        "references/color.md": "主色：暖白",
        "exemplars/e1.json": "{}",
    }


def _saved(data: Path, name: str = "暖纸双色", category: str | None = "概念传记") -> str:
    return store.import_style(data, _files(name, category)).id


class TestImportAndRead:
    def test_round_trip(self, tmp_path: Path) -> None:
        detail = store.import_style(tmp_path, _files())
        assert detail.name == "暖纸双色"
        assert detail.category == "概念传记"
        assert detail.files == _files()
        assert store.get_style(tmp_path, detail.id).files == _files()
        assert store.read_style_files(tmp_path, detail.id) == _files()

    def test_explicit_id_is_used_as_the_directory_name(self, tmp_path: Path) -> None:
        detail = store.import_style(tmp_path, _files(), style_id="legacy-1")
        assert detail.id == "legacy-1"
        assert style_dir(tmp_path, "legacy-1").is_dir()

    def test_existing_id_is_not_overwritten_unless_asked(self, tmp_path: Path) -> None:
        store.import_style(tmp_path, _files("甲"), style_id="s1")
        with pytest.raises(StyleExistsError):
            store.import_style(tmp_path, _files("乙"), style_id="s1")
        replaced = store.import_style(tmp_path, _files("乙"), style_id="s1", overwrite=True)
        assert replaced.name == "乙"
        assert store.get_style(tmp_path, "s1").name == "乙"

    def test_invalid_content_is_rejected_and_nothing_is_written(self, tmp_path: Path) -> None:
        with pytest.raises(StyleValidationError) as exc:
            store.import_style(tmp_path, {"STYLE.md": "没有 frontmatter"})
        assert exc.value.errors
        assert not styles_root(tmp_path).exists() or not list(styles_root(tmp_path).iterdir())

    def test_names_are_unique_after_trimming(self, tmp_path: Path) -> None:
        _saved(tmp_path, "暖纸双色")
        with pytest.raises(DuplicateStyleNameError):
            store.import_style(tmp_path, _files("  暖纸双色  "))

    def test_unknown_or_invalid_ids(self, tmp_path: Path) -> None:
        with pytest.raises(StyleNotFoundError):
            store.get_style(tmp_path, "nope")
        with pytest.raises(StyleNotFoundError):
            store.get_style(tmp_path, "../evil")


class TestList:
    def test_summaries_carry_counts_and_are_sorted_by_category_then_name(
        self, tmp_path: Path
    ) -> None:
        b = _saved(tmp_path, "b-style", "科普")
        a = _saved(tmp_path, "a-style", "科普")
        c = _saved(tmp_path, "z-style", "概念传记")
        summaries = store.list_styles(tmp_path)
        assert [s.id for s in summaries] == [c, a, b]
        first = summaries[0]
        assert (first.reference_count, first.exemplar_count) == (1, 1)
        assert first.description == "暖色纸张质感的双色风格"
        assert first.has_draft is False and first.is_new is False
        assert first.modified_at.tzinfo is not None

    def test_missing_category_shows_as_uncategorized(self, tmp_path: Path) -> None:
        _saved(tmp_path, category=None)
        assert store.list_styles(tmp_path)[0].category == "未分类"

    def test_empty_when_nothing_exists(self, tmp_path: Path) -> None:
        assert store.list_styles(tmp_path) == []

    def test_broken_directories_are_skipped_not_fatal(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        good = _saved(tmp_path)
        (styles_root(tmp_path) / "no-entry").mkdir()
        (styles_root(tmp_path) / "bad-front").mkdir()
        (styles_root(tmp_path) / "bad-front" / "STYLE.md").write_text("# 没有 frontmatter")
        (styles_root(tmp_path) / ".hidden").mkdir()
        (styles_root(tmp_path) / "stray.txt").write_text("x")
        with caplog.at_level(logging.WARNING):
            summaries = store.list_styles(tmp_path)
        assert [s.id for s in summaries] == [good]
        assert "no-entry" in caplog.text and "bad-front" in caplog.text

    def test_has_draft_flag(self, tmp_path: Path) -> None:
        style_id = _saved(tmp_path)
        store.open_draft(tmp_path, style_id)
        assert store.list_styles(tmp_path)[0].has_draft is True


class TestDuplicate:
    def test_copy_is_independent_and_gets_a_fresh_name(self, tmp_path: Path) -> None:
        source = _saved(tmp_path)
        first = store.duplicate_style(tmp_path, source)
        second = store.duplicate_style(tmp_path, source)
        assert first.name == "暖纸双色（副本）"
        assert second.name == "暖纸双色（副本 2）"
        assert first.id != source
        assert first.category == "概念传记"
        assert first.files["references/color.md"] == "主色：暖白"
        assert parse_frontmatter(first.files["STYLE.md"]) is not None
        assert store.get_style(tmp_path, source).name == "暖纸双色"

    def test_unknown_source(self, tmp_path: Path) -> None:
        with pytest.raises(StyleNotFoundError):
            store.duplicate_style(tmp_path, "nope")


class TestDelete:
    def test_removes_saved_version_and_draft(self, tmp_path: Path) -> None:
        style_id = _saved(tmp_path)
        store.open_draft(tmp_path, style_id)
        store.delete_style(tmp_path, style_id)
        assert not style_dir(tmp_path, style_id).exists()
        assert not draft_dir(tmp_path, style_id).exists()

    def test_removes_a_never_saved_draft(self, tmp_path: Path) -> None:
        style_id = store.create_new_draft(tmp_path)
        store.delete_style(tmp_path, style_id)
        assert not draft_dir(tmp_path, style_id).exists()

    def test_unknown_id(self, tmp_path: Path) -> None:
        with pytest.raises(StyleNotFoundError):
            store.delete_style(tmp_path, "nope")


class TestDraftLifecycle:
    def test_new_draft_starts_from_a_valid_template(self, tmp_path: Path) -> None:
        style_id = store.create_new_draft(tmp_path)
        status = store.draft_status(tmp_path, style_id)
        assert status.is_new is True and status.dirty is True
        assert status.files == ["STYLE.md"]
        assert store.validate_draft(tmp_path, style_id) == []

    def test_a_never_saved_draft_is_listed_as_new_so_it_can_be_resumed(
        self, tmp_path: Path
    ) -> None:
        saved = _saved(tmp_path, "已保存")
        new_id = store.create_new_draft(tmp_path)
        store.write_draft_file(tmp_path, new_id, "references/a.md", "x")

        summaries = {s.id: s for s in store.list_styles(tmp_path)}

        assert set(summaries) == {saved, new_id}
        assert summaries[saved].is_new is False
        item = summaries[new_id]
        assert item.is_new is True and item.has_draft is True
        assert item.name == "新风格" and item.category == "未分类"
        assert item.reference_count == 1
        assert item.modified_at.tzinfo is not None

    def test_a_draft_without_a_usable_entry_is_still_listed_so_it_can_be_discarded(
        self, tmp_path: Path
    ) -> None:
        new_id = store.create_new_draft(tmp_path)
        store.write_draft_file(tmp_path, new_id, "STYLE.md", "frontmatter 被删了")

        [item] = store.list_styles(tmp_path)

        assert item.id == new_id and item.is_new is True
        assert item.name == "未命名风格"

    def test_two_new_drafts_with_the_same_name_do_not_block_each_other_until_saved(
        self, tmp_path: Path
    ) -> None:
        first = store.create_new_draft(tmp_path)
        second = store.create_new_draft(tmp_path)
        store.save_draft(tmp_path, first)
        with pytest.raises(DuplicateStyleNameError):
            store.save_draft(tmp_path, second)

    def test_open_draft_copies_the_saved_version_and_is_idempotent(self, tmp_path: Path) -> None:
        style_id = _saved(tmp_path)
        first = store.open_draft(tmp_path, style_id)
        assert first.is_new is False and first.dirty is False
        assert first.files == ["STYLE.md", "exemplars/e1.json", "references/color.md"]
        store.write_draft_file(tmp_path, style_id, "references/color.md", "改过了")
        again = store.open_draft(tmp_path, style_id)
        assert again.dirty is True
        assert store.read_draft_file(tmp_path, style_id, "references/color.md") == "改过了"

    def test_open_draft_of_unknown_style(self, tmp_path: Path) -> None:
        with pytest.raises(StyleNotFoundError):
            store.open_draft(tmp_path, "nope")

    def test_dirty_goes_back_to_false_when_the_edit_is_reverted(self, tmp_path: Path) -> None:
        style_id = _saved(tmp_path)
        store.open_draft(tmp_path, style_id)
        store.write_draft_file(tmp_path, style_id, "references/color.md", "x")
        assert store.draft_status(tmp_path, style_id).dirty is True
        store.write_draft_file(tmp_path, style_id, "references/color.md", "主色：暖白")
        assert store.draft_status(tmp_path, style_id).dirty is False

    def test_add_and_delete_files(self, tmp_path: Path) -> None:
        style_id = _saved(tmp_path)
        store.open_draft(tmp_path, style_id)
        store.write_draft_file(tmp_path, style_id, "references/new.md", "n")
        assert "references/new.md" in store.draft_status(tmp_path, style_id).files
        store.delete_draft_file(tmp_path, style_id, "references/new.md")
        assert "references/new.md" not in store.draft_status(tmp_path, style_id).files
        with pytest.raises(StyleNotFoundError):
            store.read_draft_file(tmp_path, style_id, "references/new.md")

    def test_discard_keeps_the_saved_version(self, tmp_path: Path) -> None:
        style_id = _saved(tmp_path)
        store.open_draft(tmp_path, style_id)
        store.write_draft_file(tmp_path, style_id, "STYLE.md", "乱写")
        store.discard_draft(tmp_path, style_id)
        assert not draft_dir(tmp_path, style_id).exists()
        assert store.get_style(tmp_path, style_id).files == _files()

    def test_discarding_a_never_saved_draft_removes_the_style_entirely(
        self, tmp_path: Path
    ) -> None:
        style_id = store.create_new_draft(tmp_path)
        store.discard_draft(tmp_path, style_id)
        assert not draft_dir(tmp_path, style_id).exists()
        with pytest.raises(StyleNotFoundError):
            store.draft_status(tmp_path, style_id)

    def test_discard_without_a_draft_is_a_no_op_for_an_existing_style(self, tmp_path: Path) -> None:
        style_id = _saved(tmp_path)
        store.discard_draft(tmp_path, style_id)
        with pytest.raises(StyleNotFoundError):
            store.discard_draft(tmp_path, "nope")


class TestDraftPathSafety:
    @pytest.mark.parametrize(
        "relpath",
        [
            "../evil.md",
            "references/../../evil.md",
            "/abs.md",
            "notes.md",
            "other/a.md",
            "references/.hidden.md",
            "references/a/b.md",
            "references",
            "STYLE.md/x",
            "references/a b.md",
            "references/a\\b.md",
            "",
        ],
    )
    def test_writes_outside_the_allowed_layout_are_rejected(
        self, tmp_path: Path, relpath: str
    ) -> None:
        style_id = _saved(tmp_path)
        store.open_draft(tmp_path, style_id)
        with pytest.raises(StylePathError):
            store.write_draft_file(tmp_path, style_id, relpath, "x")
        with pytest.raises(StylePathError):
            store.read_draft_file(tmp_path, style_id, relpath)
        with pytest.raises(StylePathError):
            store.delete_draft_file(tmp_path, style_id, relpath)
        assert not (tmp_path / "evil.md").exists()

    def test_writing_through_a_symlinked_directory_is_rejected(self, tmp_path: Path) -> None:
        style_id = _saved(tmp_path)
        store.open_draft(tmp_path, style_id)
        outside = tmp_path / "outside"
        outside.mkdir()
        shutil.rmtree(draft_dir(tmp_path, style_id) / "references")
        (draft_dir(tmp_path, style_id) / "references").symlink_to(outside)
        with pytest.raises(StylePathError):
            store.write_draft_file(tmp_path, style_id, "references/x.md", "x")
        assert list(outside.iterdir()) == []

    def test_a_symlinked_file_cannot_be_read_through_the_api(self, tmp_path: Path) -> None:
        style_id = _saved(tmp_path)
        store.open_draft(tmp_path, style_id)
        secret = tmp_path / "secret.md"
        secret.write_text("secret")
        link = draft_dir(tmp_path, style_id) / "references" / "leak.md"
        link.symlink_to(secret)
        with pytest.raises(StylePathError):
            store.read_draft_file(tmp_path, style_id, "references/leak.md")

    def test_oversized_writes_are_rejected(self, tmp_path: Path) -> None:
        style_id = _saved(tmp_path)
        store.open_draft(tmp_path, style_id)
        with pytest.raises(StyleValidationError):
            store.write_draft_file(tmp_path, style_id, "references/big.md", "x" * 200_001)


class TestSave:
    def test_save_replaces_the_saved_version_and_removes_the_draft(self, tmp_path: Path) -> None:
        style_id = _saved(tmp_path)
        store.open_draft(tmp_path, style_id)
        store.write_draft_file(tmp_path, style_id, "references/color.md", "主色：深蓝")
        store.delete_draft_file(tmp_path, style_id, "exemplars/e1.json")
        store.write_draft_file(
            tmp_path, style_id, "STYLE.md", _entry(body="先读 `references/color.md`。")
        )
        detail = store.save_draft(tmp_path, style_id)
        assert detail.files["references/color.md"] == "主色：深蓝"
        assert "exemplars/e1.json" not in detail.files
        assert store.get_style(tmp_path, style_id).files == detail.files
        assert not draft_dir(tmp_path, style_id).exists()
        assert [p.name for p in styles_root(tmp_path).iterdir()] == [style_id]

    def test_saving_a_new_draft_creates_the_style(self, tmp_path: Path) -> None:
        style_id = store.create_new_draft(tmp_path)
        content = store.read_draft_file(tmp_path, style_id, "STYLE.md")
        store.write_draft_file(
            tmp_path, style_id, "STYLE.md", content.replace("新风格", "我的风格", 1)
        )
        detail = store.save_draft(tmp_path, style_id)
        assert detail.id == style_id and detail.name == "我的风格"
        assert [s.id for s in store.list_styles(tmp_path)] == [style_id]

    def test_invalid_draft_is_rejected_and_nothing_changes(self, tmp_path: Path) -> None:
        style_id = _saved(tmp_path)
        store.open_draft(tmp_path, style_id)
        store.write_draft_file(tmp_path, style_id, "STYLE.md", "frontmatter 被删了")
        with pytest.raises(StyleValidationError) as exc:
            store.save_draft(tmp_path, style_id)
        assert any("frontmatter" in e for e in exc.value.errors)
        assert store.get_style(tmp_path, style_id).files == _files()
        assert store.read_draft_file(tmp_path, style_id, "STYLE.md") == "frontmatter 被删了"

    def test_renaming_to_an_existing_name_is_rejected(self, tmp_path: Path) -> None:
        _saved(tmp_path, "甲")
        other = _saved(tmp_path, "乙")
        store.open_draft(tmp_path, other)
        store.write_draft_file(tmp_path, other, "STYLE.md", _files("甲")["STYLE.md"])
        with pytest.raises(DuplicateStyleNameError):
            store.save_draft(tmp_path, other)
        assert store.get_style(tmp_path, other).name == "乙"

    def test_keeping_its_own_name_is_not_a_conflict(self, tmp_path: Path) -> None:
        style_id = _saved(tmp_path, "甲")
        store.open_draft(tmp_path, style_id)
        store.write_draft_file(tmp_path, style_id, "references/color.md", "改")
        assert store.save_draft(tmp_path, style_id).name == "甲"

    def test_content_planted_by_an_agent_is_rejected_at_save(self, tmp_path: Path) -> None:
        style_id = _saved(tmp_path)
        store.open_draft(tmp_path, style_id)
        draft = draft_dir(tmp_path, style_id)
        outside = tmp_path / "outside.md"
        outside.write_text("x")
        (draft / "references" / "link.md").symlink_to(outside)
        (draft / "references" / "binary.md").write_bytes(b"\xff\xfe\x00bad")
        (draft / "notes.md").write_text("顶层多余文件")
        (draft / "extra").mkdir()
        (draft / "extra" / "a.md").write_text("多余目录")
        (draft / "references" / "huge.md").write_text("x" * 200_001)
        with pytest.raises(StyleValidationError) as exc:
            store.save_draft(tmp_path, style_id)
        text = "\n".join(exc.value.errors)
        for needle in ("link.md", "binary.md", "notes.md", "extra/a.md", "huge.md"):
            assert needle in text
        assert store.get_style(tmp_path, style_id).files == _files()
        assert (draft / "notes.md").exists()

    def test_ds_store_files_are_ignored(self, tmp_path: Path) -> None:
        style_id = _saved(tmp_path)
        store.open_draft(tmp_path, style_id)
        (draft_dir(tmp_path, style_id) / ".DS_Store").write_bytes(b"\x00")
        (draft_dir(tmp_path, style_id) / "references" / ".DS_Store").write_bytes(b"\x00")
        assert store.save_draft(tmp_path, style_id).files == _files()

    def test_failure_while_writing_leaves_the_saved_version_and_draft_intact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        style_id = _saved(tmp_path)
        store.open_draft(tmp_path, style_id)
        store.write_draft_file(tmp_path, style_id, "references/color.md", "改")

        def boom(*_args: object, **_kwargs: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(store, "_write_tree", boom)
        with pytest.raises(OSError):
            store.save_draft(tmp_path, style_id)
        assert store.get_style(tmp_path, style_id).files == _files()
        assert store.read_draft_file(tmp_path, style_id, "references/color.md") == "改"
        assert [p.name for p in styles_root(tmp_path).iterdir()] == [style_id]

    def test_failure_while_swapping_restores_the_old_version(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        style_id = _saved(tmp_path)
        store.open_draft(tmp_path, style_id)
        store.write_draft_file(tmp_path, style_id, "references/color.md", "改")
        real_rename = Path.rename
        calls = {"n": 0}

        def flaky(self: Path, target: Path | str) -> Path:
            calls["n"] += 1
            if calls["n"] == 2:  # old -> backup succeeds, tmp -> final fails
                raise OSError("rename failed")
            return real_rename(self, target)

        monkeypatch.setattr(Path, "rename", flaky)
        with pytest.raises(OSError):
            store.save_draft(tmp_path, style_id)
        monkeypatch.undo()
        assert store.get_style(tmp_path, style_id).files == _files()
        assert [p.name for p in styles_root(tmp_path).iterdir()] == [style_id]
        assert store.read_draft_file(tmp_path, style_id, "references/color.md") == "改"

    def test_save_without_a_draft(self, tmp_path: Path) -> None:
        style_id = _saved(tmp_path)
        with pytest.raises(StyleNotFoundError):
            store.save_draft(tmp_path, style_id)


class TestPruneDraft:
    """agent 用 Bash 可能在草稿里留下用户界面够不着的东西：保存只会 422，又删不掉，必须清掉。"""

    def test_removes_everything_the_api_cannot_address_and_keeps_the_rest(
        self, tmp_path: Path
    ) -> None:
        style_id = _saved(tmp_path)
        store.open_draft(tmp_path, style_id)
        draft = draft_dir(tmp_path, style_id)
        outside = tmp_path / "outside.md"
        outside.write_text("x")
        (draft / "references" / "link.md").symlink_to(outside)
        (draft / "notes.md").write_text("顶层多余文件")
        (draft / "extra").mkdir()
        (draft / "extra" / "a.md").write_text("多余目录")
        (draft / "references" / "sub").mkdir()
        (draft / "references" / "sub" / "b.md").write_text("嵌套目录")
        (draft / "references" / "a b.md").write_text("文件名不合法")
        (draft / "references" / "ok.md").write_text("合法的新文件")

        removed = store.prune_draft(tmp_path, style_id)

        assert sorted(removed) == [
            "extra",
            "notes.md",
            "references/a b.md",
            "references/link.md",
            "references/sub",
        ]
        assert outside.read_text() == "x"
        assert store.draft_status(tmp_path, style_id).files == [
            "STYLE.md",
            "exemplars/e1.json",
            "references/color.md",
            "references/ok.md",
        ]
        assert store.validate_draft(tmp_path, style_id) == []

    def test_the_runtimes_own_directory_is_removed_silently(self, tmp_path: Path) -> None:
        """Claude 运行时会在工作目录里建 `.claude/`：清掉，但不当作「agent 留下的多余文件」报告。"""
        style_id = _saved(tmp_path)
        store.open_draft(tmp_path, style_id)
        draft = draft_dir(tmp_path, style_id)
        (draft / ".claude").mkdir()
        (draft / ".claude" / "settings.local.json").write_text("{}")
        (draft / "notes.md").write_text("多余文件")

        removed = store.prune_draft(tmp_path, style_id)

        assert removed == ["notes.md"]
        assert not (draft / ".claude").exists()
        assert store.validate_draft(tmp_path, style_id) == []

    def test_the_openai_shell_cache_directory_is_removed_silently(self, tmp_path: Path) -> None:
        """OpenAI 运行时的 Shell 在工作目录里建 `.cache/tmp`：同 `.claude/`，静默清掉。"""
        style_id = _saved(tmp_path)
        store.open_draft(tmp_path, style_id)
        draft = draft_dir(tmp_path, style_id)
        (draft / ".cache" / "tmp").mkdir(parents=True)
        (draft / ".cache" / "tmp" / "x").write_text("scratch")
        (draft / "notes.md").write_text("多余文件")

        removed = store.prune_draft(tmp_path, style_id)

        assert removed == ["notes.md"]
        assert not (draft / ".cache").exists()

    def test_a_clean_draft_is_left_alone(self, tmp_path: Path) -> None:
        style_id = _saved(tmp_path)
        store.open_draft(tmp_path, style_id)
        assert store.prune_draft(tmp_path, style_id) == []

    def test_unknown_draft(self, tmp_path: Path) -> None:
        with pytest.raises(StyleNotFoundError):
            store.prune_draft(tmp_path, "nope")


class TestRecoverInterruptedSwaps:
    """TD-58: a kill between the two renames of `_swap` leaves the old version in `.<id>.old-*`."""

    def test_a_missing_style_is_restored_from_its_old_copy(self, tmp_path: Path) -> None:
        style_id = _saved(tmp_path)
        final = style_dir(tmp_path, style_id)
        old = final.with_name(f".{style_id}.old-abc")
        final.rename(old)

        restored = store.recover_interrupted_swaps(tmp_path)

        assert restored == [style_id]
        assert store.get_style(tmp_path, style_id).files == _files()
        assert not old.exists()

    def test_a_missing_draft_is_restored_too(self, tmp_path: Path) -> None:
        style_id = _saved(tmp_path)
        store.open_draft(tmp_path, style_id)
        draft = draft_dir(tmp_path, style_id)
        old = draft.with_name(f".{style_id}.old-abc")
        draft.rename(old)

        assert store.recover_interrupted_swaps(tmp_path) == [style_id]
        assert draft.is_dir() and not old.exists()

    def test_an_old_copy_next_to_an_existing_version_is_dropped(self, tmp_path: Path) -> None:
        style_id = _saved(tmp_path)
        final = style_dir(tmp_path, style_id)
        stale = final.with_name(f".{style_id}.old-abc")
        shutil.copytree(final, stale)

        assert store.recover_interrupted_swaps(tmp_path) == []
        assert not stale.exists()
        assert store.get_style(tmp_path, style_id).files == _files()

    def test_leftover_temp_directories_are_removed_and_unrelated_ones_stay(
        self, tmp_path: Path
    ) -> None:
        style_id = _saved(tmp_path)
        root = styles_root(tmp_path)
        (root / f".{style_id}.tmp-abc").mkdir()
        keep = root / ".something-else"
        keep.mkdir()

        store.recover_interrupted_swaps(tmp_path)

        assert not (root / f".{style_id}.tmp-abc").exists()
        assert keep.is_dir() and style_dir(tmp_path, style_id).is_dir()

    def test_it_is_safe_without_the_directories_and_when_repeated(self, tmp_path: Path) -> None:
        assert store.recover_interrupted_swaps(tmp_path) == []
        style_id = _saved(tmp_path)
        final = style_dir(tmp_path, style_id)
        final.rename(final.with_name(f".{style_id}.old-abc"))
        assert store.recover_interrupted_swaps(tmp_path) == [style_id]
        assert store.recover_interrupted_swaps(tmp_path) == []

    def test_one_unrestorable_directory_does_not_stop_the_others_or_the_caller(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # A bad directory must never keep the app from starting (the call sits in the lifespan).
        first, second = _saved(tmp_path, "甲"), _saved(tmp_path, "乙")
        for style_id in (first, second):
            final = style_dir(tmp_path, style_id)
            final.rename(final.with_name(f".{style_id}.old-abc"))
        real_rename = Path.rename

        def flaky(self: Path, target: Path) -> Path:
            if self.name.startswith(f".{first}."):
                raise PermissionError("read-only")
            return real_rename(self, target)

        monkeypatch.setattr(Path, "rename", flaky)

        with caplog.at_level(logging.ERROR):
            restored = store.recover_interrupted_swaps(tmp_path)

        assert restored == [second]
        assert any("风格" in record.getMessage() for record in caplog.records)
