"""`animation_html` 阶段的 `prepare_turn`（设计 §6.2）。

可预期的错误（叙事缺失、timing 不一致、JSON 损坏）不抛异常——TurnRunner 会把它变成整轮失败；
改为删除旧的 `upstream/timeline.json` 并写 `upstream/timeline.error.txt`，
由工具和提示词向 agent 说明。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from studio.stages.common.music_source import find_source
from studio.timeline import TimelineError, TimelineLayers, build_timeline, narration_from_documents
from studio.timeline.load import TimelineSources, load_timeline

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


def _is_music_video(upstream: Path) -> bool:
    """MV = 上游音乐是导入形态：有 `music/source.<ext>`（与 `music` 阶段同一信号）
    且有 `sections.json`。只有 `sections.json`（合成形态也允许写它）不算 MV。
    """
    music = upstream / "music"
    return (music / "sections.json").is_file() and find_source(music) is not None


def _prepare_music_project(workdir: Path) -> None:
    """短片、MV 与"讲解 + 背景乐"：按上游内容选来源，读出带网格与配乐层的时间轴。"""
    upstream = workdir / "upstream"
    reel = (upstream / "beatsheet" / "beatsheet.json").is_file()
    mv = _is_music_video(upstream)
    sources = TimelineSources(
        workdir,
        narration=not reel and not mv,
        music_source="import" if mv else "synth",
        prefix="upstream/",
    )
    try:
        loaded = load_timeline(sources)
    except TimelineError as exc:
        _fail(workdir, "；".join(exc.errors))
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        _fail(workdir, f"上游产物的结构不符合预期：{type(exc).__name__}: {exc}")
    else:
        (workdir / ERROR_PATH).unlink(missing_ok=True)
        (workdir / TIMELINE_PATH).write_text(
            json.dumps(loaded.timeline.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def prepare_turn(workdir: Path) -> None:
    exemplar = workdir / "upstream" / "exemplar" / _EXEMPLAR.name
    exemplar.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_EXEMPLAR, exemplar)

    upstream = workdir / "upstream"
    if (
        (upstream / "beatsheet" / "beatsheet.json").is_file()
        or (upstream / "music" / "events.json").is_file()
        or _is_music_video(upstream)
    ):
        _prepare_music_project(workdir)
        return

    narrative_dir = workdir / "upstream" / "narrative"
    try:
        narrative = _read_json(narrative_dir / "narrative.json")
        timing = _read_json(narrative_dir / "timing.json")
        timeline = build_timeline(
            TimelineLayers(narration=narration_from_documents(narrative, timing))
        )
    except FileNotFoundError as exc:
        _fail(workdir, f"缺少上游叙事产物：{exc}（narrative 阶段需要先定稿并完成配音）")
    except TimelineError as exc:
        _fail(workdir, "；".join(exc.errors))
    except json.JSONDecodeError as exc:
        _fail(workdir, f"上游叙事产物不是合法的 JSON：{exc}")
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        _fail(workdir, f"上游叙事产物的结构不符合预期：{type(exc).__name__}: {exc}")
    else:
        (workdir / ERROR_PATH).unlink(missing_ok=True)
        (workdir / TIMELINE_PATH).write_text(
            json.dumps(timeline.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
