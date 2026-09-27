"""TurnRunner：一轮对话的完整生命周期（设计 §4.4、§7）。

一轮：`user_edit` 快照 → 刷新 `upstream/` → 构建前言 → `run_turn` 事件处理 →
结束（越界检查 → 快照 → 写 turn 状态 → 发布 `turn_status`）。任何结束方式
（完成、失败、取消、超预算、运行时或本模块内部的异常、task 被取消）都走同一个
`_finish`：**先快照、后改状态**。

事件处理：持久事件（`text`/`tool_call`/`tool_result`/`notice`/`error`/`snapshot`）
先分配会话内 `seq` 落库（`repo.turns.append_event`），再带 `seq` 发布到总线；
`text_delta`、`workspace_changed`、`turn_status` 只发布。

调度：同一会话同时最多一个 `queued`/`running` 的 turn（否则 `SessionBusyError`）；
全局最多 `settings.max_concurrent_turns` 个运行中的 turn，其余按 FIFO 排队；
另外**同一项目同时只运行一个 turn**——各阶段共用一个工作区，两个 turn 并行时
一方的越界检查会把另一方的合法写入当成越界还原（评审关注点 4）。
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine

from studio.agent import events, stage_flow
from studio.agent.bus import BusEvent, SessionBus
from studio.agent.preamble import (
    GUARD_RESTORED_NOTICE,
    build_preamble,
    compose_user_text,
    gather_preamble_inputs,
)
from studio.agent.runtime import Budget, CancelToken, RuntimeFactory, TurnContext, UserInput
from studio.agent.stage import StageDefinition, StageRegistry
from studio.config import Settings
from studio.db.repo import turns as turns_repo
from studio.db.repo.profiles import ModelProfileValue, get_model_profile_by_id
from studio.db.repo.sessions import SessionValue, get_session
from studio.db.repo.snapshots import latest_snapshot
from studio.workspace import (
    BlobStore,
    Manifest,
    create_snapshot,
    files,
    guard,
    materialize_upstream,
    project_dir,
    scan,
    upstream_drift,
)

logger = logging.getLogger(__name__)

TOOL_RESULT_MAX_CHARS = 8000
"""落库的工具结果文本/工具参数字符串的上限；超出部分截断（设计 §3.1 说明）。"""


class SessionBusyError(Exception):
    """会话已有 `queued`/`running` 的 turn（API 映射为 409）。"""


class SessionNotFoundError(LookupError):
    pass


def _truncate(text: str) -> tuple[str, bool]:
    if len(text) <= TOOL_RESULT_MAX_CHARS:
        return text, False
    return text[:TOOL_RESULT_MAX_CHARS] + "…（已截断）", True


def _truncate_args(args: dict[str, object]) -> dict[str, object]:
    return {k: _truncate(v)[0] if isinstance(v, str) else v for k, v in args.items()}


@dataclass
class _Job:
    turn_id: str
    session: SessionValue
    project_id: str
    stage: StageDefinition
    profile: ModelProfileValue
    user_input: UserInput
    cancel_token: CancelToken = field(default_factory=CancelToken)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None


@dataclass
class _State:
    """一轮运行中累积的状态，`_finish` 据此收尾。"""

    before: Manifest | None = None
    upstream_ids: dict[str, str | None] = field(default_factory=dict)
    sources: dict[str, Manifest | None] | None = None
    tool_writes: dict[str, str] = field(default_factory=dict)
    pending_tool_paths: list[str] = field(default_factory=list)
    calls: dict[str, events.ToolCall] = field(default_factory=dict)
    steps: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cost_advisory: bool = False
    budget_exceeded: bool = False
    end: events.TurnEnd | None = None
    status: str | None = None
    """异常路径强制的最终状态（`failed`/`cancelled`），优先于 `end.status`。"""
    error: str | None = None

    def final_status(self) -> tuple[str, str | None]:
        # Budget wins over everything: once exceeded, the runner itself stopped the
        # turn, so a forced task.cancel() or an error raised while stopping is a
        # consequence, not the cause.
        if self.budget_exceeded:
            return "budget_exceeded", self.error
        if self.status is not None:
            return self.status, self.error
        if self.end is not None:
            return self.end.status, self.end.error
        return "failed", "运行时没有产出 TurnEnd 就结束了"


class TurnRunner:
    def __init__(
        self,
        engine: Engine,
        blobs: BlobStore,
        registry: StageRegistry,
        runtime_factory: RuntimeFactory,
        bus: SessionBus,
        settings: Settings,
        *,
        cancel_grace_seconds: float = 10.0,
    ) -> None:
        self._engine = engine
        self._blobs = blobs
        self._registry = registry
        self._factory = runtime_factory
        self._bus = bus
        self._settings = settings
        self._cancel_grace_seconds = cancel_grace_seconds
        self._jobs: dict[str, _Job] = {}
        self._queue: deque[_Job] = deque()
        self._running: dict[str, _Job] = {}

    # ---- public API ---------------------------------------------------

    async def start_turn(self, session_id: str, user_input: UserInput) -> str:
        """创建 turn 并排队；返回 turn id。会话忙时抛 `SessionBusyError`。"""
        session = get_session(self._engine, session_id)
        if session is None:
            raise SessionNotFoundError(session_id)
        if session.project_id is None:
            raise ValueError("M1 只支持属于项目的会话")
        stage = self._registry.get(session.stage)
        profile = get_model_profile_by_id(self._engine, session.model_profile_id)
        if profile is None:
            raise LookupError(f"模型配置不存在：{session.model_profile_id}")

        turn = turns_repo.create_turn_if_session_idle(self._engine, session_id, user_input.text)
        if turn is None:
            raise SessionBusyError(session_id)
        job = _Job(turn.id, session, session.project_id, stage, profile, user_input)
        self._jobs[turn.id] = job
        self._queue.append(job)
        self._publish_status(job, "queued")
        self._schedule()
        return turn.id

    def cancel(self, turn_id: str) -> bool:
        """取消排队或运行中的 turn；turn 不在本进程中时返回 `False`。

        必须在事件循环线程里调用（用到 `loop.call_later` 安排宽限期后的强制取消）。
        """
        job = self._jobs.get(turn_id)
        if job is None:
            return False
        if job in self._queue:
            self._queue.remove(job)
            self._finish_turn_row(
                job,
                status="cancelled",
                end_snapshot_id=None,
                usage=None,
                cost_usd=None,
                error=None,
                resume_ref=None,
            )
            self._publish_status(job, "cancelled")
            self._release(job)
            return True
        self._request_stop(job)
        return True

    async def wait(self, turn_id: str) -> None:
        """等待 turn 结束（测试和 API 用）；未知或已结束的 turn 立即返回。"""
        job = self._jobs.get(turn_id)
        if job is not None:
            await job.done.wait()

    def is_project_busy(self, project_id: str) -> bool:
        return any(job.project_id == project_id for job in self._running.values())

    def recover_on_startup(self) -> None:
        """设计 §4.4 第 8 步：上次进程遗留的 `running`/`queued` turn → `interrupted`。

        `running` 的 turn 先做一份 `partial` 快照（产物永远不丢，§7），再改状态；
        没有越界检查（本轮工具写入记录已随进程丢失）。`queued` 的 turn 从未
        开始，排队信息只在内存里，同样标记为 `interrupted`，否则会话会一直"忙"。
        """
        for turn in turns_repo.list_unfinished_turns(self._engine):
            try:
                self._recover_turn(turn)
            except Exception:
                logger.exception("恢复 turn %s 失败，继续处理其他 turn", turn.id)

    def _recover_turn(self, turn: turns_repo.TurnValue) -> None:
        end_snapshot_id: str | None = None
        session = get_session(self._engine, turn.session_id)
        if turn.status == "running" and session is not None and session.project_id:
            try:
                snapshot = create_snapshot(
                    self._engine, self._blobs, session.project_id, "partial", turn.id
                )
                end_snapshot_id = snapshot.id
            except Exception:
                logger.exception("turn %s 恢复时快照失败", turn.id)
        turns_repo.interrupt_turn(self._engine, turn.id, end_snapshot_id=end_snapshot_id)

    # ---- scheduling -----------------------------------------------------

    def _schedule(self) -> None:
        for job in list(self._queue):
            if len(self._running) >= self._settings.max_concurrent_turns:
                return
            if self.is_project_busy(job.project_id):
                continue
            self._queue.remove(job)
            self._running[job.turn_id] = job
            job.task = asyncio.get_running_loop().create_task(self._run(job))

    def _release(self, job: _Job) -> None:
        self._running.pop(job.turn_id, None)
        self._jobs.pop(job.turn_id, None)
        job.done.set()

    def _request_stop(self, job: _Job) -> None:
        """置位取消令牌；运行时在宽限期内不结束就取消整个 task。"""
        job.cancel_token.cancel()
        task = job.task
        if task is not None:
            asyncio.get_running_loop().call_later(
                self._cancel_grace_seconds, lambda: task.done() or task.cancel()
            )

    # ---- one turn -------------------------------------------------------

    async def _run(self, job: _Job) -> None:
        state = _State()
        try:
            await self._execute(job, state)
        except asyncio.CancelledError:
            state.status = "cancelled"
            raise
        except Exception as exc:
            logger.exception("turn %s 执行出错", job.turn_id)
            state.status, state.error = "failed", f"{type(exc).__name__}: {exc}"
        finally:
            try:
                self._finish(job, state)
            finally:
                self._release(job)
                self._schedule()

    async def _execute(self, job: _Job, state: _State) -> None:
        engine, blobs = self._engine, self._blobs
        workdir = project_dir(self._settings.data_dir, job.project_id)
        workdir.mkdir(parents=True, exist_ok=True)

        latest = latest_snapshot(engine, job.project_id)
        current = scan(workdir)
        if latest is None or latest.manifest != current:
            reason = "user_edit" if latest is not None else "init"
            start = create_snapshot(engine, blobs, job.project_id, reason, job.turn_id)
            start_id, state.before = start.id, start.manifest
        else:
            start_id, state.before = latest.id, latest.manifest
        turns_repo.mark_turn_running(engine, job.turn_id, start_snapshot_id=start_id)
        self._publish_status(job, "running")

        state.upstream_ids = stage_flow.upstream_snapshot_ids(engine, job.project_id, job.stage)
        state.sources = stage_flow.manifests_of(engine, state.upstream_ids)
        materialize_upstream(workdir, blobs, state.sources)

        previous = turns_repo.previous_turn(engine, job.session.id, job.turn_id)
        preamble = build_preamble(
            gather_preamble_inputs(
                engine,
                blobs,
                workdir=workdir,
                project_id=job.project_id,
                stage=job.stage,
                previous=previous,
                start_snapshot_id=start_id,
            )
        )

        def record_tool_write(relpath: str, _sha256: str) -> None:
            # Store what is actually on disk so guard() can restore it later.
            state.tool_writes[relpath] = blobs.put(files.read_bytes(workdir, relpath))
            state.pending_tool_paths.append(relpath)

        ctx = TurnContext(
            system_prompt=job.stage.system_prompt(),
            user_input=UserInput(
                text=compose_user_text(preamble, job.user_input.text),
                images=job.user_input.images,
            ),
            tools=job.stage.tools(),
            workdir=workdir,
            model_profile=job.profile,
            resume_ref=job.session.sdk_ref,
            cancel_token=job.cancel_token,
            budget=Budget(job.profile.max_steps_per_turn, job.profile.max_cost_per_turn),
            write_scope=job.stage.write_scope(),
            project_id=job.project_id,
            stage=job.stage.name,
            record_tool_write=record_tool_write,
        )
        runtime = self._factory.create(job.session.runtime)
        stream = runtime.run_turn(ctx)
        try:
            async for event in stream:
                self._handle(job, state, event)
        finally:
            # Close the generator (and a real SDK subprocess behind it) before
            # guard/snapshot run, also when the runner itself raised mid-stream.
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                await aclose()

    def _handle(self, job: _Job, state: _State, event: events.AgentEvent) -> None:
        if isinstance(event, events.TextDelta):
            self._publish(job, "text_delta", {"text": event.text})
        elif isinstance(event, events.TextBlock):
            self._persist(job, "text", {"text": event.text})
        elif isinstance(event, events.ToolCall):
            state.steps += 1
            state.calls[event.call_id] = event
            self._persist(
                job,
                "tool_call",
                {"call_id": event.call_id, "name": event.name, "args": _truncate_args(event.args)},
            )
            limit = job.profile.max_steps_per_turn
            if limit is not None and state.steps > limit:
                self._exceed_budget(job, state, "steps")
        elif isinstance(event, events.ToolResult):
            text, truncated = _truncate(event.text)
            self._persist(
                job,
                "tool_result",
                {
                    "call_id": event.call_id,
                    "text": text,
                    "truncated": truncated,
                    "is_error": event.is_error,
                    # Image payloads are not persisted, only their types.
                    "images": [{"media_type": image.media_type} for image in event.images],
                },
            )
            self._after_tool_result(job, state, event)
        elif isinstance(event, events.Usage):
            state.input_tokens += event.input_tokens
            state.output_tokens += event.output_tokens
            state.cost_usd += event.cost_usd
            # Subscription (login) auth: cost is informational, only steps are enforced.
            if getattr(event, "auth", None) == "login":
                state.cost_advisory = True
            limit = job.profile.max_cost_per_turn
            if limit is not None and not state.cost_advisory and state.cost_usd > limit:
                self._exceed_budget(job, state, "cost")
        elif isinstance(event, events.TurnEnd):
            state.end = event

    def _after_tool_result(self, job: _Job, state: _State, event: events.ToolResult) -> None:
        call = state.calls.get(event.call_id)
        recorded, state.pending_tool_paths = state.pending_tool_paths, []
        if call is not None and call.name in events.FILE_TOOL_NAMES:
            path = call.args.get("path")
            # An empty list means "unknown paths, refetch" (e.g. shell commands).
            paths = [path] if isinstance(path, str) else []
            self._publish(job, "workspace_changed", {"paths": paths + recorded})
        elif recorded:
            self._publish(job, "workspace_changed", {"paths": recorded})

    def _exceed_budget(self, job: _Job, state: _State, kind: str) -> None:
        if state.budget_exceeded:
            return
        state.budget_exceeded = True
        self._persist(job, "notice", {"kind": "budget_exceeded", "budget": kind})
        self._request_stop(job)

    def _finish(self, job: _Job, state: _State) -> None:
        """越界检查 → 快照 → 写 turn 状态 → 发布 `turn_status`。每一步单独兜底。"""
        status, error = state.final_status()
        workdir = project_dir(self._settings.data_dir, job.project_id)
        try:
            restored: list[str] = []
            if state.before is not None:
                report = guard(
                    workdir,
                    state.before,
                    scan(workdir),
                    job.stage.write_scope(),
                    self._blobs,
                    state.tool_writes,
                )
                restored = report.restored
            if state.sources is not None:
                # Agent changes to the read-only copy are dropped and reported (R5).
                restored += upstream_drift(workdir, state.sources)
                materialize_upstream(workdir, self._blobs, state.sources)
            if restored:
                self._persist(job, "notice", {"kind": GUARD_RESTORED_NOTICE, "paths": restored})
                self._publish(job, "workspace_changed", {"paths": restored})
        except Exception as exc:
            logger.exception("turn %s 越界检查失败", job.turn_id)
            status, error = "failed", error or f"越界检查失败：{exc}"

        if status == "failed":
            self._safe_persist(job, "error", {"message": error or "未知错误"})

        end_snapshot_id: str | None = None
        try:
            reason = "partial" if status == "failed" else "turn"
            snapshot = create_snapshot(
                self._engine, self._blobs, job.project_id, reason, job.turn_id
            )
            end_snapshot_id = snapshot.id
            self._persist(
                job,
                "snapshot",
                {
                    "snapshot_id": snapshot.id,
                    "reason": snapshot.reason,
                    "created": snapshot.created,
                },
            )
        except Exception as exc:
            logger.exception("turn %s 结束快照失败", job.turn_id)
            status, error = "failed", error or f"结束快照失败：{exc}"

        usage: dict[str, Any] = {
            "input_tokens": state.input_tokens,
            "output_tokens": state.output_tokens,
            "steps": state.steps,
        }
        self._finish_turn_row(
            job,
            status=status,
            end_snapshot_id=end_snapshot_id,
            usage=usage,
            cost_usd=state.cost_usd,
            error=error,
            resume_ref=state.end.resume_ref if state.end is not None else None,
        )
        if status == "done":
            try:
                stage_flow.after_turn_done(
                    self._engine, job.project_id, job.stage.name, state.upstream_ids
                )
            except Exception:
                logger.exception("turn %s 更新阶段状态失败", job.turn_id)
        self._publish_status(job, status, error)

    # ---- persistence & bus ------------------------------------------------

    def _finish_turn_row(self, job: _Job, **fields: Any) -> None:
        """写 turn 最终状态，失败时重试一次（例如 SQLite 繁忙）；再失败只记日志。

        否则内存里的并发名额已释放，数据库却一直是 `running`，会话在重启前
        都会返回"忙"。
        """
        for attempt in (1, 2):
            try:
                turns_repo.finish_turn(self._engine, job.turn_id, **fields)
                return
            except Exception:
                logger.exception("turn %s 写入最终状态失败（第 %d 次）", job.turn_id, attempt)

    def _persist(self, job: _Job, type: str, payload: dict[str, Any]) -> None:
        payload = {"turn_id": job.turn_id, **payload}
        row = turns_repo.append_event(
            self._engine,
            turn_id=job.turn_id,
            session_id=job.session.id,
            type=type,
            payload=payload,
        )
        self._bus.publish(job.session.id, BusEvent(type, payload, seq=row.seq))

    def _safe_persist(self, job: _Job, type: str, payload: dict[str, Any]) -> None:
        try:
            self._persist(job, type, payload)
        except Exception:
            logger.exception("turn %s 写入 %s 事件失败", job.turn_id, type)

    def _publish(self, job: _Job, type: str, payload: dict[str, Any]) -> None:
        self._bus.publish(job.session.id, BusEvent(type, {"turn_id": job.turn_id, **payload}))

    def _publish_status(self, job: _Job, status: str, error: str | None = None) -> None:
        self._publish(job, "turn_status", {"status": status, "error": error})
