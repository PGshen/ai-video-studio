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

模块拆分（TD-15）：一轮的完整生命周期分散在四个文件里，`runner.py` 只保留
`TurnRunner` 的公开接口、排队调度和总线/持久化的基础方法（`_persist` 等，其他
模块通过持有的 `TurnRunner` 引用调用它们）：

- `turn_state.py`：`_Job`/`_State`，四个模块共用。
- `turn_events.py`：把运行时事件落库、推送，维护 `_State`（`handle`）。
- `turn_finish.py`：一轮结束的收尾（`finish`/`finish_turn_row`）。
- `recovery.py`：进程重启后恢复遗留 turn（`recover_on_startup`）。
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any

from sqlalchemy import Engine

from studio.agent import recovery, stage_flow, turn_events, turn_finish
from studio.agent.bus import BusEvent, SessionBus
from studio.agent.preamble import (
    build_preamble,
    compose_user_text,
    gather_preamble_inputs,
)
from studio.agent.runtime import Budget, RuntimeFactory, TurnContext, UserInput
from studio.agent.stage import StageRegistry
from studio.agent.turn_events import TOOL_RESULT_MAX_CHARS
from studio.agent.turn_state import _Job, _State
from studio.config import Settings
from studio.db.repo import turns as turns_repo
from studio.db.repo.profiles import get_model_profile_by_id
from studio.db.repo.sessions import get_session
from studio.db.repo.snapshots import latest_snapshot
from studio.workspace import (
    BlobStore,
    create_snapshot,
    files,
    materialize_upstream,
    project_dir,
    scan,
)

__all__ = [
    "TurnRunner",
    "SessionBusyError",
    "SessionNotFoundError",
    "TOOL_RESULT_MAX_CHARS",
]

logger = logging.getLogger(__name__)


class SessionBusyError(Exception):
    """会话已有 `queued`/`running` 的 turn（API 映射为 409）。"""


class SessionNotFoundError(LookupError):
    pass


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
        self._shutting_down = False

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
            turn_finish.finish_turn_row(
                self,
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
        """项目是否有 turn 在跑。只能在事件循环线程上调用（I4）：`_running` 和排队
        调度都在事件循环上修改，调用方（api 的 `async def` 端点）在检查与写工作区
        之间不 `await`，相对调度器就是原子的。
        """
        return any(job.project_id == project_id for job in self._running.values())

    async def shutdown(self, grace_seconds: float = 5.0) -> None:
        """进程关闭（lifespan 退出）时收尾：排队的 turn 直接记为 `interrupted`；
        运行中的 turn 置位取消令牌，等 `grace_seconds` 让运行时自己停下，超时就
        取消 task。两种情况都走 `_finish`（越界检查 → `partial` 快照 → 写状态），
        状态记为 `interrupted`，和重启后 `recover_on_startup` 的结果一致，可以"继续"。
        """
        self._shutting_down = True
        for job in list(self._queue):
            self._queue.remove(job)
            try:
                turns_repo.interrupt_turn(self._engine, job.turn_id, end_snapshot_id=None)
            except Exception:
                logger.exception("turn %s 关闭时标记 interrupted 失败", job.turn_id)
            self._publish_status(job, "interrupted")
            self._release(job)

        tasks = []
        for job in list(self._running.values()):
            job.shutdown = True
            job.cancel_token.cancel()
            if job.task is not None:
                tasks.append(job.task)
        if not tasks:
            return
        _done, pending = await asyncio.wait(tasks, timeout=grace_seconds)
        for task in pending:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def recover_on_startup(self) -> None:
        """设计 §4.4 第 8 步：上次进程遗留的 `running`/`queued` turn → `interrupted`。"""
        recovery.recover_on_startup(self)

    # ---- scheduling -----------------------------------------------------

    def _schedule(self) -> None:
        if self._shutting_down:
            return
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
                turn_finish.finish(self, job, state)
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
            allow_web=job.stage.allow_web,
            engine=engine,
        )
        runtime = self._factory.create(job.session.runtime)
        stream = runtime.run_turn(ctx)
        try:
            async for event in stream:
                turn_events.handle(self, job, state, event)
        finally:
            # Close the generator (and a real SDK subprocess behind it) before
            # guard/snapshot run, also when the runner itself raised mid-stream.
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                await aclose()

    # ---- persistence & bus ------------------------------------------------
    #
    # 供本模块和 turn_events/turn_finish/recovery 共用：它们持有 TurnRunner 引用，
    # 通过这些方法落库、推送到总线，自己只决定"发生了什么、要不要发"。

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
