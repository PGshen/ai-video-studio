"""按镜头 id 聚合 `validate_scenes`/`render_preview` 最近状态（TD-33 的读模型）。

不新增任何表：直接从已有的 `sessions`/`turns`/`turn_events`/`snapshots` 在
读时聚合——`validate_scenes`/`render_preview` 的持久化格式完全不变，设计
§3.1 的表数量不变（AGENTS.md 红线：不引入计划之外的新依赖/公共接口，不
改动已批准的设计）。

## 怎么判断"已过期"（stale）

镜头代码文件（`animation/scenes/<scene_id>.py`）的内容哈希已经存在于快照
`manifest`（`{相对路径: sha256}`）里，不需要另外存一份：把"做这次检查的
那一轮结束时的快照"（`turns.end_snapshot_id`）里这个路径的哈希，和"项目
当前最新快照"里同一路径的哈希比较，不同（或那一轮还没有 `end_snapshot_id`，
理论上只会发生在它还在运行的极窄窗口内）就认为"已过期"——保守地认为需要
重新检查，而不是默认"还有效"。

## `validate_scenes` 的镜头归属

`validate_scenes` 一次校验全部镜头，不是逐镜头调用；持久化的 `tool_result.text`
只有三种形状（`stages/animation/validate_scenes.py::_handler`）：

- 全部通过：`"全部 N 个镜头静态校验通过。"`——这是一条"项目级"通过记录，
  对所有镜头都成立，除非某个镜头有更新的失败记录。
- 缺代码：`"以下镜头缺少代码或代码为空，需要先写好再校验：a、b"`。
- 校验错误：`_relabel_scene_errors` 生成的 `"镜头 a（scene 0）: ..."`（可能
  同时点名多个镜头）。

后两种都点名了具体镜头 id，只标这些镜头"校验失败"；不点名的镜头仍然沿用
"最近一次全部通过"的结果（按时间戳，谁新听谁的）。

`render_preview` 每次只测一个镜头，`ToolCall.args["scene_id"]` 直接给出，
不需要解析文本，精确到镜头。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import Engine

from studio.db.repo.sessions import list_sessions
from studio.db.repo.snapshots import get_snapshot, latest_snapshot
from studio.db.repo.turns import TurnValue, get_turn, list_events

_ANIMATION_STAGE = "animation"
_VALIDATE_TOOL = "validate_scenes"
_PREVIEW_TOOL = "render_preview"
_SCENE_PATH_TEMPLATE = "animation/scenes/{scene_id}.py"

_MISSING_RE = re.compile(r"以下镜头缺少代码或代码为空，需要先写好再(?:校验|预览)：(.+)")
_SCENE_NAME_RE = re.compile(r"镜头 (\S+?)（scene \d+）")

CheckOutcome = Literal["passed", "failed", "not_checked"]


@dataclass(frozen=True, slots=True)
class SceneCheck:
    status: CheckOutcome
    stale: bool
    checked_at: datetime | None


@dataclass(frozen=True, slots=True)
class SceneChecks:
    validate_scenes: SceneCheck
    render_preview: SceneCheck


_NOT_CHECKED = SceneCheck(status="not_checked", stale=False, checked_at=None)


def _scene_ids_named_in_validate_failure(text: str) -> set[str]:
    """从一次校验失败的 `tool_result.text` 里提取被点名的镜头 id。"""
    missing_match = _MISSING_RE.search(text)
    if missing_match:
        return {sid.strip() for sid in missing_match.group(1).split("、") if sid.strip()}
    return set(_SCENE_NAME_RE.findall(text))


@dataclass(frozen=True, slots=True)
class _RawEvent:
    checked_at: datetime
    kind: Literal["validate_all_passed", "validate_failure", "preview"]
    scene_id: str | None
    passed: bool
    turn_id: str


def _collect_raw_events(engine: Engine, project_id: str) -> list[_RawEvent]:
    events: list[_RawEvent] = []
    for session in list_sessions(engine, project_id, _ANIMATION_STAGE):
        pending_calls: dict[str, dict[str, object]] = {}
        for event in list_events(engine, session.id):
            if event.type == "tool_call" and event.payload.get("name") in (
                _VALIDATE_TOOL,
                _PREVIEW_TOOL,
            ):
                pending_calls[str(event.payload["call_id"])] = event.payload
                continue
            if event.type != "tool_result":
                continue
            call = pending_calls.pop(str(event.payload["call_id"]), None)
            if call is None:
                continue
            is_error = bool(event.payload["is_error"])
            turn_id = str(event.payload["turn_id"])
            if call["name"] == _PREVIEW_TOOL:
                args = call.get("args")
                scene_id = args.get("scene_id") if isinstance(args, dict) else None
                if isinstance(scene_id, str):
                    events.append(
                        _RawEvent(event.created_at, "preview", scene_id, not is_error, turn_id)
                    )
            elif is_error:
                for scene_id in _scene_ids_named_in_validate_failure(str(event.payload["text"])):
                    events.append(
                        _RawEvent(event.created_at, "validate_failure", scene_id, False, turn_id)
                    )
            else:
                events.append(
                    _RawEvent(event.created_at, "validate_all_passed", None, True, turn_id)
                )
    return events


def compute_scene_checks(
    engine: Engine, project_id: str, scene_ids: list[str]
) -> dict[str, SceneChecks]:
    events = sorted(_collect_raw_events(engine, project_id), key=lambda e: e.checked_at)

    latest_all_passed: tuple[datetime, str] | None = None
    latest_validate_failure: dict[str, tuple[datetime, str]] = {}
    latest_preview: dict[str, tuple[datetime, bool, str]] = {}
    for event in events:
        if event.kind == "validate_all_passed":
            latest_all_passed = (event.checked_at, event.turn_id)
        elif event.kind == "validate_failure":
            assert event.scene_id is not None
            latest_validate_failure[event.scene_id] = (event.checked_at, event.turn_id)
        else:
            assert event.scene_id is not None
            latest_preview[event.scene_id] = (event.checked_at, event.passed, event.turn_id)

    current = latest_snapshot(engine, project_id)
    current_manifest = current.manifest if current is not None else {}

    turn_cache: dict[str, TurnValue | None] = {}

    def _end_manifest(turn_id: str) -> dict[str, str] | None:
        if turn_id not in turn_cache:
            turn_cache[turn_id] = get_turn(engine, turn_id)
        turn = turn_cache[turn_id]
        if turn is None or turn.end_snapshot_id is None:
            return None
        snapshot = get_snapshot(engine, turn.end_snapshot_id)
        return snapshot.manifest if snapshot is not None else None

    def _check_at(path: str, checked_at: datetime, passed: bool, turn_id: str) -> SceneCheck:
        end_manifest = _end_manifest(turn_id)
        stale = end_manifest is None or end_manifest.get(path) != current_manifest.get(path)
        return SceneCheck(
            status="passed" if passed else "failed", stale=stale, checked_at=checked_at
        )

    def _validate_status(scene_id: str) -> SceneCheck:
        path = _SCENE_PATH_TEMPLATE.format(scene_id=scene_id)
        failure = latest_validate_failure.get(scene_id)
        is_newer_failure = failure is not None and (
            latest_all_passed is None or failure[0] > latest_all_passed[0]
        )
        if failure is not None and is_newer_failure:
            checked_at, turn_id = failure
            return _check_at(path, checked_at, False, turn_id)
        if latest_all_passed is not None:
            checked_at, turn_id = latest_all_passed
            return _check_at(path, checked_at, True, turn_id)
        return _NOT_CHECKED

    def _preview_status(scene_id: str) -> SceneCheck:
        entry = latest_preview.get(scene_id)
        if entry is None:
            return _NOT_CHECKED
        checked_at, passed, turn_id = entry
        path = _SCENE_PATH_TEMPLATE.format(scene_id=scene_id)
        return _check_at(path, checked_at, passed, turn_id)

    return {
        scene_id: SceneChecks(
            validate_scenes=_validate_status(scene_id), render_preview=_preview_status(scene_id)
        )
        for scene_id in scene_ids
    }
