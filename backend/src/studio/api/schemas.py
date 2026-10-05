"""api 层的请求/响应模型（任务简报 T7）。

命名对应各路由返回的资源；字段是仓储值对象（`db.repo.*Value`）的子集或直接
映射，不泄露 ORM 对象（规则 5 的延伸——api 也只经 `db.repo` 拿数据）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from studio.agent.runtime import Effort
from studio.stages.pipeline import Engine, MusicSource, VideoKind


class ProjectCreate(BaseModel):
    title: str
    settings: dict[str, Any] | None = None
    idea_id: str | None = None
    """从选题池的想法卡片创建（卡片须为 `idea` 状态，已归档的不行）。同一张卡片可以创建多个项目。"""
    style_preset_id: str | None = None
    """风格库里的预设 id；不给就用默认风格，没有默认风格时用占位 `STYLE.md`。"""
    engine: Engine | None = None
    narration: bool | None = None
    music_source: MusicSource | None = None
    """项目类型配置：三者都不给 = 老默认（Manim 讲解）；只给一部分 → 422。"""


class ProjectSettingsPatch(BaseModel):
    """`PATCH /projects/{id}/settings`：只放行 `voice`/`speech_rate`（M5 T8）和 `effort`。
    `null` 清除该键，清除后配音回落到内置默认、思考强度回落到 `DEFAULT_EFFORT`。
    语速范围和音色是否可用由端点检查，错误信息更好读。"""

    model_config = ConfigDict(extra="forbid")

    voice: str | None = None
    speech_rate: float | None = None
    effort: Effort | None = None


class StageOut(BaseModel):
    stage: str
    status: str
    finalized_snapshot_id: str | None
    based_on: dict[str, str]
    finalized_at: datetime | None


class ProjectKindConfig(BaseModel):
    engine: Engine
    narration: bool
    music_source: MusicSource


class ProjectKindOut(BaseModel):
    video_kind: VideoKind
    engine: Engine
    narration: bool
    music_source: MusicSource
    pipeline: list[str]


class ProjectOut(BaseModel):
    id: str
    title: str
    idea_id: str | None
    current_stage: str
    settings: dict[str, Any]
    completed_at: datetime | None
    """"成片定稿"（T11）或手动标记已完成后设为完成时间；`None` 表示项目尚未完成。"""
    abandoned_at: datetime | None
    """手动标记已废弃的时间；与 `completed_at` 互斥。"""
    status: Literal["active", "completed", "abandoned"]
    """由 `completed_at`/`abandoned_at` 推导的项目状态：进行中、已完成、已废弃。"""
    kind: ProjectKindOut
    """项目类型与流水线；老项目（settings 里没有类型字段）视为 Manim 讲解。"""


class ProjectStatusPatch(BaseModel):
    status: Literal["active", "completed", "abandoned"]


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


class SessionModelUpdate(BaseModel):
    """`PATCH /sessions/{id}`：把会话换成另一个模型配置（同 runtime、同 provider）。"""

    model_config = ConfigDict(extra="forbid")

    model_profile_id: str


class SessionOut(BaseModel):
    id: str
    project_id: str | None
    stage: str
    subject_id: str | None = None
    """会话属于的对象：风格对话是风格 id，其余为空。"""
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
    never_started: bool = False
    """`interrupted` 且从未真正开始运行（重启时还在排队）；[继续] 重发 `user_message`（TD-19）。"""
    created_at: datetime
    updated_at: datetime


class SessionDetailOut(SessionOut):
    turns: list[TurnOut]


class SuggestionOut(BaseModel):
    """回退建议（M5 T9）：下游阶段的 agent 对上游产物提出的修改建议。"""

    id: str
    project_id: str
    from_stage: str
    to_stage: str
    content: str
    status: str
    """`open`（待处理）/`applied`（已处理）/`dismissed`（已忽略）。"""
    turn_id: str | None
    created_at: datetime


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
    """永远不含 key 的**值**，只有 `key_configured`。M5 T6 起返回 `api_key_env`（环境变量的
    名字，不是密钥，界面要编辑它）和 `base_url`（账号密码打码）。"""

    id: str
    name: str
    provider: str
    model: str
    runtime: str
    base_url: str | None
    api_key_env: str | None
    """环境变量名；为空表示使用本机登录（仅 claude 运行时）。"""
    supports_vision: bool
    price_input: float | None
    price_output: float | None
    max_cost_per_turn: float | None
    max_steps_per_turn: int | None
    key_configured: bool
    builtin: bool
    """内置配置（种子名和 `fake`）：可以编辑，不能删除。"""
    env_override: list[str]
    """当前由环境变量（`STUDIO_*`）决定的字段；启动时会覆盖库里的值，所以界面不让改。"""


class ModelProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    provider: str
    model: str
    runtime: str
    base_url: str | None = None
    api_key_env: str | None = None
    supports_vision: bool = False
    price_input: float | None = None
    price_output: float | None = None
    max_cost_per_turn: float | None = None
    max_steps_per_turn: int | None = None


class ModelProfilePatch(BaseModel):
    """只改出现的字段（`null` 清空可空字段）；`name`/`provider`/`runtime` 建好后不可改。"""

    model_config = ConfigDict(extra="forbid")

    model: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    supports_vision: bool | None = None
    price_input: float | None = None
    price_output: float | None = None
    max_cost_per_turn: float | None = None
    max_steps_per_turn: int | None = None


class SceneCheckOut(BaseModel):
    """`scene_checks.py::SceneCheck` 的线上表示（TD-33，读时聚合，不对应任何表）。"""

    status: str
    """`"passed"`/`"failed"`/`"not_checked"`。"""
    stale: bool
    """检查之后镜头代码又改过，需要重新检查。"""
    checked_at: datetime | None
    images: list[str] = []
    """该次检查结果里的图片 blob sha256（`render_preview` 关键帧），用 `/blobs/{sha256}` 取图。"""


class SceneChecksOut(BaseModel):
    validate_scenes: SceneCheckOut
    render_preview: SceneCheckOut


class SceneChecksResponse(BaseModel):
    scenes: dict[str, SceneChecksOut]


class TopicCheckOut(BaseModel):
    ok: bool
    errors: list[str]
    warnings: list[str]


class IdeaOut(BaseModel):
    id: str
    title: str
    pitch: str | None
    counterintuitive: str | None
    tags: list[str]
    scores: dict[str, int]
    status: str
    source_session_id: str | None
    created_at: datetime
    updated_at: datetime


class IdeaCreate(BaseModel):
    title: str
    pitch: str | None = None
    counterintuitive: str | None = None
    tags: list[str] | None = None
    scores: dict[str, Any] | None = None


class IdeaUpdate(BaseModel):
    """PATCH：只处理请求里出现过的字段（`model_fields_set`），显式 `null` 表示清空文本。"""

    title: str | None = None
    pitch: str | None = None
    counterintuitive: str | None = None
    tags: list[str] | None = None
    scores: dict[str, Any] | None = None
    status: str | None = None


class TtsDefaultOut(BaseModel):
    voice: str
    speech_rate: float


class SettingsOut(BaseModel):
    stage_default_profile: dict[str, str]
    """`{阶段: 模型配置 id}`，新建会话时预选；没设置的阶段不出现。"""
    web_mode: Literal["tools", "native"]
    """有效的联网模式：界面覆盖优先，否则是环境变量 `STUDIO_WEB_MODE`。"""
    web_mode_source: Literal["ui", "env"]
    web_mode_env: Literal["tools", "native"]
    """环境变量给出的默认值，界面「清除覆盖」后回落到它。"""
    tts_default: TtsDefaultOut
    """新项目的默认音色/语速；没设置时是内置默认值。"""
    default_style_preset_id: str | None


class SettingsPatch(BaseModel):
    """补丁语义：只改出现的字段（`model_fields_set`）；值为 `null` 表示清除。"""

    model_config = ConfigDict(extra="forbid")

    stage_default_profile: dict[str, str | None] | None = None
    web_mode: Literal["tools", "native"] | None = None
    tts_default: dict[str, Any] | None = None
    default_style_preset_id: str | None = None


class StyleSummaryOut(BaseModel):
    id: str
    name: str
    category: str
    description: str | None
    reference_count: int
    exemplar_count: int
    is_default: bool
    has_draft: bool
    """有未保存的草稿。"""
    is_new: bool
    """从未保存过（只有草稿）：点开直接进编辑，没有正式版本可看。"""
    modified_at: datetime


class StyleOut(BaseModel):
    """正式版本：`files` 是 `{相对路径: 文本}`（`STYLE.md`、`references/*`、`exemplars/*`）。"""

    id: str
    name: str
    category: str
    description: str | None
    files: dict[str, str]
    is_default: bool
    modified_at: datetime


class DraftStatusOut(BaseModel):
    id: str
    is_new: bool
    """从未保存过（正式版本不存在）。"""
    dirty: bool
    files: list[str]
    busy: bool = False
    """这套风格有对话轮次在排队或运行（AI 正在改草稿）：改动类操作会被拒绝，前端据此只读。"""


class DraftFileOut(BaseModel):
    content: str


class DraftFileWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str


class PresetOut(BaseModel):
    video_kind: VideoKind
    label: str
    description: str
    music_choices: list[MusicSource]
    default: ProjectKindConfig


class KindOptionOut(BaseModel):
    engine: Engine
    narration: bool
    music_source: MusicSource
    video_kind: VideoKind
    pipeline: list[str]
    available: bool
    unavailable_reason: str | None


class VideoKindsOut(BaseModel):
    presets: list[PresetOut]
    kinds: list[KindOptionOut]


class HtmlPreviewBeat(BaseModel):
    start: float
    end: float
    cue_text: str


class HtmlPreviewSection(BaseModel):
    id: str
    label: str
    start: float
    end: float
    beats: list[HtmlPreviewBeat]


class HtmlPreviewAudio(BaseModel):
    section_id: str
    url: str
    """叙事配音文件的下载地址（工作区文件端点），带 `audio_hash` 作缓存标识。"""


class HtmlPreviewMusic(BaseModel):
    url: str
    """`/music/audio` 的地址，带 `wav_hash` 作版本：重新渲染后换地址，预览不会放旧音。"""
    gain: float
    """线性增益：短片 1.0，讲解背景乐比成片里压低的那一档（预览不做侧链）。"""


class HtmlPreviewMeta(BaseModel):
    """`GET .../animation/html-preview/meta`：实时预览画布需要的全部时间与配音信息。"""

    hash: str
    """覆盖镜头、`lib`、`global`、`assets` 与时间轴；变了才需要刷新 iframe。"""
    duration: float
    sections: list[HtmlPreviewSection]
    audio: list[HtmlPreviewAudio]
    music: HtmlPreviewMusic | None = None
    """配乐已渲染且对得上当前时间轴才有；否则为 `None`，画面照常。"""


class MusicEventOut(BaseModel):
    name: str
    kind: str
    start: float
    end: float


class MusicSectionOut(BaseModel):
    id: str
    label: str
    start: float
    end: float


class MusicMetaOut(BaseModel):
    """`GET .../music/meta`：配乐画布和预览需要的全部信息；没有产物时 `rendered=false`。"""

    rendered: bool
    stale: bool
    """产物是对着另一版时间轴渲染的（节拍脚本或旁白变了），成片会拒绝它。"""
    hash: str | None = None
    """`music.wav` 的哈希；音频地址的版本号。"""
    duration: float | None = None
    bpm: float | None = None
    events: list[MusicEventOut] = []
    sections: list[MusicSectionOut] = []
    waveform: list[float] = []
    metrics: dict[str, Any] | None = None


class MusicRenderOut(BaseModel):
    """`POST .../music/render`：和 `render_music` 工具同形的报告。

    脚本的问题是 `ok=false`，不是 HTTP 错误。
    """

    ok: bool
    errors: list[str] = []
    text: str
    warnings: list[str] = []
    retime_note: str = ""
    metrics: dict[str, Any] | None = None
    picture_base64: str | None = None
    picture_media_type: str | None = None
