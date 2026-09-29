"""api 层的请求/响应模型（任务简报 T7）。

命名对应各路由返回的资源；字段是仓储值对象（`db.repo.*Value`）的子集或直接
映射，不泄露 ORM 对象（规则 5 的延伸——api 也只经 `db.repo` 拿数据）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ProjectCreate(BaseModel):
    title: str
    settings: dict[str, Any] | None = None


class StageOut(BaseModel):
    stage: str
    status: str
    finalized_snapshot_id: str | None
    based_on_snapshot_id: str | None
    finalized_at: datetime | None


class ProjectOut(BaseModel):
    id: str
    title: str
    idea_id: str | None
    current_stage: str
    settings: dict[str, Any]
    completed_at: datetime | None
    """"成片定稿"（T11）后设为完成时间；`None` 表示项目尚未完成。"""


class ProjectDetailOut(ProjectOut):
    stages: list[StageOut]
    busy: bool
    """项目当前是否有一轮在跑（`TurnRunner.is_project_busy`）——后端按项目
    串行，同一时间至多一个 turn 在写工作区，所以这一个字段就足够代表"任何
    会话的 turn 是否在跑"，前端画布/快照时间线用它决定是否只读（T14 控制
    者裁定）。"""


class FileEntry(BaseModel):
    path: str
    readonly: bool
    """`upstream/` 下的文件为 `True`：只读的上游产物副本，PUT 会被拒绝（403）。"""


class FileTreeOut(BaseModel):
    files: list[FileEntry]


class FileWriteRequest(BaseModel):
    content: str
    """UTF-8 文本内容；M1 的手动编辑只支持文本文件（见 `api.files` 模块文档）。"""


class FileWriteResult(BaseModel):
    path: str


class SnapshotOut(BaseModel):
    id: str
    reason: str
    turn_id: str | None
    created_at: datetime


class ModifiedFileOut(BaseModel):
    path: str
    text_diff: str | None
    """二进制文件（任一侧不是合法 UTF-8 文本）为 `None`，不生成文本 diff。"""


class SnapshotDiffOut(BaseModel):
    added: list[str]
    removed: list[str]
    modified: list[ModifiedFileOut]


class SessionCreate(BaseModel):
    model_profile_id: str


class SessionOut(BaseModel):
    id: str
    project_id: str | None
    stage: str
    model_profile_id: str
    runtime: str
    sdk_ref: str | None
    status: str
    is_active: bool
    title: str | None


class TurnOut(BaseModel):
    id: str
    session_id: str
    user_message: str
    status: str
    start_snapshot_id: str | None
    end_snapshot_id: str | None
    usage: dict[str, Any] | None
    cost_usd: float | None
    error: str | None
    created_at: datetime
    updated_at: datetime


class SessionDetailOut(SessionOut):
    turns: list[TurnOut]


class MessageCreate(BaseModel):
    text: str


class TurnAccepted(BaseModel):
    """`POST .../messages`、`.../cancel`、`.../continue` 的响应：正在处理的 turn id。"""

    turn_id: str


class JobOut(BaseModel):
    """`jobs` 表一行（`studio.jobs.JobValue` 的子集）：不包含 `payload`/
    `heartbeat_at`——这两个字段是 worker 内部使用的实现细节（分别是"worker
    怎么定位输入"和"worker 有没有卡死"），前端只需要状态、进度、错误和
    结果（`result["output_path"]`，成片下载端点走另一个固定路径，不需要
    前端自己拼）。
    """

    id: str
    type: str
    project_id: str
    status: str
    progress: float
    error: str | None
    result: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class ModelProfileOut(BaseModel):
    """不包含 `api_key_env`（字段名本身不是密钥，但简报要求"不返回 key，
    只返回 key 是否已配置"）：调用方只需要知道能不能用，不需要知道去哪个
    环境变量找 key。
    """

    id: str
    name: str
    provider: str
    model: str
    runtime: str
    supports_vision: bool
    price_input: float | None
    price_output: float | None
    max_cost_per_turn: float | None
    max_steps_per_turn: int | None
    key_configured: bool


class SceneCheckOut(BaseModel):
    """`scene_checks.py::SceneCheck` 的线上表示（TD-33，读时聚合，不对应任何表）。"""

    status: str
    """`"passed"`/`"failed"`/`"not_checked"`。"""
    stale: bool
    """检查之后镜头代码又改过，需要重新检查。"""
    checked_at: datetime | None


class SceneChecksOut(BaseModel):
    validate_scenes: SceneCheckOut
    render_preview: SceneCheckOut


class SceneChecksResponse(BaseModel):
    scenes: dict[str, SceneChecksOut]
