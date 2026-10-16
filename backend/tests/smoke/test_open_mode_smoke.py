"""Real-model smoke for open mode (open-mode plan T10). Run with `make smoke SMOKE_ARGS="-k open"`.

The workspace starts with only `style/` and `project.md`, there is no stage prompt (Claude Code's
own system prompt), and Bash may use the network. Claude (local login) must make a short HTML
animation and export it to mp4 by itself; Codex (local ChatGPT login) only checks that its sandboxed
commands reach the network.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from studio.stages.pipeline import OPEN_KIND

from .support import REPO_ROOT, build_harness, outcome_summary, record_evidence
from .test_smoke import _skip_unless_claude_login, _skip_unless_codex

pytestmark = pytest.mark.smoke

OPEN_EVIDENCE_DIR = REPO_ROOT / "data" / "evidence" / "open-mode" / "smoke"
_THEME = "「光的折射」：一束光从空气斜射进水里时为什么会拐弯。"
_CLAUDE_GO = (
    "先运行 `npm view left-pad version`，把输出告诉我。然后按 style/STYLE.md 的风格、"
    "围绕 project.md 里的主题，做一个 8 秒左右的标题动画：用 HTML + JS 写在 title/index.html，"
    "再用你觉得合适的办法（例如本机的 ffmpeg 和 headless Chromium）把它导出成 title/out.mp4"
    "（1280x720）。不用先问我，直接做完，最后告诉我做了什么。"
)
_CODEX_GO = (
    "运行 `curl -sS -o /dev/null -w '%{http_code}' https://example.com`，只回复它输出的状态码。"
)
_VERSION_RE = re.compile(r"\b\d+\.\d+\.\d+\b")


def _bash_outputs(turns: list[Any]) -> list[str]:
    calls = {
        e.payload["call_id"]: e.payload
        for t in turns
        for e in t.events
        if e.type == "tool_call" and e.payload["name"] == "Bash"
    }
    return [
        str(e.payload["text"])
        for t in turns
        for e in t.events
        if e.type == "tool_result"
        and e.payload["call_id"] in calls
        and "npm view" in json.dumps(calls[e.payload["call_id"]].get("args"), ensure_ascii=False)
    ]


def _probe_mp4(path: Path) -> float:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(json.loads(probe.stdout)["format"]["duration"])


async def test_open_mode_claude_login(tmp_path: Path) -> None:
    _skip_unless_claude_login()
    harness = build_harness(tmp_path, real_stages=True, free=OPEN_KIND, open_theme=_THEME)
    evidence: dict[str, Any] = {}
    try:
        profile = harness.profile("claude-login", max_steps_per_turn=200, suffix="-open")
        session = harness.session(profile, "claude", stage="open")
        turns = [await harness.turn(session, _CLAUDE_GO)]
        mp4s = [p for p in harness.workdir.rglob("*.mp4") if "node_modules" not in p.parts]
        if not mp4s:
            turns.append(await harness.turn(session, "还没有导出 title/out.mp4，请继续完成。"))
            mp4s = [p for p in harness.workdir.rglob("*.mp4") if "node_modules" not in p.parts]
        evidence["turns"] = [outcome_summary(t) for t in turns]
        evidence["tool_calls"] = [name for t in turns for name in t.tool_names]
        evidence["files"] = sorted(
            str(p.relative_to(harness.workdir))
            for p in harness.workdir.rglob("*")
            if p.is_file() and "node_modules" not in p.parts
        )
        assert all(t.turn.status == "done" for t in turns), [
            (t.turn.status, t.turn.error) for t in turns
        ]

        npm = _bash_outputs(turns)
        evidence["npm_view"] = npm
        assert any(_VERSION_RE.search(text) for text in npm), "Bash 里的 npm view 没有联网成功"

        assert mp4s, "没有导出 mp4"
        duration = _probe_mp4(mp4s[0])
        evidence["mp4"] = {"path": str(mp4s[0].relative_to(harness.workdir)), "duration": duration}
        assert duration > 0
        OPEN_EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(mp4s[0], OPEN_EVIDENCE_DIR / "open-claude.mp4")
    finally:
        record_evidence("open-mode-claude-login", evidence, OPEN_EVIDENCE_DIR)
        harness.engine.dispose()


async def test_open_mode_codex_login(tmp_path: Path) -> None:
    _skip_unless_codex()
    harness = build_harness(tmp_path, real_stages=True, free=OPEN_KIND, open_theme=_THEME)
    evidence: dict[str, Any] = {}
    try:
        profile = harness.profile("codex-login", max_steps_per_turn=40, suffix="-open")
        session = harness.session(profile, "codex", stage="open")
        outcome = await harness.turn(session, _CODEX_GO)
        evidence["turn"] = outcome_summary(outcome)
        evidence["text"] = outcome.text
        assert outcome.turn.status == "done", outcome.turn.error
        assert "200" in outcome.text, outcome.text
    finally:
        record_evidence("open-mode-codex-login", evidence, OPEN_EVIDENCE_DIR)
        harness.engine.dispose()
