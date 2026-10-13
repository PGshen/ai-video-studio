"""Codex 运行时：用 ChatGPT 本机登录驱动 `codex exec --json`（ADR 0030，codex-runtime T3）。

每轮一个子进程：新会话 `codex exec ... -`，续会话 `codex exec ... resume <thread_id> -`，提示词
从 stdin 写入；`thread_id` 作为 `resume_ref`（会话表的 `sdk_ref`）。参数在 `codex_args`、
事件转换在 `codex_events`、环境变量在 `codex_env`、业务工具的 MCP 端点在 `codex_mcp`。

- **认证**：只支持本机登录（`api_key_env` 必须为空）；`Usage.auth="login"`，成本按配置单价
  估算（没有单价时 `priced=False`），不参与成本预算。
- **用量**：`turn.completed.usage` 是会话累计值，按 `CodexLedger` 记的上次累计求差；没拿到
  `turn.completed`（取消、出错）时账本标"待校准"，下一轮的差值含那一轮的消耗并标
  `includes_carryover`（与 ClaudeRuntime 同一语义）。
- **阶段提示**：`developer_instructions` 只在建会话时生效。账本记下会话当前生效的提示摘要；
  续会话时提示变了，就把新提示全文放在本轮用户消息前面（`PROMPT_UPDATE`）并更新摘要。
- **失败**：成败只看 `turn.completed`/`turn.failed`；两者都没有就是异常退出，错误里带打码后的
  stderr 尾部（例如 MCP 服务连不上时 codex 只在 stderr 说明原因）。
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import signal
import sys
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from studio import proc
from studio.agent import events
from studio.agent.codex_args import build_args
from studio.agent.codex_cli import desktop_candidates, find_codex
from studio.agent.codex_env import build_env
from studio.agent.codex_events import CodexTurn, convert_event, failure_message, redact
from studio.agent.codex_mcp import TurnToolServer
from studio.agent.codex_procs import descendant_groups, kill_groups
from studio.agent.codex_sandbox import sandbox_args
from studio.agent.exec_policy import codex_sandbox_available, exec_mode
from studio.agent.openai_tools import turn_cost
from studio.agent.runtime import RuntimeFactory, TurnContext
from studio.config import Settings
from studio.config import repo_root as default_repo_root

logger = logging.getLogger(__name__)

PROMPT_UPDATE = (
    "【阶段说明已更新】会话开始时给你的阶段说明已被替换，从本轮起以下面的新说明为准：\n"
    "<stage_instructions>\n{prompt}\n</stage_instructions>\n\n"
)
CANCEL_GRACE_S = 15.0
"""取消时等 codex 响应 SIGINT 的时间（它收尾时还会再发一次模型请求，实测 2–3 秒）。"""
_READ_CHUNK = 1 << 16
_STDERR_KEEP = 16 * 1024
_STDERR_TAIL = 800
_STDERR_NOISE = ("Reading additional input from stdin", "failed to refresh available models")
_IMAGE_SUFFIXES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
_THREAD_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,128}$")
_USAGE_KEYS = ("input_tokens", "cached_input_tokens", "output_tokens")


def prompt_digest(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LedgerEntry:
    usage: dict[str, int]
    """该会话最近一次 `turn.completed` 的累计用量。"""
    unsettled: bool = False
    """之后有一轮没拿到 `turn.completed`，那一轮的消耗还没算进任何一轮。"""
    prompt_digest: str | None = None
    """会话当前生效的阶段提示的摘要。"""


class CodexLedger:
    """每个 codex 会话一个 JSON 文件（`<data_dir>/codex/ledger/<thread_id>.json`）。

    落盘而不是放内存：进程重启后续上的会话，`turn.completed` 仍是从头累计的值。
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, thread_id: str) -> Path | None:
        return self._root / f"{thread_id}.json" if _THREAD_ID_RE.match(thread_id) else None

    def get(self, thread_id: str) -> LedgerEntry | None:
        path = self._path(thread_id)
        if path is None or not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            usage = {key: int(value) for key, value in dict(raw.get("usage") or {}).items()}
            digest = raw.get("prompt_digest")
            return LedgerEntry(
                usage, bool(raw.get("unsettled")), digest if isinstance(digest, str) else None
            )
        except (OSError, ValueError, TypeError, AttributeError):
            return None

    def record(self, thread_id: str, usage: Mapping[str, int]) -> None:
        """记下新的累计用量（同时清掉"待校准"）。"""
        entry = self.get(thread_id)
        self._write(
            thread_id, LedgerEntry(dict(usage), False, entry.prompt_digest if entry else None)
        )

    def mark_unsettled(self, thread_id: str) -> None:
        entry = self.get(thread_id) or LedgerEntry({})
        self._write(thread_id, LedgerEntry(entry.usage, True, entry.prompt_digest))

    def set_prompt(self, thread_id: str, digest: str) -> None:
        entry = self.get(thread_id) or LedgerEntry({})
        self._write(thread_id, LedgerEntry(entry.usage, entry.unsettled, digest))

    def _write(self, thread_id: str, entry: LedgerEntry) -> None:
        path = self._path(thread_id)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        payload = {
            "usage": entry.usage,
            "unsettled": entry.unsettled,
            "prompt_digest": entry.prompt_digest,
        }
        tmp.write_text(json.dumps(payload), encoding="utf-8", newline="")
        tmp.replace(path)


class _NoLedger(CodexLedger):
    """`ephemeral` 运行（单轮调用）：codex 不存会话，也就不记账。"""

    def get(self, thread_id: str) -> LedgerEntry | None:
        return None

    def _write(self, thread_id: str, entry: LedgerEntry) -> None:
        return None


class CodexRuntime:
    def __init__(
        self,
        data_dir: Path,
        binary: Path,
        *,
        environ: Mapping[str, str] | None = None,
        platform: str | None = None,
        cancel_grace_s: float = CANCEL_GRACE_S,
        repo_root: Path | None = None,
        ephemeral: bool = False,
    ) -> None:
        """`ephemeral`：单轮调用（会话命名、连通性测试），`--ephemeral` 不写会话文件、不记账。"""
        self._binary = binary
        self._data_dir = data_dir
        self._repo_root = repo_root if repo_root is not None else default_repo_root()
        self._cancel_grace_s = cancel_grace_s
        self._codex_dir = data_dir / "codex"
        self._ephemeral = ephemeral
        ledger_root = self._codex_dir / "ledger"
        self._ledger = _NoLedger(ledger_root) if ephemeral else CodexLedger(ledger_root)
        self._environ = environ if environ is not None else os.environ
        self._platform = platform or sys.platform

    def _sandbox_args(self, ctx: TurnContext) -> list[str] | None:
        mode = exec_mode(
            platform=self._platform,
            sandbox_available=codex_sandbox_available(self._platform),
            allow_unsandboxed=ctx.allow_unsandboxed_exec,
        )
        return sandbox_args(mode, ctx.workdir, self._repo_root, self._data_dir)

    async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
        if ctx.cancel_token.is_cancelled:
            yield events.TurnEnd(resume_ref=ctx.resume_ref, status="cancelled")
            return
        if ctx.model_profile.api_key_env is not None:
            yield events.TurnEnd(
                resume_ref=ctx.resume_ref,
                status="failed",
                error=(
                    "codex 运行时只支持本机登录（ChatGPT 账号）：模型配置的 API key 环境变量须留空"
                ),
            )
            return

        sandbox = self._sandbox_args(ctx)
        if sandbox is None:
            yield events.TurnEnd(
                resume_ref=ctx.resume_ref,
                status="failed",
                error=(
                    "当前平台没有可用的命令隔离，codex 不能运行；"
                    "如需使用，请在设置里打开「无隔离执行」开关（ADR 0024）"
                ),
            )
            return
        message, digest = self._message(ctx)
        image_dir = self._codex_dir / "tmp" / uuid.uuid4().hex
        turn = CodexTurn(workdir=ctx.workdir.resolve(), call_prefix=uuid.uuid4().hex[:8])
        stderr_tail: collections.deque[bytes] = collections.deque()
        child: asyncio.subprocess.Process | None = None
        try:
            image_paths = _write_images(image_dir, ctx.user_input.images)
            async with TurnToolServer(ctx.tools, ctx.tool_context()) as mcp:
                args = build_args(
                    workdir=turn.workdir,
                    model=ctx.model_profile.model,
                    resume_ref=ctx.resume_ref,
                    system_prompt=ctx.system_prompt,
                    effort=ctx.effort,
                    image_paths=image_paths,
                    extra=[*mcp.args(), *sandbox, *(["--ephemeral"] if self._ephemeral else [])],
                )
                env = build_env(self._environ, platform=self._platform) | mcp.env
                child = await asyncio.create_subprocess_exec(
                    str(self._binary),
                    *args,
                    cwd=turn.workdir,
                    env=env,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    **proc.spawn_kwargs(),
                )
                stderr_task = asyncio.create_task(_drain(child, stderr_tail))
                watcher = asyncio.create_task(self._stop_on_cancel(ctx, child))
                try:
                    await _feed(child, message)
                    async for obj in _json_lines(child):
                        if turn.thread_id is None and obj.get("type") == "thread.started":
                            convert_event(obj, turn)
                            if turn.thread_id:
                                self._ledger.set_prompt(turn.thread_id, digest)
                            continue
                        for event in convert_event(obj, turn):
                            yield event
                    await child.wait()
                    await stderr_task
                finally:
                    watcher.cancel()
        except Exception as exc:
            logger.exception("codex 运行失败")
            if turn.thread_id or ctx.resume_ref:
                self._ledger.mark_unsettled(turn.thread_id or ctx.resume_ref or "")
            yield events.TurnEnd(
                resume_ref=turn.thread_id or ctx.resume_ref,
                status="failed",
                error=f"codex 运行失败：{type(exc).__name__}: {redact(str(exc))}",
            )
            return
        finally:
            if child is not None and child.returncode is None:
                await _force_stop(child)
            shutil.rmtree(image_dir, ignore_errors=True)

        returncode = child.returncode if child is not None else None
        for event in self._finish(ctx, turn, returncode, _stderr_text(stderr_tail)):
            yield event

    def _message(self, ctx: TurnContext) -> tuple[str, str]:
        """本轮写进 stdin 的消息，以及本轮之后会话生效的阶段提示摘要。"""
        digest = prompt_digest(ctx.system_prompt)
        text = ctx.user_input.text
        if ctx.resume_ref is not None:
            entry = self._ledger.get(ctx.resume_ref)
            if entry is not None and entry.prompt_digest not in (None, digest):
                text = PROMPT_UPDATE.format(prompt=ctx.system_prompt) + text
        return text, digest

    async def _stop_on_cancel(self, ctx: TurnContext, child: asyncio.subprocess.Process) -> None:
        await ctx.cancel_token.wait()
        await _stop(child, grace_s=self._cancel_grace_s, platform=self._platform)

    def _finish(
        self, ctx: TurnContext, turn: CodexTurn, returncode: int | None, stderr: str
    ) -> list[events.AgentEvent]:
        thread = turn.thread_id or ctx.resume_ref
        out: list[events.AgentEvent] = []
        if turn.usage is not None and thread:
            out.append(self._usage(ctx, thread, turn.usage))
        elif thread:
            self._ledger.mark_unsettled(thread)

        if ctx.cancel_token.is_cancelled:
            out.append(events.TurnEnd(resume_ref=thread, status="cancelled"))
        elif turn.failure is not None:
            out.append(
                events.TurnEnd(
                    resume_ref=thread, status="failed", error=failure_message(turn.failure)
                )
            )
        elif turn.usage is not None:
            out.append(events.TurnEnd(resume_ref=thread, status="done"))
        else:
            detail = f"：{stderr}" if stderr else ""
            out.append(
                events.TurnEnd(
                    resume_ref=thread,
                    status="failed",
                    error=f"codex 没有返回本轮结果（退出码 {returncode}）{detail}",
                )
            )
        return out

    def _usage(self, ctx: TurnContext, thread: str, cumulative: dict[str, int]) -> events.Usage:
        entry = self._ledger.get(thread) if ctx.resume_ref else None
        previous = entry.usage if entry is not None else {}
        delta = {key: cumulative.get(key, 0) - previous.get(key, 0) for key in _USAGE_KEYS}
        if any(value < 0 for value in delta.values()):
            # The cumulative total went backwards (session reset): count it as this turn's own.
            delta = {key: cumulative.get(key, 0) for key in _USAGE_KEYS}
        carryover = entry is not None and entry.unsettled
        self._ledger.record(thread, cumulative)
        profile = ctx.model_profile
        return events.Usage(
            input_tokens=delta["input_tokens"],
            output_tokens=delta["output_tokens"],
            cache_read_tokens=delta["cached_input_tokens"],
            cost_usd=turn_cost(profile, delta["input_tokens"], delta["output_tokens"]),
            auth="login",
            priced=profile.price_input is not None and profile.price_output is not None,
            includes_carryover=carryover,
        )


async def _stop(child: asyncio.subprocess.Process, *, grace_s: float, platform: str) -> None:
    """取消：先 SIGINT（codex 收尾并收掉自己启动的命令），宽限期内没退出再强杀。

    命令所在的进程组在发信号前记下：codex 退出后它们的父进程变成 1，就找不到了。
    """
    groups = await asyncio.to_thread(descendant_groups, child.pid)
    with contextlib.suppress(ProcessLookupError, OSError):
        if platform == "win32":
            # Windows: the child has its own process group (`proc.spawn_kwargs`); untested there.
            os.kill(child.pid, getattr(signal, "CTRL_BREAK_EVENT", signal.SIGINT))
        else:
            child.send_signal(signal.SIGINT)
    try:
        await asyncio.wait_for(child.wait(), grace_s)
    except TimeoutError:
        logger.warning("codex 在 %.0f 秒内没有响应 SIGINT，强制结束", grace_s)
        await _force_stop(child, groups)
        return
    kill_groups(groups)


async def _force_stop(child: asyncio.subprocess.Process, known: set[int] | None = None) -> None:
    groups = (known or set()) | await asyncio.to_thread(descendant_groups, child.pid)
    await proc.kill_tree(child)
    kill_groups(groups)


def _write_images(directory: Path, images: Sequence[events.ImageData]) -> list[Path]:
    import base64

    paths: list[Path] = []
    for index, image in enumerate(images):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"image-{index}{_IMAGE_SUFFIXES.get(image.media_type, '.png')}"
        path.write_bytes(base64.b64decode(image.data_base64))
        paths.append(path)
    return paths


async def _feed(child: asyncio.subprocess.Process, message: str) -> None:
    assert child.stdin is not None
    with contextlib.suppress(BrokenPipeError, ConnectionResetError):
        child.stdin.write(message.encode("utf-8"))
        await child.stdin.drain()
    child.stdin.close()


async def _json_lines(child: asyncio.subprocess.Process) -> AsyncIterator[dict[str, object]]:
    """stdout 的每一行 JSON；按块读再切行，不受 asyncio 默认 64 KiB 行长限制。"""
    assert child.stdout is not None
    buffer = b""
    while True:
        chunk = await child.stdout.read(_READ_CHUNK)
        if not chunk:
            break
        buffer += chunk
        *lines, buffer = buffer.split(b"\n")
        for line in lines:
            parsed = _parse(line)
            if parsed is not None:
                yield parsed
    parsed = _parse(buffer)
    if parsed is not None:
        yield parsed


def _parse(line: bytes) -> dict[str, object] | None:
    if not line.strip():
        return None
    try:
        obj = json.loads(line)
    except ValueError:
        logger.info("codex stdout（非 JSON）：%s", redact(line[:300].decode(errors="replace")))
        return None
    return obj if isinstance(obj, dict) else None


async def _drain(child: asyncio.subprocess.Process, tail: collections.deque[bytes]) -> None:
    assert child.stderr is not None
    kept = 0
    while chunk := await child.stderr.read(_READ_CHUNK):
        tail.append(chunk)
        kept += len(chunk)
        while kept > _STDERR_KEEP and len(tail) > 1:
            kept -= len(tail.popleft())


def _stderr_text(tail: collections.deque[bytes]) -> str:
    lines = b"".join(tail).decode(errors="replace").splitlines()
    useful = [line for line in lines if line.strip() and not any(n in line for n in _STDERR_NOISE)]
    text = "\n".join(useful)
    if len(text) > _STDERR_TAIL:
        text = "…" + text[-_STDERR_TAIL:]
    return redact(text)


def register_codex(factory: RuntimeFactory, settings: Settings) -> None:
    """找得到 Codex CLI 时注册 `codex` 运行时（ADR 0030 前提 2）；找不到就不注册。"""
    binary = find_codex(settings.codex_bin, desktop_candidates(platform=sys.platform))
    if binary is None:
        logger.info("未找到 Codex CLI（ChatGPT 桌面版或 STUDIO_CODEX_BIN），codex 运行时不可用")
        return
    data_dir = settings.data_dir
    factory.register("codex", lambda: CodexRuntime(data_dir, binary))
