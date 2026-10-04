"""`engines.render.html.assets`：资产类型、体积、符号链接检查。"""

from __future__ import annotations

from pathlib import Path

from studio.engines.render.html.assets import MAX_ASSET_BYTES, check_assets, list_assets


def _asset(workdir: Path, name: str, size: int = 10) -> Path:
    path = workdir / "animation" / "assets" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def test_allowed_types_pass_and_are_listed(tmp_path: Path) -> None:
    for name in ("a.svg", "b.png", "c.jpg", "d.jpeg", "e.webp"):
        _asset(tmp_path, name)
    assert check_assets(tmp_path) == []
    assert [p.name for p in list_assets(tmp_path)] == [
        "a.svg",
        "b.png",
        "c.jpg",
        "d.jpeg",
        "e.webp",
    ]


def test_disallowed_type_and_oversize_are_errors(tmp_path: Path) -> None:
    _asset(tmp_path, "movie.mp4")
    _asset(tmp_path, "big.png", MAX_ASSET_BYTES + 1)
    errors = check_assets(tmp_path)
    assert any("movie.mp4" in e and "类型" in e for e in errors)
    assert any("big.png" in e and "5 MB" in e for e in errors)


def test_symlink_outside_workspace_is_error_and_not_listed(tmp_path: Path) -> None:
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"x")
    work = tmp_path / "work"
    (work / "animation" / "assets").mkdir(parents=True)
    (work / "animation" / "assets" / "link.png").symlink_to(outside)
    assert any("link.png" in e and "工作区外" in e for e in check_assets(work))
    assert list_assets(work) == []


def test_no_assets_dir(tmp_path: Path) -> None:
    assert check_assets(tmp_path) == []
    assert list_assets(tmp_path) == []
