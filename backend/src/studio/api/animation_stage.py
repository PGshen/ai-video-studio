"""项目的"出片阶段"名：`animation_html`（讲解的 HTML 动画）、`produce`（短片、MV 的配乐与
动画），或老 manim 项目的 `animation`（Manim 已下线，ADR 0027，只读）。

由项目流水线（`settings["pipeline"]`）决定；老项目没有该字段时回落 `animation`。渲染任务、
成片定稿和镜头检查状态共用这一处解析，不再各自写死阶段名。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Engine

from studio.db.repo.projects import get_project

RETIRED_MANIM_STAGE = "animation"
"""老 manim 项目的出片阶段：不再注册，不能渲染或定稿。"""
HTML_STAGE = "animation_html"
PRODUCE_STAGE = "produce"
MANIM_RETIRED_DETAIL = "Manim 动画已下线，老项目只能查看，不能再渲染或定稿成片"


def animation_stage_of(settings: Mapping[str, Any]) -> str:
    pipeline = settings.get("pipeline")
    if isinstance(pipeline, list):
        if PRODUCE_STAGE in pipeline:
            return PRODUCE_STAGE
        if HTML_STAGE in pipeline:
            return HTML_STAGE
    return RETIRED_MANIM_STAGE


def animation_stage(engine: Engine, project_id: str) -> str:
    project = get_project(engine, project_id)
    return animation_stage_of(project.settings) if project is not None else RETIRED_MANIM_STAGE


def require_live_animation_stage(engine: Engine, project_id: str) -> str:
    """出片阶段名；老 manim 项目抛 409（Manim 已下线，不能渲染或定稿成片）。"""
    stage = animation_stage(engine, project_id)
    if stage == RETIRED_MANIM_STAGE:
        raise HTTPException(status_code=409, detail=MANIM_RETIRED_DETAIL)
    return stage
