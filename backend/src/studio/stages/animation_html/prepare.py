"""`animation_html` 阶段的 `prepare_turn`（设计 §6.2）。

可预期的错误（叙事缺失、timing 不一致、JSON 损坏）不抛异常——TurnRunner 会把它变成整轮失败；
改为删除旧的 `upstream/timeline.json` 并写 `upstream/timeline.error.txt`，
由工具和提示词向 agent 说明。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from studio.timeline import TimelineError, TimelineLayers, build_timeline, narration_from_documents

_EXEMPLAR = Path(__file__).parent / "exemplar" / "canvas-techniques.js"
TIMELINE_PATH = "upstream/timeline.json"
ERROR_PATH = "upstream/timeline.error.txt"


def _read_json(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path.relative_to(path.parents[2]).as_posix())
    return json.loads(path.read_text(encoding="utf-8"))


def _fail(workdir: Path, reason: str) -> None:
    (workdir / TIMELINE_PATH).unlink(missing_ok=True)
    error = workdir / ERROR_PATH
    error.parent.mkdir(parents=True, exist_ok=True)
    error.write_text(reason + "\n", encoding="utf-8")


def prepare_turn(workdir: Path) -> None:
    exemplar = workdir / "upstream" / "exemplar" / _EXEMPLAR.name
    exemplar.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_EXEMPLAR, exemplar)

    narrative_dir = workdir / "upstream" / "narrative"
    try:
        narrative = _read_json(narrative_dir / "narrative.json")
        timing = _read_json(narrative_dir / "timing.json")
        timeline = build_timeline(
            TimelineLayers(narration=narration_from_documents(narrative, timing))
        )
    except FileNotFoundError as exc:
        _fail(workdir, f"缺少上游叙事产物：{exc}（narrative 阶段需要先定稿并完成配音）")
    except json.JSONDecodeError as exc:
        _fail(workdir, f"上游叙事产物不是合法的 JSON：{exc}")
    except TimelineError as exc:
        _fail(workdir, str(exc))
    else:
        (workdir / ERROR_PATH).unlink(missing_ok=True)
        (workdir / TIMELINE_PATH).write_text(
            json.dumps(timeline.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
