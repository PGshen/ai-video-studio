"""OpenAI 路径 Shell 的 macOS `sandbox-exec` 沙箱（M1x T9，TD-20）。

纯函数测试（Seatbelt 配置生成、平台判断）所有平台都跑；真实执行测试只在 macOS 上跑：
沙箱实现本身只存在于 macOS（`/usr/bin/sandbox-exec`），计划 T9 已写明这一 skipif 理由。
"""

from __future__ import annotations

import dataclasses
import os
import sys
import uuid
from pathlib import Path

import pytest
from agents import RunContextWrapper, ShellCallData, ShellCommandRequest, ShellResult
from agents.tool import ShellActionRequest

from studio.agent.openai_runtime import native_shell_supported
from studio.agent.sandbox_paths import sensitive_home_dirs
from studio.agent.shell import LocalShellExecutor
from studio.agent.shell_sandbox import (
    SANDBOX_EXEC,
    sandbox_available,
    sandbox_tmpdir,
    seatbelt_profile,
)
from studio.config import repo_root
from studio.db.repo.profiles import ModelProfileValue

_OPENAI = ModelProfileValue(
    id="p-gpt",
    name="gpt",
    provider="openai",
    model="gpt-test",
    runtime="openai",
    base_url=None,
    api_key_env="TEST_OPENAI_KEY",
    supports_vision=True,
    price_input=None,
    price_output=None,
    max_cost_per_turn=None,
    max_steps_per_turn=None,
)

darwin_only = pytest.mark.macos_only("sandbox-exec 只存在于 macOS（计划 M1x T9）")
seatbelt_profile_text = pytest.mark.macos_only(
    "Seatbelt profile 只在 macOS 上生成和使用；断言按 POSIX 路径写，Windows 路径里的反斜杠会被转义"
)


def _lines(profile: str) -> list[str]:
    return [line.strip() for line in profile.splitlines() if line.strip()]


def _index(lines: list[str], prefix: str) -> int:
    return next(i for i, line in enumerate(lines) if line.startswith(prefix))


class TestSeatbeltProfile:
    @seatbelt_profile_text
    def test_policy_shape_and_order(self, tmp_path: Path) -> None:
        workdir = tmp_path / "repo" / "data" / "projects" / "p1"
        workdir.mkdir(parents=True)
        repo, data = tmp_path / "repo", tmp_path / "repo" / "data"

        lines = _lines(seatbelt_profile(workdir, [repo, data]))

        assert lines[0] == "(version 1)"
        assert "(allow default)" in lines
        assert "(deny network*)" in lines
        w = str(workdir.resolve())
        deny_read = _index(lines, "(deny file-read*")
        allow_read = _index(lines, "(allow file-read*")
        # Seatbelt: the later rule wins, so the workdir re-allow must come after the deny.
        assert deny_read < allow_read
        assert f'(subpath "{repo.resolve()}")' in lines[deny_read]
        assert f'(subpath "{data.resolve()}")' in lines[deny_read]
        assert f'(subpath "{w}")' in lines[allow_read]
        deny_write = lines.index("(deny file-write*)")
        allow_write = _index(lines, "(allow file-write*")
        assert deny_write < allow_write
        for literal in (
            f'(subpath "{w}")',
            f'(subpath "{sandbox_tmpdir(workdir.resolve())}")',
            '(literal "/dev/null")',
            '(literal "/dev/tty")',
            '(subpath "/dev/fd")',
        ):
            assert literal in lines[allow_write]

    @seatbelt_profile_text
    def test_paths_are_realpaths(self, tmp_path: Path) -> None:
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)

        profile = seatbelt_profile(link, [link])

        assert f'"{link}"' not in profile
        assert f'(subpath "{real.resolve()}")' in profile

    def test_no_deny_read_rule_when_list_empty(self, tmp_path: Path) -> None:
        lines = _lines(seatbelt_profile(tmp_path, []))

        assert not any(line.startswith("(deny file-read*") for line in lines)
        assert "(deny network*)" in lines
        assert "(deny file-write*)" in lines

    @pytest.mark.posix_only('目录名里的 `"` 在 Windows 上不合法')
    def test_quotes_and_backslashes_are_escaped(self, tmp_path: Path) -> None:
        odd = tmp_path / 'we"ird\\dir'
        odd.mkdir()

        profile = seatbelt_profile(odd, [])

        assert f'(subpath "{tmp_path.resolve()}/we\\"ird\\\\dir")' in profile

    def test_sandbox_tmpdir_is_under_workspace_cache(self, tmp_path: Path) -> None:
        assert sandbox_tmpdir(tmp_path) == tmp_path / ".cache" / "tmp"


class TestSandboxAvailable:
    def test_non_darwin_is_unavailable(self, tmp_path: Path) -> None:
        exe = tmp_path / "sandbox-exec"
        exe.touch()
        assert not sandbox_available(platform="linux", sandbox_exec=exe)
        assert not sandbox_available(platform="win32", sandbox_exec=exe)

    def test_darwin_requires_the_binary(self, tmp_path: Path) -> None:
        exe = tmp_path / "sandbox-exec"
        assert not sandbox_available(platform="darwin", sandbox_exec=exe)
        exe.touch()
        assert sandbox_available(platform="darwin", sandbox_exec=exe)

    def test_defaults_use_this_machine(self) -> None:
        expected = sys.platform == "darwin" and SANDBOX_EXEC.exists()
        assert sandbox_available() is expected

    def test_native_shell_fails_closed_without_sandbox(self) -> None:
        assert native_shell_supported(_OPENAI, sandbox_available=lambda: True)
        assert not native_shell_supported(_OPENAI, sandbox_available=lambda: False)
        gateway = dataclasses.replace(_OPENAI, base_url="https://openrouter.ai/api/v1")
        assert not native_shell_supported(gateway, sandbox_available=lambda: True)


# ---- real sandbox-exec runs (macOS only) ---------------------------------------


def _request(commands: list[str]) -> ShellCommandRequest:
    data = ShellCallData(call_id="s1", action=ShellActionRequest(commands=commands))
    return ShellCommandRequest(ctx_wrapper=RunContextWrapper(context=None), data=data)


@dataclasses.dataclass
class _Layout:
    repo: Path
    data: Path
    workdir: Path
    sibling: Path


@pytest.fixture
def layout(tmp_path: Path) -> _Layout:
    """The real layout: data dir inside the repo root, workspaces under data/projects."""
    repo = tmp_path / "repo"
    data = repo / "data"
    workdir = data / "projects" / "p1"
    sibling = data / "projects" / "p2"
    workdir.mkdir(parents=True)
    sibling.mkdir(parents=True)
    (repo / "backend").mkdir()
    (repo / "backend" / ".env").write_text("OPENAI_API_KEY=sk-secret\n")
    (sibling / "secret.md").write_text("other project\n")
    (data / "studio.db").write_text("db\n")
    (workdir / "notes.md").write_text("hello workspace\n")
    (workdir / "upstream").mkdir()
    (workdir / "upstream" / "topic.md").write_text("upstream copy\n")
    return _Layout(repo=repo, data=data, workdir=workdir, sibling=sibling)


async def _sh(layout: _Layout, command: str) -> tuple[int | None, str, str]:
    executor = LocalShellExecutor(
        layout.workdir, set(), deny_read=[layout.repo, layout.data], environ=os.environ
    )
    result: ShellResult = await executor(_request([command]))
    (output,) = result.output
    return output.exit_code, output.stdout, output.stderr


@darwin_only
class TestSandboxedExecution:
    async def test_write_and_read_workspace(self, layout: _Layout) -> None:
        code, out, _ = await _sh(layout, "echo written > new.md && cat new.md notes.md")
        assert code == 0
        assert out == "written\nhello workspace\n"
        assert (layout.workdir / "new.md").read_text() == "written\n"

    async def test_ls_and_upstream_readable(self, layout: _Layout) -> None:
        code, out, _ = await _sh(layout, "ls && cat upstream/topic.md && ls /usr/bin | head -1")
        assert code == 0
        assert "notes.md" in out and "upstream copy" in out

    async def test_repo_env_unreadable(self, layout: _Layout) -> None:
        code, out, err = await _sh(layout, f"cat {layout.repo / 'backend' / '.env'}")
        assert code != 0
        assert "sk-secret" not in out
        assert "Operation not permitted" in err

    async def test_relative_escape_to_repo_unreadable(self, layout: _Layout) -> None:
        code, out, _ = await _sh(layout, "cat ../../../backend/.env")
        assert code != 0 and "sk-secret" not in out

    async def test_other_project_and_db_unreadable(self, layout: _Layout) -> None:
        code, out, _ = await _sh(layout, f"cat {layout.sibling / 'secret.md'}")
        assert code != 0 and "other project" not in out
        code, out, _ = await _sh(layout, f"cat {layout.data / 'studio.db'}")
        assert code != 0 and "db" not in out

    async def test_symlink_out_of_workspace_unreadable(self, layout: _Layout) -> None:
        code, out, _ = await _sh(layout, "ln -s ../p2 peek && cat peek/secret.md")
        assert code != 0 and "other project" not in out

    async def test_real_repo_file_unreadable(self, tmp_path: Path) -> None:
        """The actual repo root (config.repo_root()) is denied too, as in production."""
        workdir = tmp_path / "w"
        workdir.mkdir()
        executor = LocalShellExecutor(workdir, set(), deny_read=[repo_root()])
        result = await executor(_request([f"cat {repo_root() / 'AGENTS.md'}"]))
        assert result.output[0].exit_code != 0
        assert "AGENTS.md" in result.output[0].stderr

    async def test_sensitive_home_dir_unreadable(self, tmp_path: Path) -> None:
        """TD-27: a credentials directory under the home dir is denied like the repo root."""
        home = tmp_path / "home"
        (home / ".ssh").mkdir(parents=True)
        (home / ".ssh" / "id_rsa").write_text("PRIVATE-KEY-MATERIAL\n")
        workdir = tmp_path / "w"
        workdir.mkdir()
        executor = LocalShellExecutor(workdir, set(), deny_read=sensitive_home_dirs(home))

        result = await executor(_request([f"cat {home / '.ssh' / 'id_rsa'}"]))

        assert result.output[0].exit_code != 0
        assert "PRIVATE-KEY-MATERIAL" not in result.output[0].stdout

    async def test_write_outside_workspace_fails(self, layout: _Layout) -> None:
        home_file = Path.home() / f".studio-sandbox-probe-{uuid.uuid4().hex}"
        try:
            code, _, err = await _sh(layout, f"touch {home_file}")
            assert code != 0 and "Operation not permitted" in err
            assert not home_file.exists()
        finally:
            home_file.unlink(missing_ok=True)
        code, _, _ = await _sh(layout, f"touch {layout.sibling / 'x'}")
        assert code != 0 and not (layout.sibling / "x").exists()
        code, _, _ = await _sh(layout, "touch /tmp/studio-sandbox-probe")
        assert code != 0

    async def test_network_denied(self, layout: _Layout) -> None:
        code, _, _ = await _sh(layout, "curl -sS -m 5 -o /dev/null https://example.com")
        assert code != 0
        code, _, _ = await _sh(layout, "curl -sS -m 5 -o /dev/null http://1.1.1.1")
        assert code != 0

    async def test_launchservices_mach_lookup_denied(self, layout: _Layout) -> None:
        """`lsappinfo front` 靠 mach-lookup 联系 launchservicesd 才能拿到真实的
        前台 app 信息；不堵这个洞的话 `(deny network*)` 挡不住经 LaunchServices
        间接指使沙箱外进程联网（review 发现）。`lsappinfo` 本身即使拿不到回复
        也以退出码 0 收场（拿到的是 `[ NULL ]`），所以这里断言输出内容，不
        断言退出码——mach-lookup 被拒时读不到真实的 ASN 信息。"""
        code, out, _ = await _sh(layout, "lsappinfo front")
        assert code == 0
        assert "ASN:" not in out

    async def test_open_exec_denied(self, layout: _Layout) -> None:
        """`/usr/bin/open` 能把 URL 交给未被沙箱管住的默认浏览器打开，等于绕开
        `(deny network*)`（review 发现）。"""
        code, _, _ = await _sh(layout, "open https://example.com")
        assert code != 0

    async def test_osascript_exec_denied(self, layout: _Layout) -> None:
        """`osascript` 能发送 Apple Event，同样是绕开 `(deny network*)` 的旁路
        （review 发现）。"""
        code, _, _ = await _sh(layout, "osascript -e 'tell application \"Finder\" to activate'")
        assert code != 0

    async def test_python3_runs(self, layout: _Layout) -> None:
        code, out, _ = await _sh(layout, "python3 -c 'print(1)'")
        assert code == 0 and out == "1\n"

    async def test_tmpdir_points_at_sandbox_tmp_and_is_writable(self, layout: _Layout) -> None:
        tmp = sandbox_tmpdir(layout.workdir.resolve())
        code, out, _ = await _sh(
            layout,
            'echo "$TMPDIR"; echo t > "$TMPDIR/t" && cat "$TMPDIR/t"; '
            "python3 -c 'import tempfile; print(tempfile.gettempdir())'",
        )
        assert code == 0
        assert out.splitlines() == [str(tmp), "t", str(tmp)]
        assert (tmp / "t").read_text() == "t\n"

    async def test_std_streams_by_path(self, layout: _Layout) -> None:
        code, out, err = await _sh(layout, "echo o > /dev/stdout; echo e > /dev/stderr")
        assert code == 0 and out == "o\n" and err == "e\n"


class TestSeatbeltProfileExtraReads:
    @seatbelt_profile_text
    def test_extra_read_paths_are_allowed_after_the_deny(self, tmp_path: Path) -> None:
        workdir = tmp_path / "repo" / "data" / "projects" / "p1"
        workdir.mkdir(parents=True)
        venv = tmp_path / "repo" / "backend" / ".venv"
        venv.mkdir(parents=True)

        lines = _lines(seatbelt_profile(workdir, [tmp_path / "repo"], allow_read=[venv]))

        deny = _index(lines, "(deny file-read*")
        extra = next(
            i
            for i, line in enumerate(lines)
            if str(venv.resolve()) in line and "allow file-read*" in line
        )
        assert deny < extra

    def test_no_extra_rule_by_default(self, tmp_path: Path) -> None:
        workdir = tmp_path / "w"
        workdir.mkdir()
        lines = _lines(seatbelt_profile(workdir, []))
        assert sum(line.startswith("(allow file-read*") for line in lines) == 1
