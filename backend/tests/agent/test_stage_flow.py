from __future__ import annotations

import pytest

from studio.agent.stage_flow import (
    StageFlowError,
    after_turn_done,
    finalize,
    reopen,
    upstream_snapshot_ids,
    upstream_sources,
)
from studio.db.repo.projects import get_project
from studio.db.repo.snapshots import get_snapshot
from studio.db.repo.stages import get_stage

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
        assert narrative.based_on_snapshot_id == topic.finalized_snapshot_id
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
        assert narrative.based_on_snapshot_id == first

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

        used = upstream_snapshot_ids(env.engine, env.project_id, env.registry.get("narrative"))
        after_turn_done(env.engine, env.project_id, "narrative", used)

        narrative = _stage(env, "narrative")
        assert (narrative.status, narrative.based_on_snapshot_id) == ("active", latest)

    def test_stage_without_upstream_is_untouched(self, env: StudioEnv) -> None:
        after_turn_done(env.engine, env.project_id, "topic", {})

        topic = _stage(env, "topic")
        assert (topic.status, topic.based_on_snapshot_id) == ("active", None)


class TestUpstreamSources:
    def test_uses_finalized_manifest_or_none(self, env: StudioEnv) -> None:
        narrative = env.registry.get("narrative")
        assert upstream_sources(env.engine, env.project_id, narrative) == {"topic": None}

        env.write("topic/brief.md", "v1")
        finalize(env.engine, env.blobs, env.registry, env.project_id, "topic")
        env.write("topic/brief.md", "edited after finalize")

        sources = upstream_sources(env.engine, env.project_id, narrative)
        manifest = sources["topic"]
        assert manifest is not None
        snapshot = get_snapshot(env.engine, _stage(env, "topic").finalized_snapshot_id or "")
        assert snapshot is not None and manifest == snapshot.manifest
