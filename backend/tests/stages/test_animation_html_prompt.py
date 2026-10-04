"""`animation_html` 提示词必须保住的规则（设计 §6.4）：改提示词时防止丢规则。"""

from __future__ import annotations

import pytest

from studio.stages.animation_html import STAGE

_REQUIRED = [
    ("时间轴路径", "upstream/timeline.json"),
    ("叙事路径", "upstream/narrative/narrative.json"),
    ("风格入口", "style/STYLE.md"),
    ("金样本路径", "upstream/exemplar/canvas-techniques.js"),
    ("时间轴不可用时的说明文件", "upstream/timeline.error.txt"),
    ("draw 契约", "draw(ctx, lt, env)"),
    ("cue 驱动", "env.cue"),
    ("cueEnd", "env.cueEnd"),
    ("禁止字面秒数", "不许写字面"),
    ("禁用随机数", "Math.random"),
    ("禁用 rAF", "requestAnimationFrame"),
    ("带种子的随机数", "种子"),
    ("lib 共享全局", "animation/lib/"),
    ("pad 转场", "pad"),
    ("assets 取用", "env.assets"),
    ("承载信息字号", "40px"),
    ("装饰标签字号", "24px"),
    ("不画字幕", "不画字幕"),
    ("字体 Anton", "Anton"),
    ("字体 Space Mono", "Space Mono"),
    ("字体 Noto Sans SC", "Noto Sans SC"),
    ("风格字体", "style/fonts"),
    ("校验工具", "validate_scenes_html"),
    ("预览工具", "render_preview_html"),
    ("回退建议工具", "suggest_upstream_change"),
    ("不要反复全量预览", "不要反复"),
    ("画面不重叠", "不重叠"),
]


@pytest.mark.parametrize(("what", "needle"), _REQUIRED, ids=[w for w, _ in _REQUIRED])
def test_prompt_keeps_the_rule(what: str, needle: str) -> None:
    assert needle in STAGE.system_prompt(), what
