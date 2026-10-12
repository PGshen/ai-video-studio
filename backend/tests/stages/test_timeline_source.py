"""工具的时间轴来源表（free-mode 设计 §5.1，计划 T3）。

`free_explainer` 没有上游：场景工具与 `render_music` 即时从工作区**顶层**的
`narrative/narrative.json` + `timing.json`（有 `music/events.json` 时再叠加配乐层）构建时间轴。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from studio.agent.tools import ToolContext, ToolSpec, invoke_tool
from studio.stages.common.narration import SYNTHESIZE_TTS_TOOL, VALIDATE_NARRATIVE_TOOL
from studio.stages.common.scenes.helpers import load_timeline
from studio.stages.common.scenes.render_preview_html import RENDER_PREVIEW_HTML_TOOL
from studio.stages.common.scenes.validate_scenes_html import VALIDATE_SCENES_HTML_TOOL
from studio.stages.common.score import tool as music_tool
from studio.stages.common.score.analyze import ANALYZE_MUSIC_TOOL
from studio.stages.common.score.tool import RENDER_MUSIC_TOOL
from studio.stages.common.timeline_source import load_live_narrated, timeline_source
from studio.stages.common.web_tools import FETCH_URL_TOOL, WEB_SEARCH_TOOL

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REF = FIXTURES / "synth_music" / "compose_ref.py"


def identity(argv: list[str], env: dict[str, str]) -> list[str]:
    return argv


@pytest.fixture
def explainer(tmp_path: Path) -> Path:
    """A free explainer workspace: narration at the top level, no `upstream/`."""
    target = tmp_path / "narrative"
    target.mkdir(parents=True)
    for name in ("narrative.json", "timing.json"):
        shutil.copyfile(FIXTURES / "animation" / name, target / name)
    return tmp_path


def _ctx(workdir: Path, stage: str, writes: list[tuple[str, str]] | None = None) -> ToolContext:
    sink = writes if writes is not None else []
    return ToolContext(
        project_id="p",
        stage=stage,
        workdir=workdir,
        record_tool_write=lambda rel, digest: sink.append((rel, digest)),
    )


@pytest.mark.parametrize(
    ("stage", "expected"),
    [
        ("animation_html", "upstream"),
        ("music", "upstream"),
        ("produce", "live_silent"),
        ("free_produce", "live_silent"),
        ("free_explainer", "live_narrated"),
    ],
)
def test_timeline_source_table(stage: str, expected: str) -> None:
    assert timeline_source(stage) == expected


def test_free_explainer_scene_tools_read_the_top_level_narration(explainer: Path) -> None:
    timeline, error = load_timeline(_ctx(explainer, "free_explainer"))

    assert error is None
    assert timeline is not None
    assert [s["id"] for s in timeline["sections"]] == ["s-hook", "s-explain"]
    assert timeline.get("music") is None
    assert not (explainer / "upstream").exists()


def test_free_explainer_names_timing_when_narration_was_edited_without_new_voice(
    explainer: Path,
) -> None:
    path = explainer / "narrative" / "narrative.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["scenes"].append({**doc["scenes"][-1], "id": "s-new"})
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    timeline, error = load_timeline(_ctx(explainer, "free_explainer"))

    assert timeline is None
    assert error is not None and error.is_error
    assert "s-new" in error.text and "timing.json" in error.text


async def test_render_music_in_free_explainer_uses_the_top_level_base_hash(
    explainer: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(music_tool, "sandbox_wrapper", lambda workdir: identity)
    (explainer / "music").mkdir()
    shutil.copyfile(REF, explainer / "music" / "compose.py")

    result = await invoke_tool(RENDER_MUSIC_TOOL, _ctx(explainer, "free_explainer"), {})

    assert not result.is_error, result.text
    assert "重定时校验通过" in result.text
    record = json.loads((explainer / "music" / "render.json").read_text(encoding="utf-8"))
    assert record["base_hash"] == load_live_narrated(explainer, with_music=False).base_hash

    timeline, error = load_timeline(_ctx(explainer, "free_explainer"))
    assert error is None and timeline is not None
    assert timeline["music"] is not None


@pytest.mark.parametrize(
    ("tool", "stages"),
    [
        (VALIDATE_SCENES_HTML_TOOL, {"free_explainer", "free_produce"}),
        (RENDER_PREVIEW_HTML_TOOL, {"free_explainer", "free_produce"}),
        (RENDER_MUSIC_TOOL, {"free_explainer", "free_produce"}),
        (ANALYZE_MUSIC_TOOL, {"free_produce"}),
        (SYNTHESIZE_TTS_TOOL, {"free_explainer"}),
        (VALIDATE_NARRATIVE_TOOL, {"free_explainer"}),
        (WEB_SEARCH_TOOL, {"free_explainer", "free_produce"}),
        (FETCH_URL_TOOL, {"free_explainer", "free_produce"}),
    ],
)
def test_tools_are_open_to_the_free_stages(tool: ToolSpec, stages: set[str]) -> None:
    assert stages <= set(tool.stages)


def test_analyze_music_stays_off_the_free_explainer() -> None:
    assert "free_explainer" not in ANALYZE_MUSIC_TOOL.stages
