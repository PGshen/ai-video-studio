"""M5: lifespan shutdown finishes running turns before disposing the engine."""

from __future__ import annotations

import asyncio
from pathlib import Path

from studio.agent.fake import FakeRuntime, sleep
from studio.agent.runtime import UserInput
from studio.config import Settings
from studio.db.engine import make_engine
from studio.db.repo.profiles import get_model_profile
from studio.db.repo.projects import create_project
from studio.db.repo.sessions import create_session
from studio.db.repo.stages import create_stage
from studio.db.repo.turns import get_turn
from studio.main import create_app
from studio.workspace import create_snapshot, init_workspace


async def test_shutdown_interrupts_running_turn(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", enable_fake_runtime=True)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        engine = app.state.engine
        runner = app.state.turn_runner
        init_workspace(settings.data_dir, "p1", {"style/STYLE.md": "x"})
        create_project(engine, id="p1", title="t", settings={})
        create_stage(engine, project_id="p1", stage="topic", status="active")
        create_snapshot(engine, app.state.blobs, "p1", reason="init")
        profile = get_model_profile(engine, "fake")
        assert profile is not None
        session = create_session(
            engine, project_id="p1", stage="topic", model_profile_id=profile.id, runtime="fake"
        )
        app.state.runtime_factory.register("fake", lambda: FakeRuntime([sleep(30)]))
        turn_id = await runner.start_turn(session.id, UserInput(text="1"))
        while not runner.is_project_busy("p1"):
            await asyncio.sleep(0.01)

    check = make_engine(settings.data_dir / "studio.db")
    try:
        turn = get_turn(check, turn_id)
        assert turn is not None and turn.status == "interrupted"
        assert turn.end_snapshot_id is not None
    finally:
        check.dispose()
