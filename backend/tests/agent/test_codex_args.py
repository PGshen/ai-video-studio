"""`codex_args.build_args`：`codex exec --json` 的命令行（codex-runtime T3）。"""

from __future__ import annotations

import tomllib
from pathlib import Path

from studio.agent.codex_args import LOCKDOWN_ARGS, NO_SUBAGENTS_NOTE, build_args

WORKDIR = Path("/work/space")


def _overrides(args: list[str]) -> dict[str, object]:
    """Every `-c key=value`, parsed the way codex does (TOML value)."""
    out: dict[str, object] = {}
    for flag, item in zip(args, args[1:], strict=False):
        if flag == "-c":
            key, _, raw = item.partition("=")
            out[key] = tomllib.loads(f"v = {raw}")["v"]
    return out


def test_new_session() -> None:
    args = build_args(
        workdir=WORKDIR,
        model="gpt-6.1-sol",
        resume_ref=None,
        system_prompt='你是叙事助手。\n说 "引号" 也没问题',
        effort=None,
        image_paths=[],
        extra=["-c", 'x.y="z"'],
    )
    assert args[:2] == ["exec", "--json"]
    for flag in ("--skip-git-repo-check", "--ignore-user-config", "--ignore-rules"):
        assert flag in args
    assert args[args.index("-C") + 1] == str(WORKDIR)
    assert args[args.index("-m") + 1] == "gpt-6.1-sol"
    overrides = _overrides(args)
    instructions = overrides["developer_instructions"]
    assert isinstance(instructions, str)
    assert instructions.startswith('你是叙事助手。\n说 "引号" 也没问题')
    assert instructions.endswith(NO_SUBAGENTS_NOTE)
    assert overrides["x.y"] == "z"
    assert "model_reasoning_effort" not in overrides
    assert "resume" not in args
    # The prompt always comes from stdin: no argv length limit, and no variadic `-i` to swallow it.
    assert args[-1] == "-"


def test_runtime_default_prompt_sends_only_the_runtime_note() -> None:
    """open-mode 设计 §5.1：`None` → 不传阶段指令；关不掉的协作工具仍要在提示里禁止。"""
    args = build_args(
        workdir=WORKDIR,
        model="gpt-6.1-sol",
        resume_ref=None,
        system_prompt=None,
        effort=None,
        image_paths=[],
        extra=[],
    )
    assert _overrides(args)["developer_instructions"] == NO_SUBAGENTS_NOTE.strip()


def test_lockdown_args_are_always_present() -> None:
    args = build_args(
        workdir=WORKDIR,
        model="m",
        resume_ref=None,
        system_prompt="s",
        effort=None,
        image_paths=[],
        extra=[],
    )
    start = args.index(LOCKDOWN_ARGS[0])
    assert args[start : start + len(LOCKDOWN_ARGS)] == list(LOCKDOWN_ARGS)
    overrides = _overrides(list(LOCKDOWN_ARGS))
    assert overrides["project_doc_max_bytes"] == 0
    assert overrides["skills.include_instructions"] is False
    assert overrides["web_search"] == "disabled"
    assert overrides["tools.update_plan.enabled"] is False
    assert "multi_agent" in LOCKDOWN_ARGS


def test_resume_puts_exec_options_before_the_subcommand() -> None:
    args = build_args(
        workdir=WORKDIR,
        model="gpt-6-luna",
        resume_ref="01a1-thread",
        system_prompt="ignored on resume",
        effort="high",
        image_paths=[Path("/tmp/a.png"), Path("/tmp/b.jpg")],
        extra=["-c", 'mcp_servers.studio.url="http://127.0.0.1:1/mcp"'],
    )
    at = args.index("resume")
    assert args[at + 1] == "01a1-thread"
    before = args[:at]
    assert "-C" in before and "-m" in before and "--json" in before
    assert _overrides(before)["model_reasoning_effort"] == "high"
    assert "mcp_servers.studio.url" in _overrides(before)
    # developer_instructions only apply when a session is created (codex.md).
    assert "developer_instructions" not in _overrides(args)
    assert args[at + 2 :] == ["--image=/tmp/a.png", "--image=/tmp/b.jpg", "-"]


def test_new_session_images_use_single_value_form() -> None:
    args = build_args(
        workdir=WORKDIR,
        model="m",
        resume_ref=None,
        system_prompt="s",
        effort="low",
        image_paths=[Path("/tmp/a.png")],
        extra=[],
    )
    assert args[-2:] == ["--image=/tmp/a.png", "-"]
    assert _overrides(args)["model_reasoning_effort"] == "low"


def test_toml_escaping_round_trips_control_characters() -> None:
    prompt = 'tab\there\\back "q" \u0007 末尾'
    args = build_args(
        workdir=WORKDIR,
        model="m",
        resume_ref=None,
        system_prompt=prompt,
        effort=None,
        image_paths=[],
        extra=[],
    )
    instructions = _overrides(args)["developer_instructions"]
    assert isinstance(instructions, str) and instructions.startswith(prompt)
