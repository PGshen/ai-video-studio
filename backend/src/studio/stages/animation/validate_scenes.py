"""`validate_scenes` 工具（设计 §5.3；计划 T7）：静态校验动画阶段的镜头代码。

从 `upstream/narrative/narrative.json`（`workspace.upstream` 已经物化好的
只读副本，本工具只消费不管物化）按顺序取出镜头 id，读取工作区
`animation/scenes/<scene_id>.py`：缺失或为空的镜头直接报错（不进引擎，
因为引擎根本没有代码可校验）；全部存在时交给
`ManimRenderEngine.validate_code` 做静态校验（AST 语法/未定义名称/签名/
一次 dry-run）。

`SceneInput` 用 `scene_index`（从 0 开始的位置）标识镜头，引擎返回的错误
文本点名的是 `scene_index`（形如 `"scene 1: ..."`），不认识 `scene_id`——
`_relabel_scene_errors` 把这类前缀换算成对应的 `scene_id`，不依赖引擎层
知道 `scene_id` 的存在（`ManimRenderEngine`/`engines.render` 完全不认识
`narrative.json` 这个概念）。
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel

from studio.agent.tools import ToolContext, ToolResult, ToolSpec
from studio.engines.render.base import SceneInput
from studio.engines.render.manim import ManimRenderEngine
from studio.workspace import files

_SCENES_DIR = "animation/scenes"
_NARRATIVE_PATH = "upstream/narrative/narrative.json"
_SCENE_ERROR_RE = re.compile(r"scene (\d+):")


class ValidateScenesArgs(BaseModel):
    """`validate_scenes` 无入参：总是校验当前工作区里的全部镜头。"""


def _scene_ids(ctx: ToolContext) -> list[str]:
    """按 `narrative.json` 里 `scenes[]` 的顺序返回镜头 id 列表。"""
    narrative_path = files.safe_path(ctx.workdir, _NARRATIVE_PATH)
    narrative = json.loads(narrative_path.read_text(encoding="utf-8"))
    return [scene["id"] for scene in narrative["scenes"]]


def _relabel_scene_errors(error_text: str, scene_ids: list[str]) -> str:
    """把引擎错误文本里的 `"scene N:"` 前缀换算成对应的 `scene_id`。"""

    def _replace(match: re.Match[str]) -> str:
        index = int(match.group(1))
        scene_id = scene_ids[index] if 0 <= index < len(scene_ids) else f"#{index}"
        return f"镜头 {scene_id}（scene {index}）:"

    return _SCENE_ERROR_RE.sub(_replace, error_text)


async def _handler(ctx: ToolContext, args: ValidateScenesArgs) -> ToolResult:
    scene_ids = _scene_ids(ctx)

    missing: list[str] = []
    codes: list[str] = []
    for scene_id in scene_ids:
        scene_path = files.safe_path(ctx.workdir, f"{_SCENES_DIR}/{scene_id}.py")
        code = scene_path.read_text(encoding="utf-8") if scene_path.is_file() else ""
        if not code.strip():
            missing.append(scene_id)
        else:
            codes.append(code)

    if missing:
        return ToolResult(
            text="以下镜头缺少代码或代码为空，需要先写好再校验：" + "、".join(missing),
            is_error=True,
        )

    scenes = [
        SceneInput(scene_index=index, narration="", description=scene_id, code=code, audio=None)
        for index, (scene_id, code) in enumerate(zip(scene_ids, codes, strict=True))
    ]

    is_valid, error_text = await ManimRenderEngine().validate_code(scenes)
    if not is_valid:
        return ToolResult(text=_relabel_scene_errors(error_text, scene_ids), is_error=True)

    return ToolResult(text=f"全部 {len(scene_ids)} 个镜头静态校验通过。")


VALIDATE_SCENES_TOOL = ToolSpec(
    name="validate_scenes",
    description="静态校验 animation/scenes/ 下的全部镜头代码，失败时点名具体镜头。",
    input_model=ValidateScenesArgs,
    stages={"animation"},
    handler=_handler,
)
