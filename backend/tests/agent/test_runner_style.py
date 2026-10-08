"""TurnRunner 的「绑定目录」模式（计划 style-library T9、ADR 0019）：风格对话的 cwd 是这套风格的
草稿目录，没有快照、`upstream/`、前言和越界还原；同一风格的轮次串行，和项目轮次互不阻塞。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from studio.agent import events, fake
from studio.agent.runtime import TurnContext, UserInput
from studio.db.repo.profiles import get_model_profile
from studio.db.repo.sessions import SessionValue, create_session
from studio.db.repo.snapshots import list_snapshots
from studio.db.repo.turns import (
    create_turn_if_session_idle,
    get_turn,
    latest_turn,
    list_events,
    mark_turn_running,
)
from studio.stages.style import STAGE as STYLE
from studio.styles import store
from studio.styles.layout import draft_dir

from .conftest import StudioEnv
from .test_runner import Harness, _collect, _drain, _make_harness, _until

FILES = {
    "STYLE.md": (
        "---\nname: 暖纸双色\ndescription: 暖色双色风格\n---\n\n先读 `references/color.md`。\n"
    ),
    "references/color.md": "主色：暖白",
}


@pytest.fixture
def h(env: StudioEnv) -> Harness:
    env.registry.register(STYLE)
    return _make_harness(env)


def _style(h: Harness, name: str = "暖纸双色") -> str:
    files = dict(FILES)
    files["STYLE.md"] = files["STYLE.md"].replace("暖纸双色", name)
    return store.import_style(h.env.data_dir, files).id


def _session(h: Harness, subject_id: str | None) -> SessionValue:
    profile = get_model_profile(h.env.engine, "fake")
    assert profile is not None
    return create_session(
        h.env.engine,
        project_id=None,
        stage="style",
        subject_id=subject_id,
        model_profile_id=profile.id,
        runtime="fake",
    )


def _running(h: Harness, session_id: str) -> bool:
    turn = latest_turn(h.env.engine, session_id)
    return turn is not None and turn.status == "running"


class TestStyleTurn:
    async def test_the_turn_works_in_the_draft_and_leaves_the_saved_version(
        self, h: Harness
    ) -> None:
        style_id = _style(h)
        session = _session(h, style_id)

        turn = await h.run(
            session.id, [fake.say("改好了"), fake.write("references/color.md", "主色：深蓝")]
        )

        assert turn.status == "done"
        ctx = h.contexts[0]
        assert ctx.workdir == draft_dir(h.env.data_dir, style_id)
        assert ctx.project_id is None and ctx.stage == "style"
        assert (
            store.read_draft_file(h.env.data_dir, style_id, "references/color.md") == "主色：深蓝"
        )
        assert store.get_style(h.env.data_dir, style_id).files == FILES

    async def test_no_snapshots_no_preamble_and_a_style_scoped_write_scope(
        self, h: Harness
    ) -> None:
        style_id = _style(h)
        session = _session(h, style_id)
        before = len(list_snapshots(h.env.engine, h.env.project_id))

        turn = await h.run(session.id, [fake.say("好")], text="把配色改深一点")

        assert turn.start_snapshot_id is None and turn.end_snapshot_id is None
        assert len(list_snapshots(h.env.engine, h.env.project_id)) == before
        ctx = h.contexts[0]
        assert ctx.user_input.text == "把配色改深一点"
        assert ctx.write_scope == STYLE.write_scope()
        assert [r.type for r in list_events(h.env.engine, session.id)] == ["text"]

    async def test_the_draft_is_opened_for_a_saved_style_and_a_brand_new_one(
        self, h: Harness
    ) -> None:
        saved = _style(h)
        new_id = store.create_new_draft(h.env.data_dir)

        await h.run(_session(h, saved).id, [fake.write("references/a.md", "x")])
        await h.run(_session(h, new_id).id, [fake.write("references/b.md", "y")])

        assert "references/a.md" in store.draft_status(h.env.data_dir, saved).files
        assert "references/b.md" in store.draft_status(h.env.data_dir, new_id).files
        assert store.draft_status(h.env.data_dir, new_id).is_new is True

    async def test_workspace_changed_is_published_after_each_write_and_once_more_at_the_end(
        self, h: Harness
    ) -> None:
        style_id = _style(h)
        session = _session(h, style_id)
        received, pump = _collect(h.bus, session.id)

        await h.run(session.id, [fake.write("references/color.md", "x")])
        await _drain(pump)

        changed = [e for e in received if e.type == "workspace_changed"]
        assert len(changed) == 2  # the write, then the end-of-turn refresh (shell edits)
        assert changed[0].payload["paths"] == ["references/color.md"]

    async def test_an_out_of_scope_write_is_refused_and_nothing_is_created(
        self, h: Harness
    ) -> None:
        style_id = _style(h)
        session = _session(h, style_id)

        await h.run(session.id, [fake.write("notes.md", "x"), fake.write("style/STYLE.md", "x")])

        rows = [r for r in list_events(h.env.engine, session.id) if r.type == "tool_result"]
        assert len(rows) == 2 and all(r.payload.get("is_error") for r in rows)
        draft = draft_dir(h.env.data_dir, style_id)
        assert not (draft / "notes.md").exists() and not (draft / "style").exists()

    async def test_junk_left_by_a_shell_is_pruned_with_a_notice(self, h: Harness) -> None:
        style_id = _style(h)
        session = _session(h, style_id)
        outside = h.env.data_dir / "outside.md"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_text("x")

        class Messy:
            async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
                (ctx.workdir / "notes.md").write_text("顶层多余文件")
                (ctx.workdir / "references" / "link.md").symlink_to(outside)
                (ctx.workdir / "references" / "good.md").write_text("合法的新文件")
                yield events.TurnEnd(resume_ref=None, status="done")

        turn = await h.run(session.id, Messy)

        assert turn.status == "done"
        draft = draft_dir(h.env.data_dir, style_id)
        assert not (draft / "notes.md").exists() and not (draft / "references" / "link.md").exists()
        assert (draft / "references" / "good.md").read_text() == "合法的新文件"
        assert outside.read_text() == "x"
        notices = [r for r in list_events(h.env.engine, session.id) if r.type == "notice"]
        assert len(notices) == 1
        assert notices[0].payload["kind"] == "draft_pruned"
        assert set(notices[0].payload["paths"]) == {"notes.md", "references/link.md"}

    async def test_failure_and_cancel_keep_the_draft_as_it_was(self, h: Harness) -> None:
        style_id = _style(h)
        session = _session(h, style_id)

        class Exploding:
            async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
                (ctx.workdir / "references" / "half.md").write_text("写了一半")
                yield events.TextBlock(text="写了一半")
                raise RuntimeError("网络断开")

        failed = await h.run(session.id, Exploding)
        assert failed.status == "failed" and "网络断开" in (failed.error or "")
        assert store.read_draft_file(h.env.data_dir, style_id, "references/half.md") == "写了一半"

        h.scripts.append([fake.sleep(5)])
        turn_id = await h.runner.start_turn(session.id, UserInput(text="go"))
        await _until(lambda: _running(h, session.id))
        assert h.runner.cancel(turn_id) is True
        await asyncio.wait_for(h.runner.wait(turn_id), timeout=5)
        cancelled = get_turn(h.env.engine, turn_id)
        assert cancelled is not None and cancelled.status == "cancelled"
        assert store.get_style(h.env.data_dir, style_id).files == FILES

    async def test_a_style_deleted_before_the_turn_fails_the_turn(self, h: Harness) -> None:
        style_id = _style(h)
        session = _session(h, style_id)
        store.delete_style(h.env.data_dir, style_id)

        turn = await h.run(session.id, [fake.say("不会执行")])

        assert turn.status == "failed"
        assert style_id in (turn.error or "")
        assert not draft_dir(h.env.data_dir, style_id).exists()


class TestScheduling:
    async def test_two_sessions_of_the_same_style_run_one_after_the_other(self, h: Harness) -> None:
        style_id = _style(h)
        first, second = _session(h, style_id), _session(h, style_id)
        h.scripts.append([fake.sleep(0.3)])
        t1 = await h.runner.start_turn(first.id, UserInput(text="a"))
        await _until(lambda: _running(h, first.id))
        h.scripts.append([fake.say("等我")])
        t2 = await h.runner.start_turn(second.id, UserInput(text="b"))

        await asyncio.sleep(0.05)
        queued = get_turn(h.env.engine, t2)
        assert queued is not None and queued.status == "queued"
        assert h.runner.is_subject_busy(style_id) is True

        await asyncio.wait_for(h.runner.wait(t2), timeout=5)
        done = get_turn(h.env.engine, t2)
        assert done is not None and done.status == "done"
        assert h.runner.is_subject_busy(style_id) is False
        await h.runner.wait(t1)

    async def test_different_styles_run_concurrently(self, h: Harness) -> None:
        a, b = _style(h, "甲"), _style(h, "乙")
        first, second = _session(h, a), _session(h, b)
        h.scripts.append([fake.sleep(5)])
        t1 = await h.runner.start_turn(first.id, UserInput(text="a"))
        await _until(lambda: _running(h, first.id))

        turn = await h.run(second.id, [fake.say("并行")])

        assert turn.status == "done"
        assert h.runner.is_subject_busy(a) is True and h.runner.is_subject_busy(b) is False
        h.runner.cancel(t1)
        await asyncio.wait_for(h.runner.wait(t1), timeout=5)

    async def test_style_and_project_turns_do_not_block_each_other(self, h: Harness) -> None:
        style_id = _style(h)
        project_session = h.session()
        h.scripts.append([fake.sleep(5)])
        project_turn = await h.runner.start_turn(project_session, UserInput(text="p"))
        await _until(lambda: h.runner.is_project_busy(h.env.project_id))

        turn = await h.run(_session(h, style_id).id, [fake.say("不受项目 turn 影响")])

        assert turn.status == "done"
        assert h.runner.is_project_busy(h.env.project_id)
        h.runner.cancel(project_turn)
        await asyncio.wait_for(h.runner.wait(project_turn), timeout=5)

    async def test_is_subject_busy_is_false_for_unknown_subjects(self, h: Harness) -> None:
        assert h.runner.is_subject_busy("nothing") is False


def test_draft_directory_helper_is_what_the_runner_uses(tmp_path: Path) -> None:
    assert draft_dir(tmp_path, "abc") == tmp_path / "style-drafts" / "abc"


class TestRecovery:
    def test_a_crashed_style_turn_has_its_draft_pruned_on_startup(self, h: Harness) -> None:
        # TD-54: the process died mid-turn, so nothing pruned what the agent left behind.
        style_id = _style(h)
        store.open_draft(h.env.data_dir, style_id)
        draft = draft_dir(h.env.data_dir, style_id)
        (draft / "stray.txt").write_text("多余", encoding="utf-8")
        (draft / "link.md").symlink_to(draft / "STYLE.md")
        session = _session(h, style_id)
        turn = create_turn_if_session_idle(h.env.engine, session.id, "改一下")
        assert turn is not None
        mark_turn_running(h.env.engine, turn.id, start_snapshot_id=None)

        h.runner.recover_on_startup()

        assert not (draft / "stray.txt").exists()
        assert not (draft / "link.md").is_symlink()
        assert (draft / "STYLE.md").is_file()
        assert store.validate_draft(h.env.data_dir, style_id) == []

    def test_a_style_session_whose_draft_is_gone_does_not_break_recovery(self, h: Harness) -> None:
        session = _session(h, "no-such-style")
        turn = create_turn_if_session_idle(h.env.engine, session.id, "x")
        assert turn is not None
        mark_turn_running(h.env.engine, turn.id, start_snapshot_id=None)

        h.runner.recover_on_startup()

        after = latest_turn(h.env.engine, session.id)
        assert after is not None and after.status == "interrupted"
