"""Real-model smoke for chat attachments (plan chat-attachments T7, AC1).

One project turn on the local Claude login: a two-colour PNG goes in as a multimodal image and a
`.md` file lands in `uploads/`; the model must name the colours and quote the code word from the
file (it can only know either by seeing the image / reading the file).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from studio.api.attachments import IncomingFile, prepare_input
from studio.db.repo.profiles import get_model_profile_by_id

from .support import (
    REPO_ROOT,
    SMOKE_COLOURS,
    TURN_TIMEOUT_SECONDS,
    build_harness,
    make_two_colour_png,
    mentions_colours,
    outcome_summary,
    record_evidence,
)
from .test_smoke import _skip_unless_claude_login

pytestmark = pytest.mark.smoke

EVIDENCE_DIR = REPO_ROOT / "data" / "evidence" / "chat-attachments" / "smoke"
CODE_WORD = "青柠-4271"


async def test_attachments_claude_login(tmp_path: Path) -> None:
    _skip_unless_claude_login()
    harness = build_harness(tmp_path, real_stages=True)
    try:
        profile_id = harness.profile("claude-login", max_steps_per_turn=8)
        profile = get_model_profile_by_id(harness.engine, profile_id)
        assert profile is not None and profile.supports_vision
        session_id = harness.session(profile_id, "claude")
        png = make_two_colour_png(64, 32, SMOKE_COLOURS["blue"], SMOKE_COLOURS["yellow"])
        note = (
            "# 选题资料\n\n方向：数据库索引为什么会让写入变慢。\n\n"
            f"项目代号：{CODE_WORD}（之后的文件都用这个代号命名）\n"
        ).encode()
        text = (
            "我上传了一张参考图和一份选题资料。先说说参考图左右两半分别是什么颜色"
            "（我想用它做配色），再读一下资料，告诉我资料里写的项目代号，然后我们再开始打磨选题。"
        )
        prepared = prepare_input(
            text,
            [IncomingFile("colours.png", png), IncomingFile("资料.md", note)],
            workdir=harness.workdir,
            blobs=harness.blobs,
            runtime="claude",
            supports_vision=True,
        )
        turn_id = await harness.runner.start_turn(
            session_id,
            prepared.user_input,
            user_message=text,
            attachments=[r.to_dict() for r in prepared.records],
        )
        await asyncio.wait_for(harness.runner.wait(turn_id), timeout=TURN_TIMEOUT_SECONDS)
        outcome = harness._outcome(session_id, turn_id)
        evidence = {
            **outcome_summary(outcome),
            "records": [r.to_dict() for r in prepared.records],
            "user_message": outcome.turn.user_message,
        }
        record_evidence("attachments-claude-login", evidence, EVIDENCE_DIR)

        assert outcome.turn.status == "done", (outcome.turn.status, outcome.turn.error)
        assert outcome.turn.user_message == text
        assert len(outcome.turn.attachments) == 2
        assert mentions_colours(outcome.text), outcome.text
        assert CODE_WORD in outcome.text, outcome.text
        uploaded = [r.path for r in prepared.records if r.path]
        assert uploaded and (harness.workdir / uploaded[0]).read_bytes() == note
    finally:
        harness.engine.dispose()
