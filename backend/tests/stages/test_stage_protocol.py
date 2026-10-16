"""所有真实阶段的协议约束（open-mode 设计 §5）。

只有完全自由阶段用运行时默认提示词、放开命令联网。
"""

from __future__ import annotations

import pytest

from studio.agent.stage import StageDefinition
from studio.db.repo.settings import STAGES as DEFAULT_PROFILE_STAGES
from studio.stages.animation_html import STAGE as ANIMATION_HTML_STAGE
from studio.stages.brainstorm import STAGE as BRAINSTORM_STAGE
from studio.stages.concept import STAGE as CONCEPT_STAGE
from studio.stages.free_explainer import STAGE as FREE_EXPLAINER_STAGE
from studio.stages.free_produce import STAGE as FREE_PRODUCE_STAGE
from studio.stages.music import STAGE as MUSIC_STAGE
from studio.stages.narrative import STAGE as NARRATIVE_STAGE
from studio.stages.open import STAGE as OPEN_STAGE
from studio.stages.produce import STAGE as PRODUCE_STAGE
from studio.stages.style import STAGE as STYLE_STAGE
from studio.stages.topic import STAGE as TOPIC_STAGE

PROMPTED_STAGES: list[StageDefinition] = [
    BRAINSTORM_STAGE,
    TOPIC_STAGE,
    NARRATIVE_STAGE,
    ANIMATION_HTML_STAGE,
    CONCEPT_STAGE,
    MUSIC_STAGE,
    PRODUCE_STAGE,
    FREE_EXPLAINER_STAGE,
    FREE_PRODUCE_STAGE,
    STYLE_STAGE,
]


@pytest.mark.parametrize("stage", PROMPTED_STAGES, ids=lambda s: s.name)
def test_existing_stages_keep_their_own_prompt_and_offline_commands(
    stage: StageDefinition,
) -> None:
    prompt = stage.system_prompt()
    assert isinstance(prompt, str) and prompt.strip()
    assert stage.exec_network is False


def test_every_stage_can_have_a_default_model() -> None:
    """设置里「各阶段默认模型」接受的阶段与实际注册的阶段一致（漏掉的阶段保存默认值会 422）。"""
    registered = {stage.name for stage in PROMPTED_STAGES} | {OPEN_STAGE.name}
    assert set(DEFAULT_PROFILE_STAGES) == registered
