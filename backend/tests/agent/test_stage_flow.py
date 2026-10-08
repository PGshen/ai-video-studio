from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command

from studio.agent.preamble import _upstream_changes as upstream_changes
from studio.agent.stage import StageRegistry
from studio.agent.stage_flow import (
    StageFlowError,
    after_turn_done,
    finalize,
    initial_statuses,
    project_pipeline,
    reopen,
    upstream_snapshot_ids,
    upstream_sources,
)
from studio.agent.tools import ToolSpec
from studio.db.engine import _alembic_config
from studio.db.repo.projects import create_project, get_project
from studio.db.repo.snapshots import get_snapshot
from studio.db.repo.stages import create_stage, get_stage
from studio.workspace import create_snapshot, project_dir
from studio.workspace.scope import WriteScope

from .conftest import StudioEnv


def _stage(env: StudioEnv, name: str):
    value = get_stage(env.engine, env.project_id, name)
    assert value is not None
    return value


class TestFinalize:
    def test_finalize_snapshots_workspace_and_unlocks_downstream(self, env: StudioEnv) -> None:
        env.write("topic/brief.md", "v1")  # unsnapshotted edit must be captured

        finalize(env.engine, env.blobs, env.registry, env.project_id, "topic")

        topic = _stage(env, "topic")
        assert topic.status == "finalized"
        assert topic.finalized_at is not None
        assert topic.finalized_snapshot_id is not None
        snapshot = get_snapshot(env.engine, topic.finalized_snapshot_id)
        assert snapshot is not None and "topic/brief.md" in snapshot.manifest

        narrative = _stage(env, "narrative")
        assert narrative.status == "active"
        assert narrative.based_on == {"topic": topic.finalized_snapshot_id}
        # animation is downstream of narrative, not topic
        assert _stage(env, "animation").status == "locked"

    def test_locked_stage_cannot_be_finalized(self, env: StudioEnv) -> None:
        with pytest.raises(StageFlowError):
            finalize(env.engine, env.blobs, env.registry, env.project_id, "narrative")

    def test_refinalize_with_changes_marks_downstream_stale(self, env: StudioEnv) -> None:
        env.write("topic/brief.md", "v1")
        finalize(env.engine, env.blobs, env.registry, env.project_id, "topic")
        first = _stage(env, "topic").finalized_snapshot_id

        reopen(env.engine, env.project_id, "topic")
        assert _stage(env, "topic").status == "active"
        # reopened upstream: downstream still reads the previous finalized version
        assert _stage(env, "narrative").status == "active"

        env.write("topic/brief.md", "v2")
        finalize(env.engine, env.blobs, env.registry, env.project_id, "topic")

        narrative = _stage(env, "narrative")
        assert narrative.status == "stale"
        assert narrative.based_on == {"topic": first}

    def test_refinalize_without_changes_keeps_downstream_active(self, env: StudioEnv) -> None:
        env.write("topic/brief.md", "v1")
        finalize(env.engine, env.blobs, env.registry, env.project_id, "topic")
        reopen(env.engine, env.project_id, "topic")
        finalize(env.engine, env.blobs, env.registry, env.project_id, "topic")

        assert _stage(env, "narrative").status == "active"

    def test_change_outside_upstream_artifact_dirs_keeps_downstream_active(
        self, env: StudioEnv
    ) -> None:
        """TD-6：定稿快照是整项目的，但只有上游产物目录（`topic/`）的变化才让下游 stale。"""
        env.write("topic/brief.md", "v1")
        finalize(env.engine, env.blobs, env.registry, env.project_id, "topic")
        reopen(env.engine, env.project_id, "topic")

        env.write("style/STYLE.md", "changed outside topic/")
        finalize(env.engine, env.blobs, env.registry, env.project_id, "topic")

        assert _stage(env, "narrative").status == "active"

    def test_stale_downstream_returns_to_active_when_upstream_reverts(self, env: StudioEnv) -> None:
        env.write("topic/brief.md", "v1")
        finalize(env.engine, env.blobs, env.registry, env.project_id, "topic")
        reopen(env.engine, env.project_id, "topic")
        env.write("topic/brief.md", "v2")
        finalize(env.engine, env.blobs, env.registry, env.project_id, "topic")
        assert _stage(env, "narrative").status == "stale"

        reopen(env.engine, env.project_id, "topic")
        env.write("topic/brief.md", "v1")
        finalize(env.engine, env.blobs, env.registry, env.project_id, "topic")

        assert _stage(env, "narrative").status == "active"

    def _stale_narrative(self, env: StudioEnv) -> None:
        """topic v1 定稿 → topic 改成 v2 再定稿，narrative 变 stale。"""
        env.write("topic/brief.md", "v1")
        finalize(env.engine, env.blobs, env.registry, env.project_id, "topic")
        env.write("narrative/script.md", "s1")

    def _refinalize_topic(self, env: StudioEnv, content: str) -> None:
        reopen(env.engine, env.project_id, "topic")
        env.write("topic/brief.md", content)
        finalize(env.engine, env.blobs, env.registry, env.project_id, "topic")

    def test_finalizing_a_stale_stage_rebases_it_onto_current_upstreams(
        self, env: StudioEnv
    ) -> None:
        """TD-64：定稿 stale 阶段时 `based_on` 刷成各上游当前定稿，
        之后上游无变化地重新定稿不再让它 stale。"""
        self._stale_narrative(env)
        self._refinalize_topic(env, "v2")
        assert _stage(env, "narrative").status == "stale"

        finalize(env.engine, env.blobs, env.registry, env.project_id, "narrative")
        narrative = _stage(env, "narrative")
        assert narrative.status == "finalized"
        assert narrative.based_on == {"topic": _stage(env, "topic").finalized_snapshot_id}

        self._refinalize_topic(env, "v2")
        assert _stage(env, "narrative").status == "finalized"

    def test_stale_finalized_stage_returns_to_finalized_when_upstream_reverts(
        self, env: StudioEnv
    ) -> None:
        """TD-65：已定稿的下游因上游变化而 stale，上游改回原样后回到 `finalized`。"""
        self._stale_narrative(env)
        finalize(env.engine, env.blobs, env.registry, env.project_id, "narrative")
        self._refinalize_topic(env, "v2")
        assert _stage(env, "narrative").status == "stale"

        self._refinalize_topic(env, "v1")

        narrative = _stage(env, "narrative")
        assert narrative.status == "finalized"
        assert narrative.based_on == {"topic": _stage(env, "topic").finalized_snapshot_id}
        project = get_project(env.engine, env.project_id)
        assert project is not None and project.current_stage == "animation"

    def test_stale_reopened_stage_returns_to_active_when_upstream_reverts(
        self, env: StudioEnv
    ) -> None:
        self._stale_narrative(env)
        finalize(env.engine, env.blobs, env.registry, env.project_id, "narrative")
        reopen(env.engine, env.project_id, "narrative")
        self._refinalize_topic(env, "v2")
        assert _stage(env, "narrative").status == "stale"

        self._refinalize_topic(env, "v1")

        assert _stage(env, "narrative").status == "active"

    def test_stage_edited_while_stale_returns_to_active_when_upstream_reverts(
        self, env: StudioEnv
    ) -> None:
        """stale 期间跑过一轮（变 `active`）的下游，再次 stale 后恢复时回到 `active`。"""
        self._stale_narrative(env)
        finalize(env.engine, env.blobs, env.registry, env.project_id, "narrative")
        self._refinalize_topic(env, "v2")
        after_turn_done(
            env.engine,
            env.project_id,
            "narrative",
            upstream_snapshot_ids(env.engine, env.registry, env.project_id, "narrative"),
        )
        assert _stage(env, "narrative").status == "active"

        self._refinalize_topic(env, "v3")
        assert _stage(env, "narrative").status == "stale"
        self._refinalize_topic(env, "v2")

        assert _stage(env, "narrative").status == "active"


class TestCurrentStage:
    """`projects.current_stage` 跟着阶段流转走：第一个未定稿的阶段，全部定稿则是最后一个阶段。"""

    def _current(self, env: StudioEnv) -> str:
        project = get_project(env.engine, env.project_id)
        assert project is not None
        return project.current_stage

    def test_starts_at_topic(self, env: StudioEnv) -> None:
        assert self._current(env) == "topic"

    def test_follows_finalize_through_to_the_last_stage(self, env: StudioEnv) -> None:
        env.write("topic/brief.md", "v1")
        finalize(env.engine, env.blobs, env.registry, env.project_id, "topic")
        assert self._current(env) == "narrative"

        finalize(env.engine, env.blobs, env.registry, env.project_id, "narrative")
        assert self._current(env) == "animation"

        finalize(env.engine, env.blobs, env.registry, env.project_id, "animation")
        assert self._current(env) == "animation"

    def test_reopen_moves_back_to_the_earliest_unfinalized_stage(self, env: StudioEnv) -> None:
        env.write("topic/brief.md", "v1")
        finalize(env.engine, env.blobs, env.registry, env.project_id, "topic")
        finalize(env.engine, env.blobs, env.registry, env.project_id, "narrative")

        reopen(env.engine, env.project_id, "narrative")
        assert self._current(env) == "narrative"

        reopen(env.engine, env.project_id, "topic")
        assert self._current(env) == "topic"


class TestReopen:
    def test_only_finalized_stage_can_be_reopened(self, env: StudioEnv) -> None:
        with pytest.raises(StageFlowError):
            reopen(env.engine, env.project_id, "topic")


class TestAfterTurnDone:
    def test_stale_downstream_rebases_and_becomes_active(self, env: StudioEnv) -> None:
        env.write("topic/brief.md", "v1")
        finalize(env.engine, env.blobs, env.registry, env.project_id, "topic")
        reopen(env.engine, env.project_id, "topic")
        env.write("topic/brief.md", "v2")
        finalize(env.engine, env.blobs, env.registry, env.project_id, "topic")
        latest = _stage(env, "topic").finalized_snapshot_id

        used = upstream_snapshot_ids(env.engine, env.registry, env.project_id, "narrative")
        after_turn_done(env.engine, env.project_id, "narrative", used)

        narrative = _stage(env, "narrative")
        assert (narrative.status, narrative.based_on) == ("active", {"topic": latest})

    def test_stage_without_upstream_is_untouched(self, env: StudioEnv) -> None:
        after_turn_done(env.engine, env.project_id, "topic", {})

        topic = _stage(env, "topic")
        assert (topic.status, topic.based_on) == ("active", {})


class TestUpstreamSources:
    def test_uses_finalized_manifest_or_none(self, env: StudioEnv) -> None:
        assert upstream_sources(env.engine, env.registry, env.project_id, "narrative") == {
            "topic": None
        }

        env.write("topic/brief.md", "v1")
        finalize(env.engine, env.blobs, env.registry, env.project_id, "topic")
        env.write("topic/brief.md", "edited after finalize")

        sources = upstream_sources(env.engine, env.registry, env.project_id, "narrative")
        manifest = sources["topic"]
        assert manifest is not None
        snapshot = get_snapshot(env.engine, _stage(env, "topic").finalized_snapshot_id or "")
        assert snapshot is not None and manifest == snapshot.manifest


class TestLegacyProjectUpgrade:
    """评审重点 1：没有 `settings.pipeline` 的老项目，流水线取阶段行顺序，结论与改造前一致。"""

    def test_pipeline_falls_back_to_stage_row_order(self, env: StudioEnv) -> None:
        assert project_pipeline(env.engine, env.project_id) == ["topic", "narrative", "animation"]

    def test_refinalized_topic_stales_narrative_only_and_shows_in_preamble(
        self, env: StudioEnv
    ) -> None:
        env.write("topic/brief.md", "v1")
        finalize(env.engine, env.blobs, env.registry, env.project_id, "topic")
        finalize(env.engine, env.blobs, env.registry, env.project_id, "narrative")
        assert _stage(env, "animation").status == "active"

        reopen(env.engine, env.project_id, "topic")
        env.write("topic/brief.md", "v2")
        finalize(env.engine, env.blobs, env.registry, env.project_id, "topic")

        assert _stage(env, "narrative").status == "stale"
        animation = _stage(env, "animation")
        assert animation.status == "active"
        assert animation.based_on == {"narrative": _stage(env, "narrative").finalized_snapshot_id}
        changes = upstream_changes(
            env.engine, env.blobs, env.project_id, env.registry.get("narrative"), env.registry
        )
        assert [c.stage for c in changes] == ["topic"]
        assert [m.path for m in changes[0].diff.modified] == ["topic/brief.md"]


class _FakeStage:
    """Test-only stand-in for the stages added in later tasks (design §3.3 `reads()`)."""

    allow_web = False
    workspaceless = False

    def __init__(self, name: str, reads: list[str], artifact_dir: str) -> None:
        self.name = name
        self._reads = reads
        self._artifact_dir = artifact_dir

    def system_prompt(self) -> str:
        return self.name

    def tools(self) -> list[ToolSpec]:
        return []

    def write_scope(self) -> WriteScope:
        return WriteScope(writable=[f"{self._artifact_dir}/"], tool_managed=[])

    def reads(self) -> list[str]:
        return list(self._reads)

    def prepare_turn(self, workdir: Path) -> None:
        return None

    def artifact_dirs(self) -> list[str]:
        return [self._artifact_dir]

    def status_summary(self, workdir: Path) -> str:
        return ""

    def finalize_blockers(self, workdir: Path) -> list[str]:
        return []


MOTION_REEL = ["concept", "beatsheet", "music", "animation_html"]
MUSIC_VIDEO = ["concept", "music", "beatsheet", "animation_html"]


def _reel_registry() -> StageRegistry:
    registry = StageRegistry()
    for stage in (
        _FakeStage("concept", [], "concept"),
        _FakeStage("beatsheet", ["concept", "music"], "beatsheet"),
        _FakeStage("music", ["concept", "narrative", "beatsheet"], "music"),
        _FakeStage("animation_html", ["narrative", "beatsheet", "music"], "animation"),
    ):
        registry.register(stage)
    return registry


class _Reel:
    """A short-reel (motion_reel) project over the fake stages."""

    def __init__(self, env: StudioEnv) -> None:
        self.env = env
        self.registry = _reel_registry()
        project = create_project(env.engine, title="短片", settings={"pipeline": MOTION_REEL})
        self.project_id = project.id
        for name, status in initial_statuses(MOTION_REEL, self.registry):
            create_stage(env.engine, project_id=project.id, stage=name, status=status)
        project_dir(env.data_dir, project.id).mkdir(parents=True, exist_ok=True)
        create_snapshot(env.engine, env.blobs, project.id, reason="init")

    def write(self, relpath: str, content: str) -> None:
        path = project_dir(self.env.data_dir, self.project_id) / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def finalize(self, stage: str) -> None:
        finalize(self.env.engine, self.env.blobs, self.registry, self.project_id, stage)

    def reopen(self, stage: str) -> None:
        reopen(self.env.engine, self.project_id, stage)

    def edit_and_finalize(self, stage: str, relpath: str, content: str) -> None:
        # A stale stage (its own upstream changed) can be edited and finalized directly.
        if self.stage(stage).status == "finalized":
            self.reopen(stage)
        self.write(relpath, content)
        self.finalize(stage)

    def stage(self, name: str):
        value = get_stage(self.env.engine, self.project_id, name)
        assert value is not None
        return value


class TestInitialStatuses:
    def test_only_stages_without_upstream_start_active(self, env: StudioEnv) -> None:
        registry = _reel_registry()
        assert initial_statuses(MOTION_REEL, registry) == [
            ("concept", "active"),
            ("beatsheet", "locked"),
            ("music", "locked"),
            ("animation_html", "locked"),
        ]
        assert initial_statuses(MUSIC_VIDEO, registry) == [
            ("concept", "active"),
            ("music", "locked"),
            ("beatsheet", "locked"),
            ("animation_html", "locked"),
        ]

    def test_legacy_pipeline(self, env: StudioEnv) -> None:
        assert initial_statuses(["topic", "narrative", "animation"], env.registry) == [
            ("topic", "active"),
            ("narrative", "locked"),
            ("animation", "locked"),
        ]


class TestMultiUpstream:
    def test_pipeline_comes_from_settings(self, env: StudioEnv) -> None:
        reel = _Reel(env)
        assert project_pipeline(env.engine, reel.project_id) == MOTION_REEL

    def test_downstream_unlocks_only_when_all_upstreams_are_finalized(self, env: StudioEnv) -> None:
        """评审重点 2：只定稿多个上游中的一个时，下游仍是 `locked`。"""
        reel = _Reel(env)
        reel.write("concept/idea.md", "c1")
        reel.finalize("concept")

        assert reel.stage("beatsheet").status == "active"
        assert reel.stage("beatsheet").based_on == {
            "concept": reel.stage("concept").finalized_snapshot_id
        }
        assert reel.stage("music").status == "locked"
        assert reel.stage("music").based_on == {}

        reel.write("beatsheet/beats.json", "b1")
        reel.finalize("beatsheet")

        music = reel.stage("music")
        assert music.status == "active"
        assert music.based_on == {
            "concept": reel.stage("concept").finalized_snapshot_id,
            "beatsheet": reel.stage("beatsheet").finalized_snapshot_id,
        }
        assert reel.stage("animation_html").status == "locked"

    def test_stale_recovers_only_when_every_upstream_matches(self, env: StudioEnv) -> None:
        """评审重点 3：一个上游改回原样、另一个仍有变化时，下游保持 `stale`。"""
        reel = _Reel(env)
        reel.write("concept/idea.md", "c1")
        reel.finalize("concept")
        reel.write("beatsheet/beats.json", "b1")
        reel.finalize("beatsheet")
        assert reel.stage("music").status == "active"

        reel.edit_and_finalize("concept", "concept/idea.md", "c2")
        assert reel.stage("music").status == "stale"

        reel.edit_and_finalize("beatsheet", "beatsheet/beats.json", "b2")
        assert reel.stage("music").status == "stale"

        reel.edit_and_finalize("concept", "concept/idea.md", "c1")
        assert reel.stage("music").status == "stale"  # beatsheet still differs

        reel.edit_and_finalize("beatsheet", "beatsheet/beats.json", "b1")
        assert reel.stage("music").status == "active"

    def test_finalized_stale_stage_is_not_restaled_by_an_unchanged_upstream(
        self, env: StudioEnv
    ) -> None:
        """TD-64（多上游）：stale 的 beatsheet 直接定稿后，concept 无变化地重新定稿不再让它 stale，
        前言也不再报告 concept 的变化。"""
        reel = _Reel(env)
        reel.write("concept/idea.md", "c1")
        reel.finalize("concept")
        reel.write("beatsheet/beats.json", "b1")
        reel.finalize("beatsheet")
        reel.edit_and_finalize("concept", "concept/idea.md", "c2")
        assert reel.stage("beatsheet").status == "stale"

        reel.finalize("beatsheet")
        assert reel.stage("beatsheet").based_on == {
            "concept": reel.stage("concept").finalized_snapshot_id
        }

        reel.reopen("concept")
        reel.write("music/score.py", "outside concept/")
        reel.finalize("concept")
        assert reel.stage("beatsheet").status == "finalized"
        changes = upstream_changes(
            env.engine, env.blobs, reel.project_id, reel.registry.get("beatsheet"), reel.registry
        )
        assert changes == []

    def test_stale_finalized_stage_recovers_to_finalized_when_every_upstream_reverts(
        self, env: StudioEnv
    ) -> None:
        """TD-65（多上游）：两个上游都改回原样后，原来已定稿的 music 回到 `finalized`。"""
        reel = _Reel(env)
        reel.write("concept/idea.md", "c1")
        reel.finalize("concept")
        reel.write("beatsheet/beats.json", "b1")
        reel.finalize("beatsheet")
        reel.write("music/score.py", "m1")
        reel.finalize("music")

        reel.edit_and_finalize("concept", "concept/idea.md", "c2")
        reel.edit_and_finalize("beatsheet", "beatsheet/beats.json", "b2")
        assert reel.stage("music").status == "stale"

        reel.edit_and_finalize("concept", "concept/idea.md", "c1")
        assert reel.stage("music").status == "stale"
        reel.edit_and_finalize("beatsheet", "beatsheet/beats.json", "b1")

        music = reel.stage("music")
        assert music.status == "finalized"
        assert music.based_on == {
            "concept": reel.stage("concept").finalized_snapshot_id,
            "beatsheet": reel.stage("beatsheet").finalized_snapshot_id,
        }

    def test_upstream_snapshot_ids_follow_the_pipeline(self, env: StudioEnv) -> None:
        reel = _Reel(env)
        # music reads narrative too, but narrative is not in this pipeline.
        assert upstream_snapshot_ids(env.engine, reel.registry, reel.project_id, "music") == {
            "concept": None,
            "beatsheet": None,
        }

    def test_after_turn_done_keeps_stale_when_an_upstream_moved_mid_turn(
        self, env: StudioEnv
    ) -> None:
        reel = _Reel(env)
        reel.write("concept/idea.md", "c1")
        reel.finalize("concept")
        reel.write("beatsheet/beats.json", "b1")
        reel.finalize("beatsheet")
        reel.edit_and_finalize("concept", "concept/idea.md", "c2")
        assert reel.stage("music").status == "stale"

        used = upstream_snapshot_ids(env.engine, reel.registry, reel.project_id, "music")
        # beatsheet is re-finalized while the music turn is running
        reel.edit_and_finalize("beatsheet", "beatsheet/beats.json", "b2")
        after_turn_done(env.engine, reel.project_id, "music", used)

        music = reel.stage("music")
        assert music.status == "stale"
        assert music.based_on == {"concept": used["concept"], "beatsheet": used["beatsheet"]}

        used = upstream_snapshot_ids(env.engine, reel.registry, reel.project_id, "music")
        after_turn_done(env.engine, reel.project_id, "music", used)
        assert reel.stage("music").status == "active"

    def test_preamble_reports_each_changed_upstream_against_its_own_based_on(
        self, env: StudioEnv
    ) -> None:
        reel = _Reel(env)
        reel.write("concept/idea.md", "c1")
        reel.finalize("concept")
        reel.write("beatsheet/beats.json", "b1")
        reel.finalize("beatsheet")

        reel.edit_and_finalize("concept", "concept/idea.md", "c2")
        changes = upstream_changes(
            env.engine, env.blobs, reel.project_id, reel.registry.get("music"), reel.registry
        )
        assert [c.stage for c in changes] == ["concept"]
        assert [m.path for m in changes[0].diff.modified] == ["concept/idea.md"]

        reel.edit_and_finalize("beatsheet", "beatsheet/beats.json", "b2")
        changes = upstream_changes(
            env.engine, env.blobs, reel.project_id, reel.registry.get("music"), reel.registry
        )
        assert [c.stage for c in changes] == ["concept", "beatsheet"]


class TestAfterMigrationRoundTrip:
    """TD-68: stage rows that went 0010 → 0008 (old `based_on_snapshot_id`) → head keep working."""

    def test_refinalize_and_preamble_still_work_after_a_down_up_migration(
        self, env: StudioEnv
    ) -> None:
        env.write("topic/brief.md", "v1")
        finalize(env.engine, env.blobs, env.registry, env.project_id, "topic")
        first = _stage(env, "topic").finalized_snapshot_id
        assert _stage(env, "narrative").based_on == {"topic": first}

        config = _alembic_config()
        with env.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "0008")
            command.upgrade(config, "head")
        assert _stage(env, "narrative").based_on == {"topic": first}

        reopen(env.engine, env.project_id, "topic")
        env.write("topic/brief.md", "v2")
        finalize(env.engine, env.blobs, env.registry, env.project_id, "topic")

        narrative = _stage(env, "narrative")
        assert narrative.status == "stale" and narrative.based_on == {"topic": first}
        changes = upstream_changes(
            env.engine, env.blobs, env.project_id, env.registry.get("narrative"), env.registry
        )
        assert [c.stage for c in changes] == ["topic"]
        assert [m.path for m in changes[0].diff.modified] == ["topic/brief.md"]
