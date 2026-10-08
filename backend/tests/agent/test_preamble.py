from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from sqlalchemy import Engine

from studio.agent.preamble import (
    DIFF_MAX_CHARS_PER_FILE,
    PreambleInputs,
    RollbackNotice,
    UpstreamChange,
    build_preamble,
    compose_user_text,
)
from studio.agent.preamble import _narrative_scene_summary as narrative_scene_summary
from studio.agent.preamble import _upstream_changes as upstream_changes
from studio.agent.stage import StageRegistry
from studio.agent.stage_flow import finalize
from studio.db.repo.projects import update_project_settings
from studio.db.repo.stages import create_stage, update_stage
from studio.stages.animation import STAGE as ANIMATION_STAGE
from studio.stages.narrative import STAGE as NARRATIVE_STAGE
from studio.stages.topic import STAGE as TOPIC_STAGE
from studio.workspace import BlobStore, ModifiedFile, WorkspaceDiff, create_snapshot
from studio.workspace.scope import WriteScope


class NarrativeProjectEnv(Protocol):
    project_id: str
    workdir: Path
    engine: Engine
    blobs: BlobStore


def _diff(
    added: list[str] | None = None,
    removed: list[str] | None = None,
    modified: list[ModifiedFile] | None = None,
) -> WorkspaceDiff:
    return WorkspaceDiff(added=added or [], removed=removed or [], modified=modified or [])


def _modified(path: str, text_diff: str | None) -> ModifiedFile:
    return ModifiedFile(path=path, old_sha256="a", new_sha256="b", text_diff=text_diff)


def test_empty_inputs_give_empty_preamble() -> None:
    assert build_preamble(PreambleInputs()) == ""
    # an empty diff is "nothing to say" as well
    assert build_preamble(PreambleInputs(user_edits=_diff())) == ""


def test_user_edits_list_files_and_truncated_diff() -> None:
    long_diff = "@@ -1 +1 @@\n" + "+x\n" * DIFF_MAX_CHARS_PER_FILE
    text = build_preamble(
        PreambleInputs(
            user_edits=_diff(
                added=["topic/new.md"],
                removed=["topic/old.md"],
                modified=[
                    _modified("topic/brief.md", "-old line\n+new line\n"),
                    _modified("topic/long.md", long_diff),
                    _modified("topic/pic.png", None),
                ],
            )
        )
    )

    assert "用户手动修改" in text
    for path in ("topic/new.md", "topic/old.md", "topic/brief.md", "topic/pic.png"):
        assert path in text
    assert "+new line" in text
    assert "（diff 已截断）" in text
    assert len(text) < 2 * DIFF_MAX_CHARS_PER_FILE + 1000


def test_all_sections_rendered() -> None:
    text = build_preamble(
        PreambleInputs(
            upstream_changes=[
                UpstreamChange(stage="topic", diff=_diff(modified=[_modified("topic/b.md", "")]))
            ],
            restored_paths=["style/STYLE.md"],
            rollback=RollbackNotice(
                rollback_snapshot_id="snap-r",
                target_snapshot_id="snap-t",
                diff=_diff(removed=["topic/draft.md"]),
            ),
            status_summary="topic/ 下有 1 个文件",
            handoff_files=["topic/brief.md"],
        )
    )

    assert "上游新定稿" in text and "topic/b.md" in text and "upstream/topic/" in text
    assert "被还原" in text and "style/STYLE.md" in text
    assert "回滚" in text and "snap-t" in text and "topic/draft.md" in text
    assert "topic/ 下有 1 个文件" in text
    assert "交接" in text and "topic/brief.md" in text


def test_compose_user_text() -> None:
    assert compose_user_text("", "你好") == "你好"
    composed = compose_user_text("前言", "你好")
    assert composed.startswith("前言") and composed.endswith("你好")


# ---------------------------------------------------------------------------
# 叙事→动画：按镜头 id 的上游变更摘要（M3 T9，TD-6）
# ---------------------------------------------------------------------------


def _scene(scene_id: str, narration: str, cues: list[str]) -> dict:
    return {
        "id": scene_id,
        "narration": narration,
        "visual_intent": "x",
        "beats": [
            {"cue_text": cue, "visual_action": "x", "emphasis": "x", "transition": "continue"}
            for cue in cues
        ],
    }


def _manifest(blobs: BlobStore, scenes: list[dict] | None) -> dict[str, str]:
    if scenes is None:
        return {"narrative/timing.json": blobs.put(b"{}")}
    text = json.dumps({"scenes": scenes}, ensure_ascii=False).encode("utf-8")
    return {"narrative/narrative.json": blobs.put(text)}


def test_scene_summary_lists_added_removed_narration_and_beat_changes(tmp_path: Path) -> None:
    blobs = BlobStore(tmp_path / "blobs")
    old = _manifest(
        blobs,
        [
            _scene("s-keep", "甲乙", ["甲", "乙"]),
            _scene("s-gone", "丙丁", ["丙丁"]),
            _scene("s-words", "戊己", ["戊己"]),
            _scene("s-beats", "庚辛", ["庚辛"]),
        ],
    )
    new = _manifest(
        blobs,
        [
            _scene("s-keep", "甲乙", ["甲", "乙"]),
            _scene("s-words", "戊己改", ["戊己改"]),
            _scene("s-beats", "庚辛", ["庚", "辛"]),
            _scene("s-new", "壬癸", ["壬癸"]),
        ],
    )

    assert narrative_scene_summary(old, new, blobs) == [
        "- 新增镜头 s-new",
        "- 删除镜头 s-gone",
        "- 镜头 s-words 旁白有改动",
        "- 镜头 s-beats 的 beat 拆分有改动",
    ]


def test_scene_summary_is_empty_list_when_scenes_are_identical(tmp_path: Path) -> None:
    blobs = BlobStore(tmp_path / "blobs")
    manifest = _manifest(blobs, [_scene("s-a", "甲乙", ["甲乙"])])

    assert narrative_scene_summary(manifest, manifest, blobs) == []


def test_scene_summary_is_none_when_a_side_cannot_be_parsed(tmp_path: Path) -> None:
    blobs = BlobStore(tmp_path / "blobs")
    good = _manifest(blobs, [_scene("s-a", "甲乙", ["甲乙"])])
    no_narrative = _manifest(blobs, None)
    bad_json = {"narrative/narrative.json": blobs.put(b"{not json")}
    no_id = {"narrative/narrative.json": blobs.put(b'{"scenes": [{"narration": "x"}]}')}

    assert narrative_scene_summary(good, no_narrative, blobs) is None
    assert narrative_scene_summary(no_narrative, good, blobs) is None
    assert narrative_scene_summary(good, bad_json, blobs) is None
    assert narrative_scene_summary(no_id, good, blobs) is None


def test_build_preamble_prefers_scene_summary_over_file_summary() -> None:
    change = UpstreamChange(
        stage="narrative",
        diff=_diff(modified=[_modified("narrative/narrative.json", None)]),
        scene_summary=["- 新增镜头 s-new", "- 镜头 s-a 旁白有改动"],
    )

    text = build_preamble(PreambleInputs(upstream_changes=[change]))

    assert "- 新增镜头 s-new" in text
    assert "- 镜头 s-a 旁白有改动" in text
    assert "narrative/narrative.json" not in text


def test_build_preamble_explains_empty_scene_summary() -> None:
    change = UpstreamChange(
        stage="narrative",
        diff=_diff(modified=[_modified("narrative/timing.json", None)]),
        scene_summary=[],
    )

    text = build_preamble(PreambleInputs(upstream_changes=[change]))

    assert "镜头没有变化" in text
    assert "narrative/timing.json" not in text


def test_gather_uses_scene_summary_only_for_narrative_edge(
    narrative_project: NarrativeProjectEnv,
) -> None:
    env = narrative_project
    registry = StageRegistry()
    for stage in (TOPIC_STAGE, NARRATIVE_STAGE, ANIMATION_STAGE):
        registry.register(stage)
    narrative_path = env.workdir / "narrative" / "narrative.json"
    narrative_path.parent.mkdir(parents=True, exist_ok=True)

    narrative_path.write_text(
        json.dumps({"scenes": [_scene("s-a", "甲乙", ["甲乙"])]}, ensure_ascii=False),
        encoding="utf-8",
    )
    finalize(env.engine, env.blobs, registry, env.project_id, "narrative")
    narrative_path.write_text(
        json.dumps(
            {"scenes": [_scene("s-a", "甲乙", ["甲乙"]), _scene("s-b", "丙丁", ["丙丁"])]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    finalize(env.engine, env.blobs, registry, env.project_id, "narrative")

    changes = upstream_changes(env.engine, env.blobs, env.project_id, ANIMATION_STAGE, registry)
    assert [c.scene_summary for c in changes] == [["- 新增镜头 s-b"]]
    assert changes[0].diff.modified  # 文件级 diff 仍照常计算

    # 选题→叙事这条边没有镜头概念，仍是文件级摘要。
    brief = env.workdir / "topic" / "brief.md"
    brief.write_text(brief.read_text(encoding="utf-8") + "\n新增一段\n", encoding="utf-8")
    finalize(env.engine, env.blobs, registry, env.project_id, "topic")
    topic_changes = upstream_changes(
        env.engine, env.blobs, env.project_id, NARRATIVE_STAGE, registry
    )
    assert [c.stage for c in topic_changes] == ["topic"]
    assert topic_changes[0].scene_summary is None


class _FakeStage:
    allow_web = False
    workspaceless = False

    def __init__(self, name: str, dirs: list[str], reads: list[str] | None = None) -> None:
        self.name = name
        self._dirs = dirs
        self._reads = reads or []

    def prepare_turn(self, workdir: Path) -> None:
        return None

    def finalize_blockers(self, workdir: Path) -> list[str]:
        return []

    def system_prompt(self) -> str:
        return ""

    def tools(self) -> list:
        return []

    def write_scope(self) -> WriteScope:
        return WriteScope(writable=[], tool_managed=[])

    def reads(self) -> list[str]:
        return list(self._reads)

    def artifact_dirs(self) -> list[str]:
        return list(self._dirs)

    def status_summary(self, workdir: Path) -> str:
        return ""


def test_upstream_changes_slice_by_artifact_dirs_not_stage_name(
    narrative_project: NarrativeProjectEnv,
) -> None:
    env = narrative_project
    upstream = _FakeStage("visual", ["animation/"])
    downstream = _FakeStage("animation_html", [], reads=["visual"])
    registry = StageRegistry()
    registry.register(upstream)
    registry.register(downstream)

    (env.workdir / "animation").mkdir(exist_ok=True)
    (env.workdir / "visual").mkdir(exist_ok=True)
    (env.workdir / "animation" / "a.txt").write_text("old", encoding="utf-8")
    (env.workdir / "visual" / "note.txt").write_text("old", encoding="utf-8")
    old_snap = create_snapshot(env.engine, env.blobs, env.project_id, "turn")
    (env.workdir / "animation" / "a.txt").write_text("new", encoding="utf-8")
    (env.workdir / "visual" / "note.txt").write_text("new", encoding="utf-8")
    new_snap = create_snapshot(env.engine, env.blobs, env.project_id, "turn")

    create_stage(env.engine, project_id=env.project_id, stage="visual", status="finalized")
    update_stage(env.engine, env.project_id, "visual", finalized_snapshot_id=new_snap.id)
    create_stage(env.engine, project_id=env.project_id, stage="animation_html", status="active")
    update_stage(env.engine, env.project_id, "animation_html", based_on={"visual": old_snap.id})

    changes = upstream_changes(env.engine, env.blobs, env.project_id, downstream, registry)

    assert [c.stage for c in changes] == ["visual"]
    assert [m.path for m in changes[0].diff.modified] == ["animation/a.txt"]
    assert changes[0].diff.added == [] and changes[0].diff.removed == []


def test_upstream_changes_follow_pipeline_order(
    narrative_project: NarrativeProjectEnv,
) -> None:
    env = narrative_project
    # MV-shaped pipeline: music comes before beatsheet, while reads() lists beatsheet first.
    registry = StageRegistry()
    registry.register(_FakeStage("concept", ["concept/"]))
    registry.register(_FakeStage("music", ["music/"]))
    registry.register(_FakeStage("beatsheet", ["beatsheet/"]))
    registry.register(_FakeStage("animation_html", [], reads=["beatsheet", "music"]))
    pipeline = ["concept", "music", "beatsheet", "animation_html"]
    update_project_settings(env.engine, env.project_id, {"pipeline": pipeline})

    for name in ("music", "beatsheet"):
        (env.workdir / name).mkdir(exist_ok=True)
        (env.workdir / name / "a.txt").write_text("old", encoding="utf-8")
    old_snap = create_snapshot(env.engine, env.blobs, env.project_id, "turn")
    for name in ("music", "beatsheet"):
        (env.workdir / name / "a.txt").write_text("new", encoding="utf-8")
    new_snap = create_snapshot(env.engine, env.blobs, env.project_id, "turn")

    for name in ("music", "beatsheet"):
        create_stage(env.engine, project_id=env.project_id, stage=name, status="finalized")
        update_stage(env.engine, env.project_id, name, finalized_snapshot_id=new_snap.id)
    create_stage(env.engine, project_id=env.project_id, stage="animation_html", status="active")
    update_stage(
        env.engine,
        env.project_id,
        "animation_html",
        based_on={"music": old_snap.id, "beatsheet": old_snap.id},
    )

    changes = upstream_changes(
        env.engine, env.blobs, env.project_id, registry.get("animation_html"), registry
    )

    assert [c.stage for c in changes] == ["music", "beatsheet"]


def test_an_unregistered_upstream_falls_back_to_its_own_name_as_artifact_dir(
    narrative_project: NarrativeProjectEnv,
) -> None:
    # TD-68: a stage name the registry no longer knows still slices the diff by `<name>/`.
    env = narrative_project
    registry = StageRegistry()
    downstream = _FakeStage("animation_html", [], reads=["ghost"])
    registry.register(downstream)
    update_project_settings(env.engine, env.project_id, {"pipeline": ["ghost", "animation_html"]})

    (env.workdir / "ghost").mkdir(exist_ok=True)
    (env.workdir / "other").mkdir(exist_ok=True)
    (env.workdir / "ghost" / "a.txt").write_text("old", encoding="utf-8")
    (env.workdir / "other" / "b.txt").write_text("old", encoding="utf-8")
    old_snap = create_snapshot(env.engine, env.blobs, env.project_id, "turn")
    (env.workdir / "ghost" / "a.txt").write_text("new", encoding="utf-8")
    (env.workdir / "other" / "b.txt").write_text("new", encoding="utf-8")
    new_snap = create_snapshot(env.engine, env.blobs, env.project_id, "turn")

    create_stage(env.engine, project_id=env.project_id, stage="ghost", status="finalized")
    update_stage(env.engine, env.project_id, "ghost", finalized_snapshot_id=new_snap.id)
    create_stage(env.engine, project_id=env.project_id, stage="animation_html", status="active")
    update_stage(env.engine, env.project_id, "animation_html", based_on={"ghost": old_snap.id})

    changes = upstream_changes(env.engine, env.blobs, env.project_id, downstream, registry)

    assert [c.stage for c in changes] == ["ghost"]
    assert [m.path for m in changes[0].diff.modified] == ["ghost/a.txt"]
