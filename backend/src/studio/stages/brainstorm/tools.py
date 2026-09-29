"""头脑风暴的三个业务工具（设计 §5.0；计划 M4 T4）：读写选题池 `ideas` 表。

都读 `ctx.engine`（没有数据库连接时按 `suggest_upstream_change` 的写法返回内部错误）。
校验、查重、状态规则都在 `db.repo.ideas`，这里只把结果和错误转成给模型看的中文文本。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from studio.agent.tools import ToolContext, ToolResult, ToolSpec
from studio.db.repo import ideas as repo

LIST_LIMIT = 50
_STAGES = {"brainstorm"}
_NO_DB = ToolResult(text="内部错误：当前上下文没有数据库连接。", is_error=True)


class ListIdeasArgs(BaseModel):
    status: Literal["idea", "picked", "archived"] | None = Field(
        default=None, description="只看某个状态的卡片；不填则列出全部（含归档，方便查重）"
    )
    query: str | None = Field(
        default=None, description="按关键词过滤：匹配标题、一句话卖点、标签（不区分大小写）"
    )


class CreateIdeaArgs(BaseModel):
    title: str = Field(min_length=1, description="选题标题，简短具体")
    pitch: str = Field(min_length=1, description="一句话卖点：这条视频讲什么、为什么值得看")
    counterintuitive: str = Field(
        min_length=1, description="反直觉点：一句话说清「大家以为 X，实际是 Y」"
    )
    tags: list[str] | None = Field(default=None, description="标签，最多 8 个")
    scores: dict[str, Any] | None = Field(
        default=None,
        description=(
            "评分，键为 counterintuitive（反直觉）、provable（可论证）、visual（可视化）、"
            "novelty（新鲜度），值为 1–5 的整数；可以只评其中几项"
        ),
    )


class UpdateIdeaArgs(BaseModel):
    id: str = Field(description="要修改的卡片 id（见 list_ideas）")
    title: str | None = None
    pitch: str | None = None
    counterintuitive: str | None = None
    tags: list[str] | None = None
    scores: dict[str, Any] | None = None


def _total(idea: repo.IdeaValue) -> str:
    if not idea.scores:
        return "未评分"
    return f"{sum(idea.scores.values())} 分（{len(idea.scores)} 项）"


def _line(idea: repo.IdeaValue) -> str:
    tags = "、".join(idea.tags) if idea.tags else "无标签"
    return f"- {idea.id} | {idea.title} | {idea.status} | {tags} | {_total(idea)}"


def _matches(idea: repo.IdeaValue, query: str) -> bool:
    needle = query.strip().casefold()
    haystacks = [idea.title, idea.pitch or "", *idea.tags]
    return any(needle in text.casefold() for text in haystacks)


def _list_ideas(ctx: ToolContext, args: ListIdeasArgs) -> ToolResult:
    if ctx.engine is None:
        return _NO_DB
    ideas = repo.list_ideas(ctx.engine, status=args.status or "all")
    if args.query and args.query.strip():
        ideas = [i for i in ideas if _matches(i, args.query)]
    if not ideas:
        return ToolResult(text="选题池里还没有符合条件的卡片。")
    shown = ideas[:LIST_LIMIT]
    header = f"共 {len(ideas)} 张卡片"
    if len(ideas) > LIST_LIMIT:
        header += f"，只显示前 {LIST_LIMIT} 张（可以用 status 或 query 缩小范围）"
    return ToolResult(text="\n".join([header, *(_line(i) for i in shown)]))


def _create_idea(ctx: ToolContext, args: CreateIdeaArgs) -> ToolResult:
    if ctx.engine is None:
        return _NO_DB
    try:
        idea = repo.create_idea(
            ctx.engine,
            title=args.title,
            pitch=args.pitch,
            counterintuitive=args.counterintuitive,
            tags=args.tags,
            scores=args.scores,
            source_session_id=ctx.session_id,
        )
    except repo.DuplicateIdeaError as exc:
        existing = exc.existing
        return ToolResult(
            text=(
                f"已有相同标题的卡片：{existing.title}"
                f"（id {existing.id}，状态 {existing.status}）。"
                "请换一个角度，或用 update_idea 改进那张卡片。"
            ),
            is_error=True,
        )
    except repo.IdeaValidationError as exc:
        return ToolResult(text=f"卡片没有创建：{exc}", is_error=True)
    return ToolResult(text=f"已创建卡片 {idea.id}：{idea.title}")


def _update_idea(ctx: ToolContext, args: UpdateIdeaArgs) -> ToolResult:
    if ctx.engine is None:
        return _NO_DB
    changes = {name: getattr(args, name) for name in args.model_fields_set - {"id"}}
    if not changes:
        return ToolResult(text="没有给出任何要修改的字段。", is_error=True)
    if changes.get("title") is None:
        changes.pop("title", None)
    idea = repo.get_idea(ctx.engine, args.id)
    if idea is None:
        return ToolResult(text=f"卡片不存在：{args.id}", is_error=True)
    if idea.status != "idea":
        return ToolResult(
            text=f"这张卡片的状态是 {idea.status}，不能再修改（只能改状态为 idea 的卡片）。",
            is_error=True,
        )
    try:
        if changes.get("scores"):
            # 评分按维度合并：agent 说「补评分」时不该把已有的其他维度冲掉。
            changes["scores"] = {**idea.scores, **repo.clean_scores(changes["scores"])}
        updated = repo.update_idea(ctx.engine, args.id, **changes)
    except repo.DuplicateIdeaError as exc:
        return ToolResult(
            text=f"已有相同标题的卡片：{exc.existing.title}（id {exc.existing.id}）。",
            is_error=True,
        )
    except (repo.IdeaValidationError, repo.IdeaStateError, repo.IdeaNotFoundError) as exc:
        return ToolResult(text=f"卡片没有修改：{exc}", is_error=True)
    return ToolResult(text=f"已修改卡片 {updated.id}：{updated.title}")


LIST_IDEAS_TOOL = ToolSpec(
    name="list_ideas",
    description="列出选题池里已有的想法卡片（id、标题、状态、标签、总分），创建新卡片前用它查重。",
    input_model=ListIdeasArgs,
    stages=_STAGES,
    handler=_list_ideas,
)

CREATE_IDEA_TOOL = ToolSpec(
    name="create_idea",
    description="在选题池里创建一张想法卡片。一次一张；标题与已有卡片重复会被拒绝。",
    input_model=CreateIdeaArgs,
    stages=_STAGES,
    handler=_create_idea,
)

UPDATE_IDEA_TOOL = ToolSpec(
    name="update_idea",
    description=(
        "修改一张还没被选用的卡片（状态为 idea）的标题、卖点、反直觉点、标签或评分；"
        "只传要改的字段，评分按维度合并。不能改状态：归档由用户在界面上做。"
    ),
    input_model=UpdateIdeaArgs,
    stages=_STAGES,
    handler=_update_idea,
)
