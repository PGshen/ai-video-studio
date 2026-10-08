"""TD-80: `artifact_dirs()` entries may be exact file paths as well as directories."""

from __future__ import annotations

from studio.agent.preamble import _handoff_files as handoff_files
from studio.agent.preamble import _upstream_changes as upstream_changes
from studio.agent.stage import StageRegistry, artifact_entry_matches
from studio.agent.stage_flow import finalize, initial_statuses, reopen
from studio.db.repo.projects import create_project
from studio.db.repo.stages import create_stage, get_stage
from studio.stages.concept import ConceptStage
from studio.workspace import create_snapshot, project_dir

from .conftest import StudioEnv
from .test_stage_flow import _FakeStage

PIPELINE = ["concept", "produce"]


class TestArtifactEntryMatches:
    def test_directory_entry_matches_by_prefix(self) -> None:
        assert artifact_entry_matches("concept", "concept/brief.md")
        assert artifact_entry_matches("concept/", "concept/brief.md")
        assert not artifact_entry_matches("concept", "concept.md")
        assert not artifact_entry_matches("concept", "conceptual/x.md")

    def test_file_entry_matches_only_that_file(self) -> None:
        assert artifact_entry_matches("music/lyrics.lrc", "music/lyrics.lrc")
        assert not artifact_entry_matches("music/lyrics.lrc", "music/music.wav")
        assert not artifact_entry_matches("music/lyrics.lrc", "music/lyrics.lrc.bak")


class _Project:
    def __init__(self, env: StudioEnv) -> None:
        self.env = env
        self.registry = StageRegistry()
        self.registry.register(ConceptStage())
        self.registry.register(_FakeStage("produce", ["concept"], "produce"))
        project = create_project(env.engine, title="歌", settings={"pipeline": PIPELINE})
        self.project_id = project.id
        for name, status in initial_statuses(PIPELINE, self.registry):
            create_stage(env.engine, project_id=project.id, stage=name, status=status)
        project_dir(env.data_dir, project.id).mkdir(parents=True, exist_ok=True)
        create_snapshot(env.engine, env.blobs, project.id, reason="init")

    def write(self, relpath: str, content: str) -> None:
        path = project_dir(self.env.data_dir, self.project_id) / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def finalize(self, stage: str) -> None:
        finalize(self.env.engine, self.env.blobs, self.registry, self.project_id, stage)

    def refinalize_concept(self) -> None:
        reopen(self.env.engine, self.project_id, "concept")
        self.finalize("concept")

    def status(self, name: str) -> str:
        value = get_stage(self.env.engine, self.project_id, name)
        assert value is not None
        return value.status

    def write_produce_outputs(self) -> None:
        self.write("music/music.wav", "wav")
        self.write("music/events.json", "{}")
        self.write("music/range.json", "{}")


class TestConceptFileScope:
    def test_concept_declares_only_user_input_files(self) -> None:
        entries = ConceptStage().artifact_dirs()
        assert entries[0] == "concept"
        assert "music" not in entries
        assert "music/source.mp3" in entries
        assert {"music/analysis.json", "music/analysis.png", "music/lyrics.lrc"} <= set(entries)

    def test_produce_outputs_do_not_stale_produce_for_short_reel(self, env: StudioEnv) -> None:
        proj = _Project(env)
        proj.write("concept/brief.md", "b")
        proj.finalize("concept")  # music/ is empty here
        proj.finalize("produce")
        proj.write_produce_outputs()
        proj.refinalize_concept()
        assert proj.status("produce") == "finalized"

    def test_produce_outputs_do_not_stale_produce_for_mv(self, env: StudioEnv) -> None:
        proj = _Project(env)
        proj.write("concept/brief.md", "b")
        proj.write("music/source.mp3", "song")
        proj.write("music/lyrics.lrc", "[00:01.00]hi")
        proj.finalize("concept")
        proj.finalize("produce")
        proj.write_produce_outputs()
        proj.refinalize_concept()
        assert proj.status("produce") == "finalized"
        assert (
            upstream_changes(
                env.engine, env.blobs, proj.project_id, proj.registry.get("produce"), proj.registry
            )
            == []
        )

    def test_changing_song_or_lyrics_still_stales_produce(self, env: StudioEnv) -> None:
        proj = _Project(env)
        proj.write("concept/brief.md", "b")
        proj.write("music/source.mp3", "song")
        proj.write("music/lyrics.lrc", "[00:01.00]hi")
        proj.finalize("concept")
        proj.finalize("produce")

        reopen(env.engine, proj.project_id, "concept")
        proj.write("music/source.mp3", "other song")
        proj.finalize("concept")
        assert proj.status("produce") == "stale"

        proj.finalize("produce")
        assert proj.status("produce") == "finalized"
        reopen(env.engine, proj.project_id, "concept")
        proj.write("music/lyrics.lrc", "[00:01.00]changed")
        proj.finalize("concept")
        assert proj.status("produce") == "stale"
        changes = upstream_changes(
            env.engine, env.blobs, proj.project_id, proj.registry.get("produce"), proj.registry
        )
        assert [m.path for m in changes[0].diff.modified] == ["music/lyrics.lrc"]

    def test_handoff_files_use_file_level_entries(self, env: StudioEnv) -> None:
        proj = _Project(env)
        proj.write("concept/brief.md", "b")
        proj.write("music/lyrics.lrc", "[00:01.00]hi")
        proj.write_produce_outputs()
        workdir = project_dir(env.data_dir, proj.project_id)
        files = handoff_files(workdir, proj.registry.get("concept"))
        assert sorted(files) == ["concept/brief.md", "music/lyrics.lrc"]


class TestDirectoryEntriesUnchanged:
    def test_directory_entry_stage_still_stales_downstream(self, env: StudioEnv) -> None:
        proj = _Project(env)
        proj.registry = StageRegistry()
        proj.registry.register(_FakeStage("concept", [], "concept"))
        proj.registry.register(_FakeStage("produce", ["concept"], "produce"))
        proj.write("concept/a.md", "1")
        proj.finalize("concept")
        proj.finalize("produce")
        reopen(env.engine, proj.project_id, "concept")
        proj.write("concept/sub/b.md", "2")
        proj.finalize("concept")
        assert proj.status("produce") == "stale"
