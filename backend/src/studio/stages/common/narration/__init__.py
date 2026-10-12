"""旁白（叙事 + 配音）的共用件：`narrative.json` 的校验与规范化、
`validate_narrative`、`synthesize_tts`。

`narrative` 阶段与自由讲解 `free_explainer` 共用（free-mode 设计 §5.2；各阶段之间互不 import）。
"""

from studio.stages.common.narration.schema import NarrativeValidationError, validate_and_normalize
from studio.stages.common.narration.synthesize_tts import SYNTHESIZE_TTS_TOOL
from studio.stages.common.narration.validate_narrative import VALIDATE_NARRATIVE_TOOL

__all__ = [
    "SYNTHESIZE_TTS_TOOL",
    "VALIDATE_NARRATIVE_TOOL",
    "NarrativeValidationError",
    "validate_and_normalize",
]
