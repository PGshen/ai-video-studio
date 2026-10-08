"""风格目录存储里的截图（计划 style-screenshots T2）：草稿、保存、复制、清理。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from studio.styles import store
from studio.styles.layout import draft_dir, style_dir
from studio.styles.screenshots import MAX_SCREENSHOTS, is_screenshot_name
from studio.styles.store import StyleNotFoundError, StylePathError, StyleValidationError
from studio.styles.validate import StyleFiles

ENTRY = "---\nname: 暖纸双色\ndescription: 暖色双色风格\ncategory: 概念传记\n---\n\n# 暖纸双色\n"


def _files(name: str = "暖纸双色") -> StyleFiles:
    return {"STYLE.md": ENTRY.replace("暖纸双色", name)}


def _saved(data: Path, name: str = "暖纸双色") -> str:
    return store.import_style(data, _files(name)).id


def _shot(label: str) -> bytes:
    return f"image-{label}".encode()


def _draft_with(data: Path, *labels: str) -> tuple[str, list[str]]:
    style_id = _saved(data)
    store.open_draft(data, style_id)
    return style_id, [store.add_draft_screenshot(data, style_id, _shot(x)) for x in labels]


class TestDraftOperations:
    def test_add_appends_with_sequential_numbers(self, tmp_path: Path) -> None:
        style_id, names = _draft_with(tmp_path, "a", "b", "c")
        assert [n[:3] for n in names] == ["001", "002", "003"]
        assert all(is_screenshot_name(n) for n in names)
        assert store.draft_status(tmp_path, style_id).screenshots == names
        assert (draft_dir(tmp_path, style_id) / "screenshots" / names[0]).read_bytes() == _shot("a")

    def test_the_13th_screenshot_is_rejected(self, tmp_path: Path) -> None:
        style_id, _ = _draft_with(tmp_path, *[str(i) for i in range(MAX_SCREENSHOTS)])
        with pytest.raises(StyleValidationError, match=str(MAX_SCREENSHOTS)):
            store.add_draft_screenshot(tmp_path, style_id, _shot("one-too-many"))
        assert len(store.draft_status(tmp_path, style_id).screenshots) == MAX_SCREENSHOTS

    def test_delete_renumbers_the_rest(self, tmp_path: Path) -> None:
        style_id, names = _draft_with(tmp_path, "a", "b", "c")
        store.delete_draft_screenshot(tmp_path, style_id, names[0])
        remaining = store.draft_status(tmp_path, style_id).screenshots
        assert [n[:3] for n in remaining] == ["001", "002"]
        assert [n[4:] for n in remaining] == [names[1][4:], names[2][4:]]

    def test_delete_of_a_missing_screenshot_is_not_found(self, tmp_path: Path) -> None:
        style_id, _ = _draft_with(tmp_path, "a")
        with pytest.raises(StyleNotFoundError):
            store.delete_draft_screenshot(tmp_path, style_id, "009-aaaaaaaaaaaa.webp")

    def test_reorder_moves_the_cover(self, tmp_path: Path) -> None:
        style_id, names = _draft_with(tmp_path, "a", "b", "c")
        store.reorder_draft_screenshots(tmp_path, style_id, [names[2], names[0], names[1]])
        result = store.draft_status(tmp_path, style_id).screenshots
        assert [n[4:] for n in result] == [names[2][4:], names[0][4:], names[1][4:]]
        assert [n[:3] for n in result] == ["001", "002", "003"]
        root = draft_dir(tmp_path, style_id) / "screenshots"
        assert (root / result[0]).read_bytes() == _shot("c")

    @pytest.mark.parametrize(
        "pick", [lambda n: n[:2], lambda n: [*n, n[0]], lambda n: [*n[:2], "x"]]
    )
    def test_reorder_requires_a_permutation(
        self, tmp_path: Path, pick: Callable[[list[str]], list[str]]
    ) -> None:
        style_id, names = _draft_with(tmp_path, "a", "b", "c")
        with pytest.raises(StyleValidationError):
            store.reorder_draft_screenshots(tmp_path, style_id, pick(names))
        assert store.draft_status(tmp_path, style_id).screenshots == names

    def test_operations_need_a_draft(self, tmp_path: Path) -> None:
        style_id = _saved(tmp_path)
        with pytest.raises(StyleNotFoundError):
            store.add_draft_screenshot(tmp_path, style_id, _shot("a"))

    def test_a_symlinked_screenshots_directory_is_refused(self, tmp_path: Path) -> None:
        style_id, _ = _draft_with(tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()
        (draft_dir(tmp_path, style_id) / "screenshots").symlink_to(outside)
        with pytest.raises(StylePathError):
            store.add_draft_screenshot(tmp_path, style_id, _shot("a"))
        assert list(outside.iterdir()) == []


class TestDraftLifecycle:
    def test_open_draft_copies_saved_screenshots(self, tmp_path: Path) -> None:
        style_id, names = _draft_with(tmp_path, "a", "b")
        store.save_draft(tmp_path, style_id)
        store.discard_draft(tmp_path, style_id)
        status = store.open_draft(tmp_path, style_id)
        assert status.screenshots == names
        assert not status.dirty

    def test_only_a_screenshot_change_makes_the_draft_dirty(self, tmp_path: Path) -> None:
        style_id = _saved(tmp_path)
        assert not store.open_draft(tmp_path, style_id).dirty
        store.add_draft_screenshot(tmp_path, style_id, _shot("a"))
        assert store.draft_status(tmp_path, style_id).dirty

    def test_save_installs_screenshots_and_removes_the_draft(self, tmp_path: Path) -> None:
        style_id, names = _draft_with(tmp_path, "a", "b")
        detail = store.save_draft(tmp_path, style_id)
        assert detail.screenshots == names
        assert (style_dir(tmp_path, style_id) / "screenshots" / names[1]).read_bytes() == _shot("b")
        assert not draft_dir(tmp_path, style_id).exists()

    def test_deleting_all_screenshots_and_saving_removes_them(self, tmp_path: Path) -> None:
        style_id, names = _draft_with(tmp_path, "a")
        store.save_draft(tmp_path, style_id)
        store.open_draft(tmp_path, style_id)
        store.delete_draft_screenshot(tmp_path, style_id, names[0])
        assert store.save_draft(tmp_path, style_id).screenshots == []

    def test_discard_leaves_the_saved_screenshots_untouched(self, tmp_path: Path) -> None:
        style_id, names = _draft_with(tmp_path, "a")
        store.save_draft(tmp_path, style_id)
        store.open_draft(tmp_path, style_id)
        store.add_draft_screenshot(tmp_path, style_id, _shot("b"))
        store.delete_draft_screenshot(tmp_path, style_id, names[0])
        store.discard_draft(tmp_path, style_id)
        assert store.get_style(tmp_path, style_id).screenshots == names

    def test_save_fails_when_the_screenshots_directory_has_bad_entries(
        self, tmp_path: Path
    ) -> None:
        style_id, _ = _draft_with(tmp_path, "a")
        (draft_dir(tmp_path, style_id) / "screenshots" / "notes.txt").write_text("x")
        with pytest.raises(StyleValidationError, match="screenshots/notes.txt"):
            store.save_draft(tmp_path, style_id)
        assert store.validate_draft(tmp_path, style_id)


class TestReadingAndCopying:
    def test_summary_cover_is_the_first_screenshot(self, tmp_path: Path) -> None:
        style_id, names = _draft_with(tmp_path, "a", "b")
        store.save_draft(tmp_path, style_id)
        [summary] = store.list_styles(tmp_path)
        assert summary.cover == names[0]

    def test_summary_without_screenshots_has_no_cover(self, tmp_path: Path) -> None:
        _saved(tmp_path)
        assert store.list_styles(tmp_path)[0].cover is None

    def test_a_new_unsaved_style_shows_its_draft_cover(self, tmp_path: Path) -> None:
        style_id = store.create_new_draft(tmp_path)
        name = store.add_draft_screenshot(tmp_path, style_id, _shot("a"))
        [summary] = store.list_styles(tmp_path)
        assert summary.is_new
        assert summary.cover == name

    def test_style_files_never_include_screenshots(self, tmp_path: Path) -> None:
        style_id, _ = _draft_with(tmp_path, "a")
        store.save_draft(tmp_path, style_id)
        assert set(store.read_style_files(tmp_path, style_id)) == {"STYLE.md"}
        assert set(store.get_style(tmp_path, style_id).files) == {"STYLE.md"}

    def test_duplicate_copies_screenshots(self, tmp_path: Path) -> None:
        style_id, names = _draft_with(tmp_path, "a", "b")
        store.save_draft(tmp_path, style_id)
        copy = store.duplicate_style(tmp_path, style_id)
        assert copy.screenshots == names
        assert (style_dir(tmp_path, copy.id) / "screenshots" / names[0]).read_bytes() == _shot("a")

    def test_delete_style_removes_screenshots(self, tmp_path: Path) -> None:
        style_id, _ = _draft_with(tmp_path, "a")
        store.save_draft(tmp_path, style_id)
        store.delete_style(tmp_path, style_id)
        assert not style_dir(tmp_path, style_id).exists()

    def test_screenshot_path_for_saved_and_draft(self, tmp_path: Path) -> None:
        style_id, names = _draft_with(tmp_path, "a")
        draft_path = store.screenshot_path(tmp_path, style_id, names[0], draft=True)
        assert draft_path.read_bytes() == _shot("a")
        store.save_draft(tmp_path, style_id)
        saved_path = store.screenshot_path(tmp_path, style_id, names[0], draft=False)
        assert saved_path.read_bytes() == _shot("a")

    @pytest.mark.parametrize("bad", ["../STYLE.md", "STYLE.md", "x.webp", ""])
    def test_screenshot_path_rejects_bad_names(self, tmp_path: Path, bad: str) -> None:
        style_id, _ = _draft_with(tmp_path, "a")
        with pytest.raises(StylePathError):
            store.screenshot_path(tmp_path, style_id, bad, draft=True)

    def test_screenshot_path_of_a_missing_file_is_not_found(self, tmp_path: Path) -> None:
        style_id, _ = _draft_with(tmp_path, "a")
        with pytest.raises(StyleNotFoundError):
            store.screenshot_path(tmp_path, style_id, "009-aaaaaaaaaaaa.webp", draft=True)

    def test_screenshot_path_refuses_a_symlinked_file(self, tmp_path: Path) -> None:
        style_id, _ = _draft_with(tmp_path)
        secret = tmp_path / "secret"
        secret.write_bytes(b"secret")
        link = draft_dir(tmp_path, style_id) / "screenshots" / "001-aaaaaaaaaaaa.webp"
        link.parent.mkdir(exist_ok=True)
        link.symlink_to(secret)
        with pytest.raises((StylePathError, StyleNotFoundError)):
            store.screenshot_path(tmp_path, style_id, link.name, draft=True)


class TestPrune:
    def test_valid_screenshots_survive_and_bad_entries_are_removed(self, tmp_path: Path) -> None:
        style_id, names = _draft_with(tmp_path, "a")
        root = draft_dir(tmp_path, style_id) / "screenshots"
        (root / "sub").mkdir()
        (root / "link.webp").symlink_to(root / names[0])
        (root / "notes.txt").write_text("x")
        removed = store.prune_draft(tmp_path, style_id)
        assert sorted(removed) == [
            "screenshots/link.webp",
            "screenshots/notes.txt",
            "screenshots/sub",
        ]
        assert sorted(p.name for p in root.iterdir()) == names

    def test_a_screenshots_file_or_symlink_is_removed_entirely(self, tmp_path: Path) -> None:
        style_id, _ = _draft_with(tmp_path)
        target = draft_dir(tmp_path, style_id) / "screenshots"
        target.write_text("not a directory")
        assert store.prune_draft(tmp_path, style_id) == ["screenshots"]
        assert not target.exists()
