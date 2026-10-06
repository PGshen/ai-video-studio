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

## HTML 引擎（`animation_html`）

阶段名由 `api.animation_stage` 按项目流水线解析，两组工具各有一张"档案"（工具名、镜头文件
路径模板）。`validate_scenes_html` 的归属规则（输出形状见该工具模块顶部文档）：调用参数带
`scene_id` → 结果只属于该镜头；不带且成功 → 项目级通过；不带且失败 → 按行首 `镜头 <id>：`
点名失败镜头（`警告 镜头` 行不算），一个也没点名（页面级错误）→ 对所有镜头记为失败。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import Engine

from studio.api.animation_stage import animation_stage
from studio.db.repo.sessions import list_sessions
from studio.db.repo.snapshots import get_snapshot, latest_snapshot
from studio.db.repo.turns import TurnValue, get_turn, list_events

_MISSING_RE = re.compile(r"以下镜头缺少代码或代码为空，需要先写好再(?:校验|预览)：(.+)")
_SCENE_NAME_RE = re.compile(r"镜头 (\S+?)（scene \d+）")
_HTML_SCENE_ERROR_RE = re.compile(r"^镜头 (\S+?)：", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class _Profile:
    stage: str
    validate_tool: str
    preview_tool: str
    scene_path_template: str
    html: bool


_PROFILES = {
    "animation": _Profile(
        "animation", "validate_scenes", "render_preview", "animation/scenes/{scene_id}.py", False
    ),
    "animation_html": _Profile(
        "animation_html",
        "validate_scenes_html",
        "render_preview_html",
        "animation/scenes/{scene_id}.js",
        True,
    ),
    # `produce` (reel, MV) uses the same two tools and scene files as the HTML explainer.
    "produce": _Profile(
        "produce",
        "validate_scenes_html",
        "render_preview_html",
        "animation/scenes/{scene_id}.js",
        True,
    ),
}

CheckOutcome = Literal["passed", "failed", "not_checked"]


@dataclass(frozen=True, slots=True)
class SceneCheck:
    status: CheckOutcome
    stale: bool
    checked_at: datetime | None
    images: tuple[str, ...] = ()
    """该次检查结果里的图片 blob sha256（`render_preview` 的关键帧，按出现顺序）。"""


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


def _image_shas(raw: object) -> tuple[str, ...]:
    """从 `tool_result.images`（`[{media_type, sha256}]`）取出 sha256 列表；形状不对时忽略。"""
    if not isinstance(raw, list):
        return ()
    return tuple(
        item["sha256"]
        for item in raw
        if isinstance(item, dict) and isinstance(item.get("sha256"), str)
    )


@dataclass(frozen=True, slots=True)
class _RawEvent:
    checked_at: datetime
    kind: Literal[
        "validate_all_passed",
        "validate_scene_passed",
        "validate_failure",
        "validate_failure_all",
        "preview",
    ]
    scene_id: str | None
    passed: bool
    turn_id: str
    images: tuple[str, ...] = ()


def _html_validate_events(
    when: datetime, text: str, args: object, is_error: bool, turn_id: str
) -> list[_RawEvent]:
    scene_id = args.get("scene_id") if isinstance(args, dict) else None
    if isinstance(scene_id, str):
        kind = "validate_failure" if is_error else "validate_scene_passed"
        return [_RawEvent(when, kind, scene_id, not is_error, turn_id)]
    if not is_error:
        return [_RawEvent(when, "validate_all_passed", None, True, turn_id)]
    named = list(dict.fromkeys(_HTML_SCENE_ERROR_RE.findall(text)))
    if not named:
        return [_RawEvent(when, "validate_failure_all", None, False, turn_id)]
    return [_RawEvent(when, "validate_failure", sid, False, turn_id) for sid in named]


def _collect_raw_events(engine: Engine, project_id: str, profile: _Profile) -> list[_RawEvent]:
    events: list[_RawEvent] = []
    for session in list_sessions(engine, project_id, profile.stage):
        pending_calls: dict[str, dict[str, object]] = {}
        for event in list_events(engine, session.id):
            if event.type == "tool_call" and event.payload.get("name") in (
                profile.validate_tool,
                profile.preview_tool,
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
            if call["name"] == profile.preview_tool:
                args = call.get("args")
                scene_id = args.get("scene_id") if isinstance(args, dict) else None
                if isinstance(scene_id, str):
                    events.append(
                        _RawEvent(
                            event.created_at,
                            "preview",
                            scene_id,
                            not is_error,
                            turn_id,
                            _image_shas(event.payload.get("images")),
                        )
                    )
            elif profile.html:
                events += _html_validate_events(
                    event.created_at,
                    str(event.payload["text"]),
                    call.get("args"),
                    is_error,
                    turn_id,
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
    profile = _PROFILES[animation_stage(engine, project_id)]
    events = sorted(_collect_raw_events(engine, project_id, profile), key=lambda e: e.checked_at)

    latest_all_passed: tuple[datetime, str] | None = None
    latest_failure_all: tuple[datetime, str] | None = None
    latest_scene_passed: dict[str, tuple[datetime, str]] = {}
    latest_validate_failure: dict[str, tuple[datetime, str]] = {}
    latest_preview: dict[str, tuple[datetime, bool, str, tuple[str, ...]]] = {}
    for event in events:
        if event.kind == "validate_all_passed":
            latest_all_passed = (event.checked_at, event.turn_id)
        elif event.kind == "validate_failure_all":
            latest_failure_all = (event.checked_at, event.turn_id)
        elif event.kind == "validate_scene_passed":
            assert event.scene_id is not None
            latest_scene_passed[event.scene_id] = (event.checked_at, event.turn_id)
        elif event.kind == "validate_failure":
            assert event.scene_id is not None
            latest_validate_failure[event.scene_id] = (event.checked_at, event.turn_id)
        else:
            assert event.scene_id is not None
            latest_preview[event.scene_id] = (
                event.checked_at,
                event.passed,
                event.turn_id,
                event.images,
            )

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

    def _check_at(
        path: str,
        checked_at: datetime,
        passed: bool,
        turn_id: str,
        images: tuple[str, ...] = (),
    ) -> SceneCheck:
        end_manifest = _end_manifest(turn_id)
        stale = end_manifest is None or end_manifest.get(path) != current_manifest.get(path)
        return SceneCheck(
            status="passed" if passed else "failed",
            stale=stale,
            checked_at=checked_at,
            images=images,
        )

    def _validate_status(scene_id: str) -> SceneCheck:
        path = profile.scene_path_template.format(scene_id=scene_id)
        # (time, passed, turn): the newest verdict wins; on a tie a pass beats a failure.
        verdicts: list[tuple[datetime, bool, str]] = []
        failure = latest_validate_failure.get(scene_id)
        if failure is not None:
            verdicts.append((failure[0], False, failure[1]))
        if latest_failure_all is not None:
            verdicts.append((latest_failure_all[0], False, latest_failure_all[1]))
        if latest_all_passed is not None:
            verdicts.append((latest_all_passed[0], True, latest_all_passed[1]))
        scene_passed = latest_scene_passed.get(scene_id)
        if scene_passed is not None:
            verdicts.append((scene_passed[0], True, scene_passed[1]))
        if not verdicts:
            return _NOT_CHECKED
        checked_at, passed, turn_id = max(verdicts, key=lambda v: (v[0], v[1]))
        return _check_at(path, checked_at, passed, turn_id)

    def _preview_status(scene_id: str) -> SceneCheck:
        entry = latest_preview.get(scene_id)
        if entry is None:
            return _NOT_CHECKED
        checked_at, passed, turn_id, images = entry
        path = profile.scene_path_template.format(scene_id=scene_id)
        return _check_at(path, checked_at, passed, turn_id, images)

    return {
        scene_id: SceneChecks(
            validate_scenes=_validate_status(scene_id), render_preview=_preview_status(scene_id)
        )
        for scene_id in scene_ids
    }
