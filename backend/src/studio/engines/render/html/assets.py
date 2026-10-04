"""`animation/assets/*` 的类型、体积与符号链接检查。"""

from __future__ import annotations

from pathlib import Path

ALLOWED_SUFFIXES = (".svg", ".png", ".jpg", ".jpeg", ".webp")
MAX_ASSET_BYTES = 5 * 1024 * 1024


def _assets_dir(workdir: Path) -> Path:
    return workdir / "animation" / "assets"


def _escapes_workspace(path: Path, workdir: Path) -> bool:
    return not path.resolve().is_relative_to(workdir.resolve())


def list_assets(workdir: Path) -> list[Path]:
    """可供页面使用的资产（类型合法、不指向工作区外），按文件名排序。"""
    directory = _assets_dir(workdir)
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file()
        and path.suffix.lower() in ALLOWED_SUFFIXES
        and not _escapes_workspace(path, workdir)
    )


def check_assets(workdir: Path) -> list[str]:
    directory = _assets_dir(workdir)
    if not directory.is_dir():
        return []
    errors: list[str] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        rel = path.relative_to(workdir).as_posix()
        if _escapes_workspace(path, workdir):
            errors.append(f"资产 {rel} 是指向工作区外的链接，不允许使用")
        elif path.suffix.lower() not in ALLOWED_SUFFIXES:
            errors.append(f"资产 {rel} 的类型不允许（只支持 {'、'.join(ALLOWED_SUFFIXES)}）")
        elif path.stat().st_size > MAX_ASSET_BYTES:
            errors.append(f"资产 {rel} 超过 5 MB 上限")
    return errors
