"""`produce` 提示词必须保住的规则：改提示词时防止丢规则。"""

from __future__ import annotations

import pytest

from studio.stages.produce import STAGE

_REQUIRED = [
    ("创意简报路径", "upstream/concept/brief.md"),
    ("硬性要求章节", "硬性要求"),
    ("两种形态判断", "music/source."),
    ("合成脚本", "music/compose.py"),
    ("配乐工具", "render_music"),
    ("歌曲分析工具", "analyze_music"),
    ("截取区间", "music/range.json"),
    ("镜头划分", "animation/shots.json"),
    ("镜头文件", "animation/scenes/"),
    ("lib 共享全局", "animation/lib/"),
    ("金样本（配乐）", "upstream/exemplar/audio-techniques.py"),
    ("金样本（画面）", "upstream/exemplar/canvas-techniques.js"),
    ("风格入口", "style/STYLE.md"),
    ("脚本无时间轴输入", "STUDIO_OUT_WAV"),
    ("事件文件", "STUDIO_OUT_EVENTS"),
    ("事件名与种类", "onset"),
    ("扫频事件", "sweep"),
    ("听不到声音", "听不到"),
    ("指标不证明好听", "不证明好听"),
    ("draw 契约", "draw(ctx, lt, env)"),
    ("hit", "env.hit"),
    ("span", "env.span"),
    ("energy", "env.energy"),
    ("bt 不可用", "env.bt"),
    ("moment 不可用", "env.moment"),
    ("禁止字面秒数", "不许写字面"),
    ("音乐平移警告", "平移"),
    ("禁用随机数", "Math.random"),
    ("禁用 rAF", "requestAnimationFrame"),
    ("带种子的随机数", "种子"),
    ("pad 转场", "pad"),
    ("assets 取用", "env.assets"),
    ("承载信息字号", "40px"),
    ("装饰标签字号", "24px"),
    ("不画字幕", "不画字幕"),
    ("字体 Anton", "Anton"),
    ("字体 Space Mono", "Space Mono"),
    ("字体 Noto Sans SC", "Noto Sans SC"),
    ("画面不重叠", "不重叠"),
    ("校验工具", "validate_scenes_html"),
    ("预览工具", "render_preview_html"),
    ("回退建议工具", "suggest_upstream_change"),
    ("不要反复全量预览", "不要反复"),
    ("对齐由你负责", "对齐由你负责"),
    ("事件列表按需读文件", "events.json"),
    ("歌曲项目缺歌时请用户上传", "请用户先上传歌曲"),
    ("汇报无法验证的东西", "无法验证"),
    ("歌词文件", "music/lyrics.lrc"),
    ("歌词意象以简报为准", "歌词意象"),
    ("当前歌词", "env.lyric()"),
    ("全部歌词行", "env.lyrics"),
    ("歌词金样本", "lyrics-techniques.js"),
    ("不写死歌词时间", "不要写死歌词出现的秒数"),
    ("镜头跟乐句走", "跟着乐句走"),
]


@pytest.mark.parametrize(("what", "needle"), _REQUIRED, ids=[what for what, _ in _REQUIRED])
def test_prompt_keeps_the_rule(what: str, needle: str) -> None:
    assert needle in STAGE.system_prompt(), f"提示词缺少「{what}」：{needle}"


@pytest.mark.parametrize(
    "gone",
    [
        "beatsheet.json",
        "sections.json",
        "validate_beatsheet",
        "validate_sections",
        "STUDIO_TIMELINE",
    ],
)
def test_prompt_no_longer_mentions_the_removed_pieces(gone: str) -> None:
    prompt = STAGE.system_prompt()
    assert gone not in prompt


def test_prompt_stays_a_reasonable_size() -> None:
    assert len(STAGE.system_prompt().encode("utf-8")) < 16_000
