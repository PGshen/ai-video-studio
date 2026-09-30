"""Helpers for the real-model smoke tests (plan T15).

Everything here is offline: a stdlib-only PNG writer, the `smoke_image` business
tool, a stage wrapper that exposes it, and a harness that drives real turns
through `TurnRunner` against a temporary data dir.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import struct
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import Engine

from studio.agent.bus import SessionBus
from studio.agent.claude_runtime import register_claude
from studio.agent.events import ImageData
from studio.agent.openai_runtime import register_openai
from studio.agent.runner import TurnRunner
from studio.agent.runtime import RuntimeFactory, UserInput
from studio.agent.stage import StageDefinition, StageRegistry
from studio.agent.tools import ToolContext, ToolResult, ToolSpec
from studio.config import Settings
from studio.db.engine import make_engine, migrate, session_scope
from studio.db.models import ModelProfile
from studio.db.repo.profiles import get_model_profile, seed_model_profiles
from studio.db.repo.projects import create_project
from studio.db.repo.sessions import create_session
from studio.db.repo.stages import create_stage
from studio.db.repo.turns import TurnEventValue, TurnValue, get_turn, list_events
from studio.stages.animation import STAGE as ANIMATION
from studio.stages.brainstorm import STAGE as BRAINSTORM
from studio.stages.narrative import STAGE as NARRATIVE
from studio.stages.topic import STAGE as TOPIC
from studio.workspace import BlobStore, create_snapshot, project_dir
from studio.workspace.scope import WriteScope

REPO_ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_DIR = REPO_ROOT / "data" / "evidence" / "m1" / "smoke"
M1X_EVIDENCE_DIR = REPO_ROOT / "data" / "evidence" / "m1x" / "smoke"
M3_EVIDENCE_DIR = REPO_ROOT / "data" / "evidence" / "m3-narrative" / "smoke"
M4_EVIDENCE_DIR = REPO_ROOT / "data" / "evidence" / "m4-topic" / "smoke"
M5_EVIDENCE_DIR = REPO_ROOT / "data" / "evidence" / "m5-polish" / "smoke"

SMOKE_COLOURS: dict[str, tuple[int, int, int]] = {"blue": (0, 0, 255), "yellow": (255, 255, 0)}
_COLOUR_WORDS = {"blue": ("blue", "蓝"), "yellow": ("yellow", "黄")}

TURN_TIMEOUT_SECONDS = 600


# ---- PNG ---------------------------------------------------------------------


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def make_two_colour_png(
    width: int, height: int, left: tuple[int, int, int], right: tuple[int, int, int]
) -> bytes:
    """8-bit RGB PNG whose left half is `left` and right half is `right`."""
    half = width // 2
    row = b"\x00" + bytes(left) * half + bytes(right) * (width - half)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(row * height))
        + _chunk(b"IEND", b"")
    )


def mentions_colours(text: str) -> bool:
    lowered = text.lower()
    return all(any(word in lowered for word in words) for words in _COLOUR_WORDS.values())


# ---- business tool and stage ---------------------------------------------------


class _NoArgs(BaseModel):
    pass


def smoke_image_tool() -> ToolSpec:
    png = make_two_colour_png(64, 32, SMOKE_COLOURS["blue"], SMOKE_COLOURS["yellow"])
    image = ImageData("image/png", base64.b64encode(png).decode("ascii"))

    def handler(_ctx: ToolContext, _args: _NoArgs) -> ToolResult:
        # The text must not name the colours: the model can only know them by seeing the image.
        return ToolResult(text="测试图片已生成（左右两半各是一种纯色）。", images=[image])

    return ToolSpec(
        name="smoke_image",
        description="返回一张测试图片。",
        input_model=_NoArgs,
        stages={"topic"},
        handler=handler,
    )


class SmokeStage:
    """Delegates to a real placeholder stage, adds `smoke_image`, disables web tools
    (keeps the turn small and deterministic)."""

    allow_web = False
    workspaceless = False

    def finalize_blockers(self, workdir: Path) -> list[str]:
        return []

    def __init__(self, base: StageDefinition) -> None:
        self._base = base
        self.name = base.name

    def system_prompt(self) -> str:
        return self._base.system_prompt()

    def tools(self) -> list[ToolSpec]:
        return [smoke_image_tool()]

    def write_scope(self) -> WriteScope:
        return self._base.write_scope()

    def upstream_stages(self) -> list[str]:
        return self._base.upstream_stages()

    def artifact_dirs(self) -> list[str]:
        return self._base.artifact_dirs()

    def status_summary(self, workdir: Path) -> str:
        return self._base.status_summary(workdir)


class _NoWebStage(SmokeStage):
    def tools(self) -> list[ToolSpec]:
        return []


# ---- harness -----------------------------------------------------------------


@dataclass
class TurnOutcome:
    turn: TurnValue
    events: list[TurnEventValue]

    @property
    def tool_names(self) -> list[str]:
        return [str(e.payload["name"]) for e in self.events if e.type == "tool_call"]

    @property
    def text(self) -> str:
        return "\n".join(str(e.payload["text"]) for e in self.events if e.type == "text")

    def tool_results(self, name: str) -> list[dict[str, Any]]:
        ids = {
            e.payload["call_id"]
            for e in self.events
            if e.type == "tool_call" and e.payload["name"] == name
        }
        return [
            e.payload
            for e in self.events
            if e.type == "tool_result" and e.payload["call_id"] in ids
        ]

    def used_tool(self, name: str) -> bool:
        """是否调用过某个工具；Claude 侧业务工具带 `mcp__<server>__` 前缀，所以按后缀匹配。"""
        return any(n == name or n.endswith(f"__{name}") for n in self.tool_names)

    def notices(self, kind: str) -> list[dict[str, Any]]:
        return [e.payload for e in self.events if e.type == "notice" and e.payload["kind"] == kind]


@dataclass
class SmokeHarness:
    data_dir: Path
    engine: Engine
    blobs: BlobStore
    registry: StageRegistry
    runner: TurnRunner
    project_id: str

    @property
    def workdir(self) -> Path:
        return project_dir(self.data_dir, self.project_id)

    def profile(
        self, seed_name: str, *, model: str | None = None, suffix: str = "", **limits: Any
    ) -> str:
        """Copy a seed profile (real model name, prices) with smoke-test limits;
        returns the new profile id. `model`/`suffix` (M5 T7) make a second profile of the same
        provider and auth with another model name, for switching models inside a session."""
        seed = get_model_profile(self.engine, seed_name)
        assert seed is not None, seed_name
        name = f"smoke-{seed_name}{suffix}"
        with session_scope(self.engine) as db:
            row = ModelProfile(
                name=name,
                provider=seed.provider,
                model=model or seed.model,
                runtime=seed.runtime,
                base_url=seed.base_url,
                api_key_env=seed.api_key_env,
                supports_vision=seed.supports_vision,
                price_input=seed.price_input,
                price_output=seed.price_output,
                **limits,
            )
            db.add(row)
            db.flush()
            return row.id

    def session(self, profile_id: str, runtime: str, stage: str = "topic") -> str:
        return create_session(
            self.engine,
            project_id=self.project_id,
            stage=stage,
            model_profile_id=profile_id,
            runtime=runtime,
        ).id

    def brainstorm_session(self, profile_id: str, runtime: str) -> str:
        """没有项目的头脑风暴会话（M4）。"""
        return create_session(
            self.engine,
            project_id=None,
            stage="brainstorm",
            model_profile_id=profile_id,
            runtime=runtime,
        ).id

    async def turn(self, session_id: str, text: str) -> TurnOutcome:
        turn_id = await self.runner.start_turn(session_id, UserInput(text=text))
        await asyncio.wait_for(self.runner.wait(turn_id), timeout=TURN_TIMEOUT_SECONDS)
        return self._outcome(session_id, turn_id)

    async def turn_cancelled_at_tool_call(self, session_id: str, text: str) -> TurnOutcome:
        """Start a turn and cancel it (like the UI's stop button) as soon as its
        first tool call is persisted."""
        turn_id = await self.runner.start_turn(session_id, UserInput(text=text))
        finished = asyncio.ensure_future(self.runner.wait(turn_id))

        async def first_tool_call() -> None:
            while not finished.done() and not any(
                e.turn_id == turn_id and e.type == "tool_call"
                for e in list_events(self.engine, session_id)
            ):
                await asyncio.sleep(0.2)

        await asyncio.wait_for(first_tool_call(), timeout=TURN_TIMEOUT_SECONDS)
        if not finished.done():  # otherwise the turn ended before any tool call
            assert self.runner.cancel(turn_id)
        await asyncio.wait_for(finished, timeout=TURN_TIMEOUT_SECONDS)
        return self._outcome(session_id, turn_id)

    def _outcome(self, session_id: str, turn_id: str) -> TurnOutcome:
        turn = get_turn(self.engine, turn_id)
        assert turn is not None
        events = [e for e in list_events(self.engine, session_id) if e.turn_id == turn_id]
        return TurnOutcome(turn, events)


def build_harness(
    tmp_path: Path,
    *,
    cancel_grace_seconds: float = 10.0,
    real_stages: bool = False,
    web_mode: Literal["tools", "native"] = "tools",
) -> SmokeHarness:
    """`real_stages=True`（M4）：注册真实的 brainstorm/topic/narrative/animation 阶段（带联网
    工具、`check_brief` 等），并按 `web_mode` 决定联网方式；默认仍是 M1 的精简阶段。"""
    data_dir = tmp_path / "data"
    engine = make_engine(tmp_path / "studio.db")
    migrate(engine)
    # Same Settings source as `make dev` (env / backend/.env), so the seed rows carry
    # the configured gateways (STUDIO_ANTHROPIC_BASE_URL, STUDIO_OPENAI_BASE_URL,
    # STUDIO_OPENAI_MODEL) and `profile()` copies them.
    settings = Settings(data_dir=data_dir, web_mode=web_mode)
    seed_model_profiles(engine, enable_fake_runtime=False, settings=settings)
    registry = StageRegistry()
    if real_stages:
        for stage in (BRAINSTORM, TOPIC, NARRATIVE, ANIMATION):
            registry.register(stage)
    else:
        registry.register(SmokeStage(TOPIC))
        registry.register(_NoWebStage(NARRATIVE))
        registry.register(_NoWebStage(ANIMATION))
    factory = RuntimeFactory()
    register_claude(factory, settings)
    register_openai(factory, settings)
    blobs = BlobStore(data_dir / "blobs")
    runner = TurnRunner(
        engine,
        blobs,
        registry,
        factory,
        SessionBus(),
        settings,
        cancel_grace_seconds=cancel_grace_seconds,
    )

    project = create_project(engine, title="冒烟测试")
    for stage, status in (("topic", "active"), ("narrative", "locked"), ("animation", "locked")):
        create_stage(engine, project_id=project.id, stage=stage, status=status)
    style = project_dir(data_dir, project.id) / "style" / "STYLE.md"
    style.parent.mkdir(parents=True, exist_ok=True)
    style.write_text("# 风格\n", encoding="utf-8")
    create_snapshot(engine, blobs, project.id, reason="init")
    return SmokeHarness(data_dir, engine, blobs, registry, runner, project.id)


# ---- evidence ----------------------------------------------------------------

_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_-]{8,})")


def record_evidence(case: str, payload: dict[str, Any], directory: Path = EVIDENCE_DIR) -> Path:
    """Write one case's observations to `directory` (default `data/evidence/m1/smoke/`,
    git-ignored). Anything that looks like an API key is masked."""
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"{stamp}-{case}.json"
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    path.write_text(_SECRET_RE.sub("sk-***", text), encoding="utf-8")
    return path


def outcome_summary(outcome: TurnOutcome) -> dict[str, Any]:
    turn = outcome.turn
    return {
        "status": turn.status,
        "error": turn.error,
        "cost_usd": turn.cost_usd,
        "usage": turn.usage,
        "tool_calls": outcome.tool_names,
        "events": [{"type": e.type, "payload": e.payload} for e in outcome.events],
    }
