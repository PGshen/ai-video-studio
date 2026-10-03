"""Manim 脚本拼装与静态分析：AST 变换、跨镜头名称提升、pyflakes/签名校验。

从 `../ai-video/backend/app/engines/render/manim.py` 迁移（原单文件 836 行按职责
拆分，决策记录 D1），只搬运脚本构建与静态检查相关的部分；子进程执行搬到
`process.py`，`ManimRenderEngine` 本体在 `engine.py`。
"""

from __future__ import annotations

import ast
import builtins
import inspect
import logging
import re

import manim
import pyflakes.checker
import pyflakes.messages as pyflakes_messages
from manim.utils import rate_functions as _manim_rate_functions

from studio.engines.render.base import SceneInput

logger = logging.getLogger(__name__)


_CHINESE_TEX_TEMPLATE_LINES = [
    '_chinese_tex_template = TexTemplate(tex_compiler="xelatex", output_format=".xdv")',
    r'_chinese_tex_template.add_to_preamble(r"\usepackage[UTF8,fontset=fandol]{ctex}")',
]
_DOUBLE_ESCAPED_TEX_COMMAND = re.compile(r"\\\\(?=[A-Za-z])")
_TEX_CONSTRUCTORS = {
    "BulletedList",
    "MathTex",
    "SingleStringMathTex",
    "Tex",
    "Title",
}
_SCENE_METHOD_RE = re.compile(r"^    def _scene_(\d+)\(self\):\s*$")

SCENE_END_MARKER = "__SCENE_END__"
"""渲染日志里标记"某镜头在视频时间轴上的结束时刻"的行前缀，格式
`__SCENE_END__ <镜头序号> <秒>`。由 `_build_manim_script(emit_scene_markers=True)`
写进脚本，`parse_scene_durations` 解析；成片按它切出每个镜头的字幕区间。"""
_SCENE_END_LINE_RE = re.compile(rf"^{SCENE_END_MARKER} (\d+) ([0-9.]+)\s*$", re.MULTILINE)


class _TexStringNormalizer(ast.NodeTransformer):
    """Repair LaTeX commands that were double-escaped by JSON/code generation."""

    def __init__(self) -> None:
        self.changed = False

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if not isinstance(node.value, str):
            return node

        normalized = _DOUBLE_ESCAPED_TEX_COMMAND.sub(r"\\", node.value)
        if normalized == node.value:
            return node

        self.changed = True
        return ast.copy_location(ast.Constant(value=normalized), node)


class _ManimImportStripper(ast.NodeTransformer):
    """Drop AI-generated ``import manim`` statements from per-scene code.

    ``_build_manim_script`` already emits ``from manim import *`` once at
    module level. When the model repeats it inside ``construct()``, it's a
    non-module-level import statement that pyflakes/Python reject.
    """

    def __init__(self) -> None:
        self.changed = False

    def visit_Import(self, node: ast.Import) -> ast.AST | None:
        if any(alias.name.partition(".")[0] == "manim" for alias in node.names):
            self.changed = True
            return None
        return node

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.AST | None:
        if node.module and node.module.partition(".")[0] == "manim":
            self.changed = True
            return None
        return node


class _RateFuncRewriter(ast.NodeTransformer):
    """Qualify bare rate-function names that Manim doesn't export top-level.

    Generated code routinely writes ``rate_func=ease_out_bounce``, but most
    easing functions live only in ``manim.utils.rate_functions`` (the
    ``rate_functions`` module itself *is* exported). Rewriting the bare name
    to ``rate_functions.<name>`` turns a guaranteed NameError into working
    code, deterministically.
    """

    def __init__(self) -> None:
        self.changed = False

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if (
            isinstance(node.ctx, ast.Load)
            and not hasattr(manim, node.id)
            and callable(getattr(_manim_rate_functions, node.id, None))
        ):
            self.changed = True
            return ast.copy_location(
                ast.Attribute(
                    value=ast.Name(id="rate_functions", ctx=ast.Load()),
                    attr=node.id,
                    ctx=ast.Load(),
                ),
                node,
            )
        return node


class _TexTemplateInjector(ast.NodeTransformer):
    """Make generated Tex/MathTex calls use a Chinese-capable template."""

    def __init__(self) -> None:
        self.source_changed = False
        self.template_injected = False

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if not _is_tex_constructor(node.func):
            return node

        normalizer = _TexStringNormalizer()
        node.args = [normalizer.visit(argument) for argument in node.args]
        if normalizer.changed:
            self.source_changed = True

        if any(keyword.arg == "tex_template" for keyword in node.keywords):
            return node

        node.keywords.append(
            ast.keyword(
                arg="tex_template",
                value=ast.Name(id="_chinese_tex_template", ctx=ast.Load()),
            )
        )
        self.source_changed = True
        self.template_injected = True
        return node


# Pyflakes message types that are noise when `from manim import *` is present:
# - ImportStarUsed: always fires for the wildcard import itself
# - UndefinedName / UndefinedLocal: pyflakes can't see inside the star, so it
#   falsely flags every Manim name (Circle, Text, Scene, …) as undefined
# - UnusedVariable: an assigned-but-unused local doesn't affect runtime
#   behavior, so it's not worth triggering a repair round over
# - UnusedImport: an unused import doesn't affect runtime behavior either
_PYFLAKES_STAR_NOISE = (
    pyflakes_messages.ImportStarUsed,
    pyflakes_messages.ImportStarUsage,  # "'X' may be undefined, or defined from star imports"
    pyflakes_messages.UndefinedName,
    pyflakes_messages.UndefinedLocal,
    pyflakes_messages.UnusedVariable,
    pyflakes_messages.UnusedImport,
)


def _scene_line_ranges(script: str) -> list[tuple[int, int, int]]:
    """Map each ``def _scene_N(self):`` method to its (start, end, scene_index) line span.

    Lines are 1-indexed to match ``ast``/pyflakes/traceback line numbers.
    """
    lines = script.splitlines()
    starts = [
        (lineno, int(m.group(1)))
        for lineno, m in (
            (i, _SCENE_METHOD_RE.match(line)) for i, line in enumerate(lines, start=1)
        )
        if m
    ]
    ranges = []
    for i, (start_line, scene_idx) in enumerate(starts):
        end_line = starts[i + 1][0] - 1 if i + 1 < len(starts) else len(lines)
        ranges.append((start_line, end_line, scene_idx))
    return ranges


def _scene_index_for_line(ranges: list[tuple[int, int, int]], lineno: int) -> int | None:
    for start, end, scene_idx in ranges:
        if start <= lineno <= end:
            return scene_idx
    return None


def _label_with_scene(message: str, lineno: int | None, ranges: list[tuple[int, int, int]]) -> str:
    scene_idx = _scene_index_for_line(ranges, lineno) if lineno is not None else None
    return f"scene {scene_idx}: {message}" if scene_idx is not None else message


def _static_check(script: str) -> list[str]:
    """Return actionable pyflakes diagnostics for the assembled Manim script.

    Star-import noise is filtered out because ``from manim import *`` makes it
    impossible for pyflakes to resolve Manim names statically. Each message is
    labeled with its originating scene (see ``_scene_line_ranges``) so repair
    prompts can be scoped to the scenes that actually need fixing.
    """
    ranges = _scene_line_ranges(script)
    try:
        tree = ast.parse(script)
    except SyntaxError as exc:
        # Line ranges are regex-derived, so scene attribution works even
        # when the script doesn't parse.
        return [_label_with_scene(f"SyntaxError: {exc}", exc.lineno, ranges)]
    w = pyflakes.checker.Checker(tree, "<manim_generated>")
    return [
        _label_with_scene(str(msg), getattr(msg, "lineno", None), ranges)
        for msg in w.messages
        if not isinstance(msg, _PYFLAKES_STAR_NOISE)
    ]


def _undefined_name_check(script: str) -> list[str]:
    """Report every bare name that cannot resolve at runtime — all scenes at once.

    pyflakes cannot do this (the star import blinds it to undefined names),
    and the dry run stops at the first NameError, burning one repair round per
    name. Whitelist per scene method: its own bindings, nested-scope bindings,
    module-level names of the assembled script, ``self``, the manim namespace,
    and builtins. Cross-scene references were already rewritten to ``self.``
    attributes by ``_promote_cross_scene_names``, so anything left bare and
    unbound is a genuine hallucination.
    """
    try:
        tree = ast.parse(script)
    except SyntaxError:
        return []  # _static_check already reported it with scene attribution

    module_names: set[str] = set()
    main_scene: ast.ClassDef | None = None
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                module_names.add((alias.asname or alias.name).partition(".")[0])
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    module_names.add(target.id)
        elif isinstance(node, ast.ClassDef) and node.name == "MainScene":
            main_scene = node
    if main_scene is None:
        return []

    errors: list[str] = []
    for method in main_scene.body:
        if not isinstance(method, ast.FunctionDef):
            continue
        match = re.fullmatch(r"_scene_(\d+)", method.name)
        if match is None:
            continue
        collector = _SceneNameCollector()
        collector.generic_visit(ast.Module(body=method.body, type_ignores=[]))
        allowed = collector.bound | collector.nested_bound | module_names | {"self"}
        for name in sorted(collector.loaded - allowed):
            if hasattr(manim, name) or hasattr(builtins, name):
                continue
            errors.append(
                f"scene {match.group(1)}: undefined name '{name}' —— "
                "该名称在本镜头与更早镜头都未定义，也不在 manim 命名空间中"
            )
    return errors


def _signature_check(script: str) -> list[str]:
    """Validate call-site arguments against real Manim callables' signatures.

    Catches "wrong number/name of arguments" (TypeError-class) mistakes for
    any call that resolves to a name in the ``manim`` namespace, without
    executing a single line of Manim code. This is the class of bug pyflakes
    can never catch (star-import makes names invisible to it, and arity
    checking isn't in its scope regardless): e.g. a hallucinated
    ``RoundedRectangle(width, height, corner_radius)`` positional signature
    when the real constructor only takes ``corner_radius`` plus keywords.
    """
    try:
        tree = ast.parse(script)
    except SyntaxError:
        return []

    ranges = _scene_line_ranges(script)
    errors: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _callable_name(node.func)
        if name is None:
            continue
        obj = getattr(manim, name, None)
        if obj is None or not (inspect.isclass(obj) or inspect.isfunction(obj)):
            continue
        # *args / **kwargs unpacking makes static arity checking meaningless.
        if any(isinstance(arg, ast.Starred) for arg in node.args):
            continue
        if any(kw.arg is None for kw in node.keywords):
            continue

        target = obj.__init__ if inspect.isclass(obj) else obj
        try:
            params = list(inspect.signature(target).parameters.values())
        except (TypeError, ValueError):
            continue
        if inspect.isclass(obj) and params and params[0].name == "self":
            params = params[1:]

        try:
            inspect.Signature(params).bind(
                *([None] * len(node.args)),
                **{kw.arg: None for kw in node.keywords if kw.arg is not None},
            )
        except TypeError as exc:
            errors.append(
                _label_with_scene(f"line {node.lineno}: {name}(...) {exc}", node.lineno, ranges)
            )

    return errors


def _callable_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_tex_constructor(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id in _TEX_CONSTRUCTORS
    if isinstance(node, ast.Attribute):
        return node.attr in _TEX_CONSTRUCTORS
    return False


class _SceneNameCollector(ast.NodeVisitor):
    """Collect method-scope bindings and loads for one scene's code.

    Names bound inside nested scopes (def/lambda parameters, comprehension
    targets, nested function locals) are tracked separately: promoting one of
    those to a ``self.`` attribute would change its meaning or produce invalid
    syntax, so they disqualify a name from promotion entirely.
    """

    _NESTED_SCOPES = (
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.Lambda,
        ast.ListComp,
        ast.SetComp,
        ast.DictComp,
        ast.GeneratorExp,
        ast.ClassDef,
    )

    def __init__(self) -> None:
        self.bound: set[str] = set()
        self.loaded: set[str] = set()
        self.nested_bound: set[str] = set()
        self._depth = 0

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.loaded.add(node.id)
        else:
            (self.nested_bound if self._depth else self.bound).add(node.id)

    def _visit_nested(self, node: ast.AST) -> None:
        arguments = getattr(node, "args", None)
        if isinstance(arguments, ast.arguments):
            for arg in (
                *arguments.posonlyargs,
                *arguments.args,
                *arguments.kwonlyargs,
                *filter(None, (arguments.vararg, arguments.kwarg)),
            ):
                self.nested_bound.add(arg.arg)
        self._depth += 1
        self.generic_visit(node)
        self._depth -= 1

    def generic_visit(self, node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, self._NESTED_SCOPES):
                name = getattr(child, "name", None)
                if name is not None:
                    (self.nested_bound if self._depth else self.bound).add(name)
                self._visit_nested(child)
            else:
                self.generic_visit(child)
        if isinstance(node, ast.Name):
            self.visit_Name(node)


class _CrossSceneNameRewriter(ast.NodeTransformer):
    """Rewrite promoted names to ``self.<name>`` attribute access."""

    def __init__(self, promoted: set[str]) -> None:
        self.promoted = promoted
        self.changed = False

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if node.id not in self.promoted:
            return node
        self.changed = True
        return ast.copy_location(
            ast.Attribute(
                value=ast.Name(id="self", ctx=ast.Load()),
                attr=node.id,
                ctx=node.ctx,
            ),
            node,
        )


class _ImportHoister(ast.NodeTransformer):
    """Remove scene-level import statements, keeping them for module-level reuse."""

    def __init__(self) -> None:
        self.hoisted: list[str] = []

    def visit_Import(self, node: ast.Import) -> ast.AST | None:
        self.hoisted.append(ast.unparse(node))
        return None

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.AST | None:
        self.hoisted.append(ast.unparse(node))
        return None


def _hoist_scene_imports(codes: list[str]) -> tuple[list[str], list[str]]:
    """Move scene-level imports (math/random/numpy/…) to the module header.

    ``import X`` inside a method is legal Python, but keeping generated
    imports at module level makes them shared, deduplicated, and immune to
    style-rule churn in repair rounds. Manim imports were already stripped by
    ``_prepare_manim_code``; whatever remains is hoisted verbatim.
    """
    header: list[str] = []
    out: list[str] = []
    for code in codes:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            out.append(code)
            continue
        hoister = _ImportHoister()
        tree = hoister.visit(tree)
        if not hoister.hoisted:
            out.append(code)
            continue
        for statement in hoister.hoisted:
            if statement not in header:
                header.append(statement)
        ast.fix_missing_locations(tree)
        out.append(ast.unparse(tree) if tree.body else "pass")
    return out, header


def _promote_cross_scene_names(codes: list[str]) -> list[str]:
    """Auto-promote locals that later scenes reference into ``self.`` attributes.

    Each scene runs in its own ``_scene_N`` method, so a plain local from
    scene i is invisible to scene j — but generated code routinely references
    earlier scenes' objects by bare name (especially in transition FadeOut
    lists). Instead of failing at dry-run one NameError at a time, detect the
    pattern statically: a name loaded in some scene without a local binding,
    that an *earlier* scene did bind, is rewritten to ``self.<name>`` at every
    occurrence in every scene. Names that shadow Manim/builtin names or are
    bound in nested scopes are left untouched; purely scene-private locals are
    unaffected.
    """
    trees: list[ast.Module] = []
    for code in codes:
        try:
            trees.append(ast.parse(code))
        except SyntaxError:
            return codes  # let dry-run report the real error with context

    collectors: list[_SceneNameCollector] = []
    for tree in trees:
        collector = _SceneNameCollector()
        collector.generic_visit(tree)
        collectors.append(collector)

    unsafe = set().union(*(c.nested_bound for c in collectors)) if collectors else set()
    promoted: set[str] = set()
    bound_earlier: set[str] = set()
    for collector in collectors:
        for name in collector.loaded - collector.bound:
            if (
                name in bound_earlier
                and name not in unsafe
                and not hasattr(manim, name)
                and not hasattr(builtins, name)
            ):
                promoted.add(name)
        bound_earlier |= collector.bound

    if not promoted:
        return codes

    logger.info("[ManimScript] promoted cross-scene names: %s", sorted(promoted))
    out: list[str] = []
    for code, tree in zip(codes, trees, strict=True):
        rewriter = _CrossSceneNameRewriter(promoted)
        new_tree = rewriter.visit(tree)
        if rewriter.changed:
            ast.fix_missing_locations(new_tree)
            out.append(ast.unparse(new_tree))
        else:
            out.append(code)
    return out


def _prepare_manim_code(code: str) -> tuple[str, bool]:
    """Prepare generated formulas for reliable Chinese LaTeX rendering.

    Tex/MathTex calls receive a Chinese-capable template, and doubled command
    escapes such as ``\\frac`` are repaired without changing LaTeX ``\\ ``
    line breaks.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        # Keep the original source so Manim can report the actual code error.
        return code, False

    stripper = _ManimImportStripper()
    tree = stripper.visit(tree)

    injector = _TexTemplateInjector()
    tree = injector.visit(tree)

    rate_func_rewriter = _RateFuncRewriter()
    tree = rate_func_rewriter.visit(tree)

    if not stripper.changed and not injector.source_changed and not rate_func_rewriter.changed:
        return code, False

    ast.fix_missing_locations(tree)
    return ast.unparse(tree), injector.template_injected


def parse_scene_durations(render_log: str, expected: int) -> list[float] | None:
    """从渲染日志里的 `SCENE_END_MARKER` 行还原每个镜头的实际时长；标记缺失或
    数量不对（比如日志被截断）时返回 `None`，由调用方回退到声明时长。
    """
    end_times = {
        int(m.group(1)): float(m.group(2)) for m in _SCENE_END_LINE_RE.finditer(render_log)
    }
    if set(end_times) != set(range(expected)):
        return None
    ends = [end_times[i] for i in range(expected)]
    return [end - start for start, end in zip([0.0, *ends[:-1]], ends, strict=True)]


def _build_manim_script(
    scenes: list[SceneInput],
    include_audio: bool = True,
    resolution: tuple[int, int] | None = None,
    emit_scene_markers: bool = False,
) -> str:
    prepared_scenes = []
    needs_chinese_tex_template = False
    for scene in scenes:
        prepared_code, changed = _prepare_manim_code(scene.code)
        prepared_scenes.append((scene, prepared_code))
        needs_chinese_tex_template = needs_chinese_tex_template or changed

    codes, hoisted_imports = _hoist_scene_imports([code for _, code in prepared_scenes])
    codes = _promote_cross_scene_names(codes)
    prepared_scenes = [
        (scene, code) for (scene, _), code in zip(prepared_scenes, codes, strict=True)
    ]

    lines = ["from manim import *"]
    lines.extend(hoisted_imports)
    lines.append("")
    if resolution is not None:
        width, height = resolution
        frame_width = 8.0 * width / height
        lines.extend(
            [
                f"config.pixel_width = {width}",
                f"config.pixel_height = {height}",
                f"config.frame_width = {frame_width:.6f}",
                "config.frame_height = 8.0",
                "",
            ]
        )
    if needs_chinese_tex_template:
        lines.extend(_CHINESE_TEX_TEMPLATE_LINES)
        lines.append("")
    lines.extend(
        [
            "",
            "class MainScene(Scene):",
            "    def clear_except(self, *keep):",
            '        """Fade out every on-screen mobject not passed in keep."""',
            "        _keep_ids = {id(m) for m in keep}",
            "        _doomed = [m for m in self.mobjects if id(m) not in _keep_ids]",
            "        if _doomed:",
            "            self.play(*[FadeOut(m) for m in _doomed], run_time=0.4)",
            "",
            "    def construct(self):",
        ]
    )
    for i in range(len(prepared_scenes)):
        lines.append(f"        self._scene_{i}()")
    lines.append("")

    # Each scene gets its own method scope (rather than being pasted flat
    # into construct()) so a local variable declared in one scene cannot be
    # silently referenced from another: cross-scene sharing must go through
    # an explicit `self.xxx` attribute. This also gives error messages a
    # precise scene attribution — pyflakes/AST line ranges via
    # `_scene_line_ranges`, and runtime tracebacks via the `_scene_N` frame
    # name itself (see `_TRACEBACK_SCENE_RE` in `process.py`).
    for i, (scene, prepared_code) in enumerate(prepared_scenes):
        lines.append(f"    def _scene_{i}(self):")
        lines.append(f"        # Scene {i}: {scene.description}")
        duration = 0.0
        if include_audio:
            audio_path = scene.audio.audio_path if scene.audio else f"scene_{i}_audio.mp3"
            duration = scene.audio.duration_seconds if scene.audio else 0.0
            lines.append(f"        _t0_{i} = self.renderer.time")
            lines.append(f"        self.add_sound({audio_path!r})")
        for code_line in prepared_code.splitlines():
            lines.append(f"        {code_line}")
        if include_audio:
            lines.append(f"        _rem_{i} = {duration:.3f} - (self.renderer.time - _t0_{i})")
            lines.append(f"        if _rem_{i} > 0:")
            lines.append(f"            self.wait(_rem_{i})")
        if emit_scene_markers:
            lines.append(
                f'        print(f"{SCENE_END_MARKER} {i} {{self.renderer.time:.3f}}", flush=True)'
            )
        lines.append("")
    return "\n".join(lines)
