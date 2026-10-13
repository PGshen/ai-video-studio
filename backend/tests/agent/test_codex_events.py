"""`codex_events`：`codex exec --json` 事件 → `AgentEvent`（codex-runtime T3）。

回放 `fixtures/codex/` 里裁剪自实测的 JSONL，不调真实模型。
"""

from __future__ import annotations

import json
from pathlib import Path

from studio.agent import events
from studio.agent.codex_events import CodexTurn, convert_event, failure_message, redact

FIXTURES = Path(__file__).parent / "fixtures" / "codex"
WORKDIR = Path("/work/ws")


def _replay(name: str) -> tuple[CodexTurn, list[events.AgentEvent]]:
    turn = CodexTurn(workdir=WORKDIR, call_prefix="t1")
    out: list[events.AgentEvent] = []
    for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines():
        out += convert_event(json.loads(line), turn)
    return turn, out


def test_minimal_turn() -> None:
    turn, out = _replay("minimal.jsonl")
    assert turn.thread_id == "01a134a0-b200-7542-a12d-f03cda26a8f7"
    assert out == [events.TextBlock("ok")]
    assert turn.usage == {
        "input_tokens": 9809,
        "cached_input_tokens": 0,
        "cache_write_input_tokens": 0,
        "output_tokens": 5,
        "reasoning_output_tokens": 0,
    }
    assert turn.failure is None


def test_mcp_tool_call_with_image() -> None:
    _, out = _replay("mcp_image.jsonl")
    calls = [e for e in out if isinstance(e, events.ToolCall)]
    results = [e for e in out if isinstance(e, events.ToolResult)]
    assert [(c.name, c.args) for c in calls] == [
        ("render_swatch", {}),
        ("lookup_note", {"key": "intro"}),
    ]
    assert [c.call_id for c in calls] == [r.call_id for r in results] == ["t1-item_1", "t1-item_3"]
    assert results[0].images and results[0].images[0].media_type == "image/png"
    assert not results[0].is_error
    assert "MAGENTA-OTTER" in results[1].text
    # Calls come out when the item starts, results when it completes.
    assert out.index(calls[0]) < out.index(results[0]) < out.index(calls[1])


def test_command_execution_maps_to_shell() -> None:
    _, out = _replay("command.jsonl")
    call = next(e for e in out if isinstance(e, events.ToolCall))
    result = next(e for e in out if isinstance(e, events.ToolResult))
    assert call.name == "shell"  # in FILE_TOOL_NAMES: the runner refreshes the workspace
    assert call.args == {"command": "/bin/zsh -lc 'sh probe.sh .'"}
    assert result.call_id == call.call_id
    assert "write workspace: OK" in result.text
    assert not result.is_error


def test_command_failure_is_an_error_result() -> None:
    turn = CodexTurn(workdir=WORKDIR, call_prefix="t1")
    item = {
        "id": "item_5",
        "type": "command_execution",
        "command": "false",
        "aggregated_output": "",
        "exit_code": 1,
        "status": "failed",
    }
    out = convert_event({"type": "item.completed", "item": item}, turn)
    # No item.started was seen: the call is emitted before its result.
    assert isinstance(out[0], events.ToolCall)
    assert isinstance(out[1], events.ToolResult) and out[1].is_error
    assert "退出码 1" in out[1].text


def test_file_change_maps_to_apply_patch_with_relative_path() -> None:
    _, out = _replay("file_change.jsonl")
    call = next(e for e in out if isinstance(e, events.ToolCall))
    assert call.name == "apply_patch"
    assert call.args["path"] == "inside.txt"
    assert call.args["changes"] == [{"path": "inside.txt", "kind": "add"}]
    # Exactly one ToolCall per item even though both started and completed carry it.
    assert sum(isinstance(e, events.ToolCall) for e in out) == 1


def test_file_change_with_several_files_has_no_single_path() -> None:
    turn = CodexTurn(workdir=WORKDIR, call_prefix="t1")
    item = {
        "id": "item_9",
        "type": "file_change",
        "changes": [
            {"path": "/work/ws/a.md", "kind": "update"},
            {"path": "/elsewhere/b.md", "kind": "add"},
        ],
        "status": "completed",
    }
    out = convert_event({"type": "item.completed", "item": item}, turn)
    call = out[0]
    assert isinstance(call, events.ToolCall)
    assert "path" not in call.args  # unknown paths → the runner refreshes everything
    assert call.args["changes"] == [
        {"path": "a.md", "kind": "update"},
        {"path": "/elsewhere/b.md", "kind": "add"},
    ]


def test_cancelled_turn_has_no_usage_or_failure() -> None:
    turn, out = _replay("cancelled.jsonl")
    assert turn.usage is None and turn.failure is None
    assert isinstance(out[-1], events.ToolCall)


def test_config_warning_before_turn_start_becomes_a_notice() -> None:
    turn, out = _replay("model_not_found.jsonl")
    notices = [e for e in out if isinstance(e, events.Notice)]
    assert len(notices) == 1 and notices[0].kind == "runtime_warning"
    assert "gpt-no-such-model" in notices[0].message
    assert turn.failure is not None
    assert failure_message(turn.failure) == (
        "The 'gpt-no-such-model' model is not supported when using Codex with a ChatGPT account."
    )


def test_reconnect_errors_do_not_fail_the_turn() -> None:
    turn, out = _replay("reconnect_then_done.jsonl")
    assert turn.failure is None and turn.usage is not None
    # Transport warnings after turn.started are logged, not shown.
    assert not any(isinstance(e, events.Notice) for e in out)
    assert out[-1] == events.TextBlock("DONE")


def test_not_logged_in_failure_is_explained() -> None:
    turn, _ = _replay("not_logged_in.jsonl")
    assert turn.failure is not None
    message = failure_message(turn.failure)
    assert "codex login" in message
    assert "401" in message


def test_reasoning_maps_to_thinking() -> None:
    turn = CodexTurn(workdir=WORKDIR, call_prefix="t1")
    item = {"id": "item_0", "type": "reasoning", "text": "**Planning** the edit"}
    assert convert_event({"type": "item.completed", "item": item}, turn) == [
        events.ThinkingBlock("**Planning** the edit")
    ]


def test_unknown_item_types_warn_once() -> None:
    turn = CodexTurn(workdir=WORKDIR, call_prefix="t1")
    item = {"id": "item_0", "type": "collab_tool_call", "tool": "spawn_agent"}
    first = convert_event({"type": "item.started", "item": item}, turn)
    second = convert_event({"type": "item.completed", "item": {**item, "id": "item_1"}}, turn)
    assert len(first) == 1 and isinstance(first[0], events.Notice)
    assert first[0].kind == "runtime_warning" and "collab_tool_call" in first[0].message
    assert second == []


def test_todo_list_items_are_ignored() -> None:
    turn = CodexTurn(workdir=WORKDIR, call_prefix="t1")
    item = {"id": "item_0", "type": "todo_list", "items": []}
    assert convert_event({"type": "item.completed", "item": item}, turn) == []


def test_failure_message_unwraps_json_errors() -> None:
    raw = json.dumps(
        {"type": "error", "status": 400, "error": {"message": "Invalid value: 'extreme'."}}
    )
    assert failure_message(raw) == "Invalid value: 'extreme'."


def test_failure_message_clips_long_text() -> None:
    assert len(failure_message("x" * 5000)) <= 600


def test_redact_hides_token_like_strings() -> None:
    jwt = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlLXZhbHVlLWhlcmU"
    text = f"auth failed for {jwt} with sk-proj-abcdefghijklmnopqrstuvwxyz and ok words"
    redacted = redact(text)
    assert jwt not in redacted and "sk-proj-abcdefghijklmnopqrstuvwxyz" not in redacted
    assert "auth failed for" in redacted and "ok words" in redacted


def test_model_switch_warning_is_not_shown() -> None:
    """Resuming with another model (ADR 0012 switch) always makes codex warn; the runner already
    shows its own "model switched" notice, so this one is only logged."""
    turn = CodexTurn(workdir=WORKDIR, call_prefix="t1")
    item = {
        "id": "item_0",
        "type": "error",
        "message": "This session was recorded with model `gpt-6.1-sol` but is resuming with "
        "`gpt-6-luna`. Consider switching back to `gpt-6.1-sol` as it may affect Codex "
        "performance.",
    }
    assert convert_event({"type": "item.completed", "item": item}, turn) == []
