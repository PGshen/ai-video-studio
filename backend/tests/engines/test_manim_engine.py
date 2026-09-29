import ast
import wave
from pathlib import Path

import pytest

from studio.engines.render.base import RenderRequest, RenderResultWithBytes, SceneAudio, SceneInput
from studio.engines.render.manim import ManimRenderEngine
from studio.engines.render.manim.script import (
    _build_manim_script,
    _prepare_manim_code,
    _scene_line_ranges,
    _static_check,
)


def test_prepare_manim_code_injects_template_into_formula_calls():
    code = """
formula = MathTex(r"\\text{面积}=\\pi r^2")
caption = Tex("中文说明")
label = Text("普通中文")
"""

    prepared, changed = _prepare_manim_code(code)
    tree = ast.parse(prepared)
    calls = {
        node.func.id: node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert changed is True
    assert any(keyword.arg == "tex_template" for keyword in calls["MathTex"].keywords)
    assert any(keyword.arg == "tex_template" for keyword in calls["Tex"].keywords)
    assert not any(keyword.arg == "tex_template" for keyword in calls["Text"].keywords)


def test_prepare_manim_code_preserves_explicit_template():
    code = 'formula = MathTex("x", tex_template=custom_template)'

    prepared, changed = _prepare_manim_code(code)

    assert changed is False
    assert prepared == code


def test_prepare_manim_code_supports_qualified_constructor():
    prepared, changed = _prepare_manim_code('formula = manim.MathTex("x")')

    assert changed is True
    assert "tex_template=_chinese_tex_template" in prepared


def test_prepare_manim_code_injects_template_into_chinese_bulleted_list():
    code = """
bullets = BulletedList(
    "主观时间加速",
    "童年慢于成年",
    "中点提前",
)
"""

    prepared, changed = _prepare_manim_code(code)
    tree = ast.parse(prepared)
    call = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "BulletedList"
    )

    assert changed is True
    assert any(keyword.arg == "tex_template" for keyword in call.keywords)


def test_prepare_manim_code_repairs_double_escaped_latex_commands():
    code = r"""
formula = MathTex(
    r'\\frac{\\Delta t_{心理}}{\\Delta t_{物理}} = \\frac{1}{年龄+1}'
)
"""

    prepared, changed = _prepare_manim_code(code)
    tree = ast.parse(prepared)
    call = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "MathTex"
    )

    assert changed is True
    assert isinstance(call.args[0], ast.Constant)
    assert call.args[0].value == (r"\frac{\Delta t_{心理}}{\Delta t_{物理}} = \frac{1}{年龄+1}")


def test_prepare_manim_code_preserves_latex_line_breaks():
    code = r"""
formula = MathTex(r"\begin{aligned}x &= 1 \\ y &= 2\end{aligned}")
"""

    prepared, _ = _prepare_manim_code(code)
    tree = ast.parse(prepared)
    call = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "MathTex"
    )

    assert isinstance(call.args[0], ast.Constant)
    assert call.args[0].value == r"\begin{aligned}x &= 1 \\ y &= 2\end{aligned}"


def test_build_manim_script_adds_xelatex_ctex_template():
    scene = SceneInput(
        scene_index=0,
        narration="圆的面积",
        description="展示中文公式",
        code='formula = MathTex(r"\\text{面积}=\\pi r^2")',
        audio=None,
    )

    script = _build_manim_script([scene])

    assert 'TexTemplate(tex_compiler="xelatex", output_format=".xdv")' in script
    assert r"\usepackage[UTF8,fontset=fandol]{ctex}" in script
    assert "tex_template=_chinese_tex_template" in script


def test_build_manim_script_skips_template_without_tex_calls():
    scene = SceneInput(
        scene_index=0,
        narration="标题",
        description="普通文字",
        code='title = Text("中文标题")',
        audio=None,
    )

    script = _build_manim_script([scene])

    assert "_chinese_tex_template" not in script


def test_build_manim_script_sets_portrait_pixel_and_logical_canvas():
    scene = SceneInput(
        scene_index=0,
        narration="标题",
        description="竖屏标题",
        code='title = Text("竖屏")',
        audio=None,
    )

    script = _build_manim_script([scene], resolution=(1080, 1920))

    assert "config.pixel_width = 1080" in script
    assert "config.pixel_height = 1920" in script
    assert "config.frame_width = 4.500000" in script
    assert "config.frame_height = 8.0" in script


def test_build_manim_script_isolates_scenes_into_own_methods():
    scenes = [
        SceneInput(
            scene_index=0, narration="", description="镜头0", code="local_var = 1", audio=None
        ),
        SceneInput(
            scene_index=1, narration="", description="镜头1", code="self.play(Wait())", audio=None
        ),
    ]

    script = _build_manim_script(scenes)

    assert "    def _scene_0(self):" in script
    assert "    def _scene_1(self):" in script
    assert "        self._scene_0()" in script
    assert "        self._scene_1()" in script

    ranges = _scene_line_ranges(script)
    assert [scene_idx for _, _, scene_idx in ranges] == [0, 1]


def test_build_manim_script_promotes_cross_scene_locals():
    scenes = [
        SceneInput(
            scene_index=0,
            narration="",
            description="镜头0",
            code="happy = Circle()\nself.add(happy)",
            audio=None,
        ),
        SceneInput(
            scene_index=1,
            narration="",
            description="镜头1",
            code="self.play(FadeOut(happy))",
            audio=None,
        ),
    ]

    script = _build_manim_script(scenes)

    assert "self.happy = Circle()" in script
    assert "FadeOut(self.happy)" in script


def test_promotion_leaves_scene_private_locals_untouched():
    scenes = [
        SceneInput(
            scene_index=0,
            narration="",
            description="镜头0",
            code="tmp = Dot()\nself.add(tmp)",
            audio=None,
        ),
        SceneInput(
            scene_index=1,
            narration="",
            description="镜头1",
            code="other = Square()\nself.add(other)",
            audio=None,
        ),
    ]

    script = _build_manim_script(scenes)

    assert "tmp = Dot()" in script
    assert "self.tmp" not in script


def test_promotion_skips_names_shadowing_manim_or_builtins():
    scenes = [
        SceneInput(
            scene_index=0, narration="", description="镜头0", code="UP = 1\nlen = 2", audio=None
        ),
        SceneInput(
            scene_index=1,
            narration="",
            description="镜头1",
            code="self.play(Dot().animate.shift(UP))\nn = len([1])",
            audio=None,
        ),
    ]

    script = _build_manim_script(scenes)

    assert "self.UP" not in script
    assert "self.len" not in script


def test_build_manim_script_injects_clear_except_helper():
    scenes = [
        SceneInput(scene_index=0, narration="", description="镜头0", code="pass", audio=None),
    ]

    script = _build_manim_script(scenes)

    assert "def clear_except(self, *keep):" in script


def test_prepare_manim_code_qualifies_bare_rate_function_names():
    code = "self.play(FadeIn(Dot()), rate_func=ease_out_bounce)"

    prepared, _ = _prepare_manim_code(code)

    assert "rate_func=rate_functions.ease_out_bounce" in prepared


def test_prepare_manim_code_keeps_top_level_rate_functions():
    code = "self.play(FadeIn(Dot()), rate_func=smooth)"

    prepared, _ = _prepare_manim_code(code)

    assert "rate_func=smooth" in code
    assert "rate_functions.smooth" not in prepared


def test_build_manim_script_hoists_scene_level_imports():
    scenes = [
        SceneInput(
            scene_index=0,
            narration="",
            description="镜头0",
            code="import random\nx = random.random()\nself.wait(x)",
            audio=None,
        ),
        SceneInput(
            scene_index=1,
            narration="",
            description="镜头1",
            code="import random\nimport math\nself.wait(math.floor(random.random()))",
            audio=None,
        ),
    ]

    script = _build_manim_script(scenes)

    module_part = script.split("class MainScene", 1)[0]
    assert "import random" in module_part
    assert "import math" in module_part
    assert "        import random" not in script
    assert "        import math" not in script


def test_static_check_labels_syntax_error_with_scene():
    scenes = [
        SceneInput(
            scene_index=0, narration="", description="镜头0", code="self.wait(1)", audio=None
        ),
        SceneInput(
            scene_index=1,
            narration="",
            description="镜头1",
            code="x = [1, 2\nself.wait(1)",
            audio=None,
        ),
    ]

    script = _build_manim_script(scenes)
    errors = _static_check(script)

    assert len(errors) == 1
    assert errors[0].startswith("scene 1: SyntaxError")


@pytest.mark.slow
async def test_validate_code_reports_all_undefined_names_at_once():
    scenes = [
        SceneInput(
            scene_index=0,
            narration="",
            description="镜头0",
            code="self.play(FadeIn(Dot()), rate_func=easey_bouncey)",
            audio=None,
        ),
        SceneInput(
            scene_index=1,
            narration="",
            description="镜头1",
            code="self.play(FadeOut(frac23_num))",
            audio=None,
        ),
    ]

    is_valid, errors = await ManimRenderEngine().validate_code(scenes)

    assert is_valid is False
    assert "scene 0: undefined name 'easey_bouncey'" in errors
    assert "scene 1: undefined name 'frac23_num'" in errors


@pytest.mark.slow
async def test_validate_code_passes_with_cross_scene_local_reference():
    scenes = [
        SceneInput(
            scene_index=0,
            narration="",
            description="定义局部变量",
            code="happy = Circle()\nself.add(happy)",
            audio=None,
        ),
        SceneInput(
            scene_index=1,
            narration="",
            description="跨镜头引用局部变量并整体清场",
            code="self.play(FadeOut(happy))\nself.clear_except()",
            audio=None,
        ),
    ]

    is_valid, errors = await ManimRenderEngine().validate_code(scenes)

    assert errors == ""
    assert is_valid is True


@pytest.mark.slow
async def test_validate_code_attributes_runtime_error_to_originating_scene():
    scenes = [
        SceneInput(scene_index=0, narration="", description="正常镜头", code="pass", audio=None),
        SceneInput(
            scene_index=1,
            narration="",
            description="引用未声明的跨镜头对象",
            code="self.play(Circumscribe(self.nonexistent))",
            audio=None,
        ),
    ]

    is_valid, errors = await ManimRenderEngine().validate_code(scenes)

    assert is_valid is False
    assert errors.startswith("scene 1:")
    assert "in _scene_1" in errors


@pytest.mark.slow
async def test_validate_code_stops_at_first_runtime_error():
    scene = SceneInput(
        scene_index=0,
        narration="",
        description="验证运行时错误立即停止",
        code='raise RuntimeError("root failure")\nraise ValueError("cascade noise")',
        audio=None,
    )

    is_valid, errors = await ManimRenderEngine().validate_code([scene])

    assert is_valid is False
    assert "RuntimeError: root failure" in errors
    assert "cascade noise" not in errors


def _write_silent_wav(path: Path, duration_seconds: float = 0.1) -> None:
    frame_rate = 8000
    n_frames = int(frame_rate * duration_seconds)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(frame_rate)
        wav_file.writeframes(b"\x00\x00" * n_frames)


# T14（集成验证）关于"渲染一个极小 manim 镜头并抽取关键帧"的引用说明：
# 这条集成用例已经被下面的 `test_render_produces_mp4_for_minimal_two_scene_script`
# （全画质渲染极小两镜头脚本得到 mp4，本文件）和
# `tests/engines/test_manim_preview.py::test_render_preview_returns_one_keyframe_per_beat`
# （低清预览 + 按 beat 抽取关键帧，T2）分别覆盖，不在这里重复写第三份。
# `tests/api/test_animation_flow.py`（T14）在完整链路（agent 一轮 → validate_scenes
# → render_preview → 创建渲染任务 → worker 产出成片 → 成片定稿）里再次真实调用了
# 这两条路径，验证的是"串起来"这件事，不是重新验证引擎本身的正确性。
@pytest.mark.slow
async def test_render_produces_mp4_for_minimal_two_scene_script(tmp_path):
    audio_path = tmp_path / "silence.wav"
    _write_silent_wav(audio_path)

    request = RenderRequest(
        scenes=[
            SceneInput(
                scene_index=0,
                narration="",
                description="镜头0",
                code="self.add(Dot())",
                audio=SceneAudio(scene_index=0, audio_path=str(audio_path), duration_seconds=0.1),
            ),
            SceneInput(
                scene_index=1,
                narration="",
                description="镜头1",
                code="self.add(Square())",
                audio=SceneAudio(scene_index=1, audio_path=str(audio_path), duration_seconds=0.1),
            ),
        ],
        output_format="mp4",
        resolution=(480, 270),
        fps=15,
    )

    result = await ManimRenderEngine().render(request)

    assert result.success is True, result.error_message
    assert isinstance(result, RenderResultWithBytes)
    assert result.output_path is not None
    assert result.output_path.endswith(".mp4")
    assert len(result.video_bytes) > 0
