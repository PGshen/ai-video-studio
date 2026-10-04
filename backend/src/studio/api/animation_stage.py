"""项目的动画阶段名：`animation`（Manim）或 `animation_html`（HTML 引擎）。

由项目流水线（`settings["pipeline"]`）决定；老项目没有该字段时回落 `animation`。渲染任务、
成片定稿和镜头检查状态共用这一处解析，不再各自写死阶段名。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import Engine

from studio.db.repo.projects import get_project

MANIM_STAGE = "animation"
HTML_STAGE = "animation_html"


def animation_stage_of(settings: Mapping[str, Any]) -> str:
    pipeline = settings.get("pipeline")
    if isinstance(pipeline, list) and HTML_STAGE in pipeline:
        return HTML_STAGE
    return MANIM_STAGE


def animation_stage(engine: Engine, project_id: str) -> str:
    project = get_project(engine, project_id)
    return animation_stage_of(project.settings) if project is not None else MANIM_STAGE
