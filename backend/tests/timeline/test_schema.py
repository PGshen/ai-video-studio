"""`studio.timeline.schema`：默认值与 JSON 往返（设计 §4.1）。"""

from __future__ import annotations

from studio.timeline.schema import Beat, NarrationScene, Section, Timeline


def test_defaults_leave_reserved_layers_empty() -> None:
    tl = Timeline(duration=3.0)
    assert tl.grid is None
    assert tl.music is None
    assert tl.sections == []
    assert tl.narration == []
    assert tl.moments == []
    assert tl.lyrics == []


def test_json_roundtrip() -> None:
    tl = Timeline(
        duration=3.0,
        sections=[Section(id="s-hook", label="开场", start=0.0, end=3.0)],
        narration=[
            NarrationScene(
                scene_id="s-hook",
                start=0.0,
                end=3.0,
                beats=[Beat(start=0.0, end=1.5, cue_text="第一句")],
            )
        ],
    )
    dumped = tl.model_dump(mode="json")
    assert dumped["narration"][0]["beats"][0]["cue_text"] == "第一句"
    assert Timeline.model_validate(dumped) == tl
