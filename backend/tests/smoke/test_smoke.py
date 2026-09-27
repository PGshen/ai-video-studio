"""Real-model smoke tests (plan T15, AC10; design §9 R1–R5). Run with `make smoke`.

Budget (plan "冒烟测试预授权"): all priced cases together stay under $1 per run,
enforced by each profile's `max_cost_per_turn` (TurnRunner / Claude `max_budget_usd`)
and `max_steps_per_turn`. The Claude login case uses the owner's subscription and
is only step-limited. Cases whose key is missing are skipped.

Every case drives real turns through `TurnRunner` with a temporary data dir and
writes its observations to `data/evidence/m1/smoke/` (git-ignored).
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from studio.agent.preamble import GUARD_RESTORED_NOTICE
from studio.agent.stage_flow import finalize
from studio.db.repo.sessions import get_session

from .support import (
    REPO_ROOT,
    SmokeHarness,
    TurnOutcome,
    build_harness,
    mentions_colours,
    outcome_summary,
    record_evidence,
)

pytestmark = pytest.mark.smoke

MAX_STEPS = 8
COST_LIMITS = {"claude-sonnet": 0.30, "gpt": 0.25, "deepseek": 0.05}
assert sum(COST_LIMITS.values()) <= 1.0  # plan: ≤ $1 per `make smoke` run

SMOKE_PROMPT = (
    "这是一次自动化冒烟测试，请严格按步骤执行，不要做其他事：\n"
    "1. 创建文件 topic/smoke.md，内容只有一行：smoke ok\n"
    "2. 调用 smoke_image 工具一次。\n"
    "3. 用一句话回答：工具返回的图片左半边和右半边分别是什么颜色？"
)
RECALL_PROMPT = "上一轮你说图片左右两半分别是什么颜色？只用一句话回答，不要调用任何工具。"


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[SmokeHarness]:
    h = build_harness(tmp_path)
    yield h
    h.engine.dispose()


def _require_env(name: str) -> None:
    if not os.environ.get(name):
        pytest.skip(f"未设置 {name}（backend/.env 或环境变量），跳过；结论记为未验证")


def _claude_cli() -> str | None:
    found = shutil.which("claude")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "claude"
    return str(fallback) if fallback.exists() else None


def _assert_smoke_turn(h: SmokeHarness, outcome: TurnOutcome, *, expect_vision: bool) -> bool:
    """Common AC10 checks; returns whether the reply named both colours (R2 evidence)."""
    turn = outcome.turn
    assert turn.status == "done", (turn.status, turn.error)
    smoke = h.workdir / "topic" / "smoke.md"
    assert smoke.is_file(), outcome.tool_names
    assert "smoke ok" in smoke.read_text(encoding="utf-8")
    assert "smoke_image" in outcome.tool_names
    results = outcome.tool_results("smoke_image")
    assert results and results[0]["images"] == [{"media_type": "image/png"}]
    saw_colours = mentions_colours(outcome.text)
    if expect_vision:
        assert saw_colours, outcome.text
    return saw_colours


def _transcripts(root: Path, session_id: str) -> list[str]:
    return [str(p) for p in root.glob(f"projects/*/{session_id}.jsonl")]


# ---- Claude, API key -------------------------------------------------------------


async def test_claude_api_key(harness: SmokeHarness) -> None:
    _require_env("ANTHROPIC_API_KEY")
    limit = COST_LIMITS["claude-sonnet"]
    profile = harness.profile(
        "claude-sonnet", max_cost_per_turn=limit, max_steps_per_turn=MAX_STEPS
    )
    session_id = harness.session(profile, "claude")

    first = await harness.turn(session_id, SMOKE_PROMPT)
    evidence: dict[str, Any] = {"turn1": outcome_summary(first)}
    try:
        saw = _assert_smoke_turn(harness, first, expect_vision=True)
        assert first.turn.cost_usd is not None and first.turn.cost_usd <= limit

        # R4 (API key mode): the transcript lands under <data_dir>/claude and resume works.
        session = get_session(harness.engine, session_id)
        assert session is not None and session.sdk_ref
        evidence["transcripts"] = _transcripts(harness.data_dir / "claude", session.sdk_ref)
        second = await harness.turn(session_id, RECALL_PROMPT)
        evidence["turn2"] = outcome_summary(second)
        assert second.turn.status == "done", second.turn.error
        evidence["resume_recalls_colours"] = mentions_colours(second.text)
        evidence["r2_saw_colours"] = saw
        assert evidence["transcripts"], "API key 模式的会话记录没有落在 <data_dir>/claude/projects"
    finally:
        record_evidence("claude-api-key", evidence)


# ---- Claude, local login (subscription) ----------------------------------------


async def test_claude_login(harness: SmokeHarness) -> None:
    if os.environ.get("STUDIO_SMOKE_SKIP_LOGIN") == "1":
        pytest.skip("STUDIO_SMOKE_SKIP_LOGIN=1，跳过本机登录用例")
    if _claude_cli() is None:
        pytest.skip("未找到 claude CLI（本机未安装/未登录 Claude Code），跳过本机登录用例")

    profile = harness.profile("claude-login", max_steps_per_turn=MAX_STEPS)
    session_id = harness.session(profile, "claude")
    outside_tmp = harness.data_dir.parent / "outside"
    outside_tmp.mkdir()
    outside_repo = REPO_ROOT / "data" / "evidence" / "m1" / "r3-scratch"
    outside_repo.mkdir(parents=True, exist_ok=True)
    probes = [outside_tmp / "r3-probe", outside_repo / "r3-probe"]
    for probe in probes:
        probe.unlink(missing_ok=True)
    ledger = harness.data_dir / "claude" / "studio-cost-ledger"
    evidence: dict[str, Any] = {}

    try:
        # Turn 1: AC10 minimal turn (file + image tool) with subscription auth.
        first = await harness.turn(session_id, SMOKE_PROMPT)
        evidence["turn1"] = outcome_summary(first)
        evidence["r2_saw_colours"] = _assert_smoke_turn(harness, first, expect_vision=True)
        session = get_session(harness.engine, session_id)
        assert session is not None and session.sdk_ref
        sdk_ref = session.sdk_ref
        # R4 (login mode): CLAUDE_CONFIG_DIR is left alone → default ~/.claude.
        evidence["transcripts_home"] = _transcripts(Path.home() / ".claude", sdk_ref)
        evidence["transcripts_data_dir"] = _transcripts(harness.data_dir / "claude", sdk_ref)
        evidence["ledger_after_turn1"] = sorted(p.name for p in ledger.glob("*.json"))

        # Turn 2: resume (R4) + Bash sandbox probe outside the workspace (R3) + network.
        command = (
            f"touch {probes[0]}; touch {probes[1]}; "
            "curl -sS -m 5 -o /dev/null -w 'http=%{http_code}' https://example.com; echo"
        )
        second = await harness.turn(
            session_id,
            RECALL_PROMPT.replace("不要调用任何工具。", "")
            + f"\n然后用 Bash 工具原样执行下面这一条命令一次（不要改写、不要重试），"
            f"并如实报告输出：\n{command}",
        )
        evidence["turn2"] = outcome_summary(second)
        evidence["resume_recalls_colours"] = mentions_colours(second.text)
        evidence["r3_probe_exists"] = {str(p): p.exists() for p in probes}
        evidence["r3_bash_results"] = second.tool_results("Bash")
        evidence["ledger_after_turn2"] = {
            p.name: p.read_text(encoding="utf-8") for p in ledger.glob("*.json")
        }
        assert second.turn.status == "done", second.turn.error
        assert evidence["resume_recalls_colours"], second.text

        # Turn 3: R5 — a narrative turn sees upstream/topic/ and is asked to write into it.
        finalize(harness.engine, harness.blobs, harness.registry, harness.project_id, "topic")
        narrative = harness.session(profile, "claude", stage="narrative")
        third = await harness.turn(
            narrative,
            "这是自动化测试，请按步骤执行，每步只做一次、失败不要重试：\n"
            "1. 读取 upstream/topic/smoke.md 并复述内容。\n"
            "2. 用 Edit 工具在该文件末尾追加一行 r5-edit。\n"
            "3. 用 Bash 执行：echo r5-bash >> upstream/topic/smoke.md\n"
            "4. 如实报告每一步的结果。",
        )
        upstream = harness.workdir / "upstream" / "topic" / "smoke.md"
        evidence["turn3"] = outcome_summary(third)
        evidence["r5_edit_results"] = third.tool_results("Edit") + third.tool_results("Write")
        evidence["r5_guard_notices"] = third.notices(GUARD_RESTORED_NOTICE)
        evidence["r5_upstream_after"] = upstream.read_text(encoding="utf-8")
        assert third.turn.status == "done", third.turn.error
        assert "r5" not in evidence["r5_upstream_after"]
    finally:
        record_evidence("claude-login", evidence)
        for probe in probes:
            probe.unlink(missing_ok=True)


# ---- OpenAI Responses API --------------------------------------------------------


async def test_openai_responses(harness: SmokeHarness) -> None:
    _require_env("OPENAI_API_KEY")
    limit = COST_LIMITS["gpt"]
    profile = harness.profile("gpt", max_cost_per_turn=limit, max_steps_per_turn=MAX_STEPS)
    session_id = harness.session(profile, "openai")
    outcome = await harness.turn(session_id, SMOKE_PROMPT)
    evidence: dict[str, Any] = {"turn1": outcome_summary(outcome)}
    try:
        evidence["r2_saw_colours"] = _assert_smoke_turn(harness, outcome, expect_vision=True)
        assert outcome.turn.cost_usd is not None and outcome.turn.cost_usd <= limit
    finally:
        record_evidence("openai-responses", evidence)


# ---- DeepSeek via LiteLLM --------------------------------------------------------


async def test_deepseek_litellm(harness: SmokeHarness) -> None:
    _require_env("DEEPSEEK_API_KEY")
    limit = COST_LIMITS["deepseek"]
    profile = harness.profile("deepseek", max_cost_per_turn=limit, max_steps_per_turn=MAX_STEPS)
    session_id = harness.session(profile, "openai")
    outcome = await harness.turn(session_id, SMOKE_PROMPT)
    evidence: dict[str, Any] = {"turn1": outcome_summary(outcome)}
    try:
        # R2 on the LiteLLM path is an observation, not an assertion (design §9).
        evidence["r2_saw_colours"] = _assert_smoke_turn(harness, outcome, expect_vision=False)
        assert outcome.turn.cost_usd is not None and outcome.turn.cost_usd <= limit
    finally:
        record_evidence("deepseek-litellm", evidence)
