"""HTML 引擎测试用的极小工作区：时间轴与几个固定场景（T4、T6、T8 共用）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

TIMELINE: dict[str, Any] = {
    "duration": 6.0,
    "grid": None,
    "sections": [
        {"id": "s-hook", "label": "开场", "start": 0.0, "end": 3.0},
        {"id": "s-explain", "label": "讲解", "start": 3.0, "end": 6.0},
    ],
    "narration": [
        {
            "scene_id": "s-hook",
            "start": 0.0,
            "end": 3.0,
            "beats": [
                {"start": 0.4, "end": 1.4, "cue_text": "第一句"},
                {"start": 1.6, "end": 2.8, "cue_text": "第二句"},
            ],
        },
        {
            "scene_id": "s-explain",
            "start": 3.0,
            "end": 6.0,
            "beats": [
                {"start": 3.5, "end": 4.5, "cue_text": "第三句"},
                {"start": 4.8, "end": 5.8, "cue_text": "第四句"},
            ],
        },
    ],
    "moments": [],
    "music": None,
    "lyrics": [],
}

# 用 env.cue 驱动：每个 beat 起点开始填充一条横条。
CUE_SCENE = """
window.__seen = window.__seen || {};
module.exports = { draw(ctx, lt, env) {
  window.__seen[env.section.id] = {
    cue0: env.cue(0), cueEnd0: env.cueEnd(0), len: env.len, id: env.section.id,
    index: env.section.index, W: env.W, H: env.H, beats: env.beats.length, t: env.t,
  };
  ctx.fillStyle = '#102030'; ctx.fillRect(0, 0, env.W, env.H);
  for (let i = 0; i < env.beats.length; i++) {
    const p = Math.min(1, Math.max(0, (lt - env.cue(i)) / 0.4));
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(100, 100 + i * 200, 800 * p, 120);
  }
} };
"""

# 把 beat 时刻写成字面量：beat 敏感度测试应判为“全部无反应”。
LITERAL_SCENE = """
module.exports = { draw(ctx, lt, env) {
  ctx.fillStyle = '#102030'; ctx.fillRect(0, 0, env.W, env.H);
  const starts = [0.4, 1.6];
  for (let i = 0; i < starts.length; i++) {
    const p = Math.min(1, Math.max(0, (lt - starts[i]) / 0.4));
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(100, 100 + i * 200, 800 * p, 120);
  }
} };
"""

PURE_SCENE_PLAIN = """
module.exports = { draw(ctx, lt, env) {
  ctx.fillStyle = '#204060'; ctx.fillRect(0, 0, env.W, env.H);
  ctx.fillStyle = '#fff'; ctx.fillRect(100 + lt * 100, 300, 200, 200);
} };
"""

# 跨帧可变状态：确定性检查应当发现。
STATEFUL_SCENE = """
let calls = 0;
module.exports = { draw(ctx, lt, env) {
  calls += 1;
  ctx.fillStyle = '#204060'; ctx.fillRect(0, 0, env.W, env.H);
  ctx.fillStyle = '#fff'; ctx.fillRect(100 + calls * 7, 300, 200, 200);
} };
"""

CHINESE_SCENE = """
module.exports = { draw(ctx, lt, env) {
  ctx.fillStyle = '#000'; ctx.fillRect(0, 0, env.W, env.H);
  ctx.fillStyle = '#fff'; ctx.font = "700 160px 'Noto Sans SC'";
  ctx.fillText('天空为什么是蓝的', 100, 500);
} };
"""

THROWING_SCENE = "module.exports = { draw(ctx, lt, env) { env.cue(99); } };\n"
GRID_SCENE = "module.exports = { draw(ctx, lt, env) { env.bt(1); } };\n"
NO_DRAW_SCENE = "module.exports = {};\n"
SYNTAX_ERROR_SCENE = "module.exports = { draw(ctx, lt, env) { ctx.fillRect(; } };\n"
LOOP_SCENE = "module.exports = { draw(ctx, lt, env) { while (true) {} } };\n"

SVG_RED = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
    '<rect width="100" height="100" fill="#ff0000"/></svg>'
)
ASSET_SCENE = """
module.exports = { draw(ctx, lt, env) {
  ctx.drawImage(env.assets['logo.svg'], 0, 0, 100, 100);
} };
"""
MISSING_ASSET_SCENE = (
    "module.exports = { draw(ctx, lt, env) { ctx.drawImage(env.assets['nope.svg'], 0, 0); } };\n"
)

PAD_A = """
module.exports = { pad: { out: 0.5 }, draw(ctx, lt, env) {
  ctx.fillStyle = '#ff0000'; ctx.fillRect(10, 10, 40, 40);
} };
"""
PAD_B = """
module.exports = { draw(ctx, lt, env) {
  ctx.fillStyle = '#0000ff'; ctx.fillRect(200, 10, 40, 40);
} };
"""
GLOBAL_POST = (
    "module.exports = { post(ctx, t, env) {"
    " ctx.fillStyle = '#ff00ff'; ctx.fillRect(5, 5, 10, 10); } };\n"
)


def write_project(
    workdir: Path,
    *,
    scenes: dict[str, str],
    lib: dict[str, str] | None = None,
    global_js: str | None = None,
    assets: dict[str, str] | None = None,
) -> Path:
    animation = workdir / "animation"
    for name, source in scenes.items():
        _write(animation / "scenes" / f"{name}.js", source)
    for name, source in (lib or {}).items():
        _write(animation / "lib" / f"{name}.js", source)
    if global_js is not None:
        _write(animation / "global.js", global_js)
    for name, source in (assets or {}).items():
        _write(animation / "assets" / name, source)
    return workdir


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def reel_timeline(*, bars: int = 4, sections: int = 2) -> dict[str, Any]:
    """A motion-reel timeline at 128 BPM with moments, music events and an energy curve.

    Section `s1` starts at 0, `s2` at half the length. Events: `kick` on every beat, one `late`
    onset and one `riser` sweep, so that `late` is the rarest name.
    """
    from fixtures.audio_engine import reel_timeline as base

    timeline = base(128.0, bars, sections=sections)
    beat = 60 / 128
    last = timeline["sections"][-1]
    timeline["moments"] = [
        {"section_id": "s1", "at": "1.1", "t": 0.0, "visual_action": "开场"},
        {
            "section_id": last["id"],
            "at": "1.3",
            "t": last["start"] + 2 * beat,
            "visual_action": "冲击",
        },
    ]
    timeline["music"] = {
        "file": "music/music.wav",
        "events": [
            *(
                {"name": "kick", "kind": "onset", "start": i * beat, "end": i * beat + 0.18}
                for i in range(bars * 4)
            ),
            {
                "name": "late",
                "kind": "onset",
                "start": last["start"] + 0.9,
                "end": last["start"] + 1.1,
            },
            {"name": "riser", "kind": "sweep", "start": 1.0, "end": 2.0},
        ],
        "energy": {
            "hop": 0.1,
            "values": [i / 150 for i in range(int(timeline["duration"] / 0.1) + 1)],
        },
    }
    return timeline
