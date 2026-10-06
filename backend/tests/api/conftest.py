"""api 测试的共用夹具：跑通 FastAPI lifespan 的 httpx `AsyncClient`。

按简报要求（T7 关键点 7）：用 `httpx.AsyncClient` + `ASGITransport`，通过
`app.router.lifespan_context(app)` 触发 `main._lifespan`（不引入 `asgi-lifespan`
依赖），这样 `app.state` 上才有 `engine`/`blobs`/`registry`/`turn_runner` 等
`api/deps.py` 依赖的单例。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from httpx import Response as HttpxResponse

from studio.agent import register_fake
from studio.agent.fake import FakeRuntime, sleep
from studio.agent.runtime import UserInput
from studio.agent.stage import StageRegistry
from studio.agent.tools import ToolSpec
from studio.config import Settings
from studio.db.repo.profiles import get_model_profile
from studio.db.repo.sessions import create_session
from studio.main import create_app
from studio.workspace import project_dir
from studio.workspace.scope import WriteScope


@dataclass
class ApiEnv:
    """一个跑起来的 app + 已进入 lifespan 的 client，外加几个测试常用的便利方法。"""

    app: FastAPI
    client: AsyncClient

    @property
    def data_dir(self) -> Path:
        return self.app.state.settings.data_dir

    def workdir(self, project_id: str) -> Path:
        return project_dir(self.data_dir, project_id)

    async def create_project(self, title: str = "测试项目") -> dict[str, Any]:
        response = await self.client.post("/api/projects", json={"title": title})
        assert response.status_code == 201, response.text
        return response.json()

    async def make_busy(self, project_id: str, stage: str = "topic") -> str:
        """启动一个永远不结束的 turn，让 `TurnRunner.is_project_busy` 返回真。

        用完后必须调用 `release_busy` 清理，否则任务会一直挂着。
        """
        profile = get_model_profile(self.app.state.engine, "fake")
        assert profile is not None
        session = create_session(
            self.app.state.engine,
            project_id=project_id,
            stage=stage,
            model_profile_id=profile.id,
            runtime="fake",
        )
        # 替换掉默认的 fake 注册：默认脚本回显一句话就立即结束，
        # 测试需要的是一个"一直忙"的 turn。
        self.app.state.runtime_factory.register("fake", lambda: FakeRuntime([sleep(30)]))
        return await self.app.state.turn_runner.start_turn(session.id, UserInput(text="占位"))

    async def release_busy(self, turn_id: str) -> None:
        self.app.state.turn_runner.cancel(turn_id)
        await self.app.state.turn_runner.wait(turn_id)
        register_fake(self.app.state.runtime_factory)


@pytest.fixture
async def api_env(tmp_path: Path) -> AsyncIterator[ApiEnv]:
    settings = Settings(data_dir=tmp_path / "data", enable_fake_runtime=True)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            yield ApiEnv(app=app, client=client)


def assert_detail(response: HttpxResponse) -> str:
    body = response.json()
    assert "detail" in body
    return body["detail"]


class FakeStage:
    """Test-only stand-in for not-yet-implemented stages (concept, produce, ...)."""

    allow_web = False
    workspaceless = False

    def __init__(self, name: str, reads: list[str], artifact_dir: str) -> None:
        self.name = name
        self._reads = reads
        self._artifact_dir = artifact_dir

    def system_prompt(self) -> str:
        return self.name

    def tools(self) -> list[ToolSpec]:
        return []

    def write_scope(self) -> WriteScope:
        return WriteScope(writable=[f"{self._artifact_dir}/"], tool_managed=[])

    def reads(self) -> list[str]:
        return list(self._reads)

    def prepare_turn(self, workdir: Path) -> None:
        return None

    def artifact_dirs(self) -> list[str]:
        return [self._artifact_dir]

    def status_summary(self, workdir: Path) -> str:
        return ""

    def finalize_blockers(self, workdir: Path) -> list[str]:
        return []


def register_reel_stages(registry: StageRegistry) -> None:
    for stage in (
        FakeStage("concept", [], "concept"),
        FakeStage("produce", ["concept"], "music"),
    ):
        registry.register(stage)
