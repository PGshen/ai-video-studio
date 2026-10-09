"""消息附件（multipart）与 `GET /api/sessions/{id}/attachments/{sha}`
（设计 2026-10-09 §4–§5，计划 chat-attachments T3）。"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import update

from studio.agent.runner import SessionBusyError
from studio.agent.runtime import UserInput
from studio.api.attachments import MAX_FILE_BYTES
from studio.db.engine import session_scope
from studio.db.models import ModelProfile
from studio.db.repo.profiles import get_model_profile
from studio.db.repo.sessions import create_session
from studio.db.repo.turns import NEVER_STARTED_ERROR, create_turn_if_session_idle, interrupt_turn
from studio.styles.layout import draft_dir

from .conftest import ApiEnv, assert_detail

PNG = b"\x89PNG\r\n\x1a\n" + b"png-body"


def _fake_profile_id(api_env: ApiEnv) -> str:
    profile = get_model_profile(api_env.app.state.engine, "fake")
    assert profile is not None
    return profile.id


@pytest.fixture(autouse=True)
def _fake_sees_images(api_env: ApiEnv) -> None:
    """这些用例按支持图片的模型来测；不支持图片的分流见 `test_attachments.py`。"""
    with session_scope(api_env.app.state.engine) as db:
        db.execute(
            update(ModelProfile).where(ModelProfile.name == "fake").values(supports_vision=True)
        )


Call = tuple[UserInput, dict[str, Any]]


def _record_start_turn(api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch) -> list[Call]:
    runner = api_env.app.state.turn_runner
    original = runner.start_turn
    calls: list[Call] = []

    async def recording(session_id: str, user_input: UserInput, **kwargs: Any) -> str:
        calls.append((user_input, kwargs))
        return await original(session_id, user_input, **kwargs)

    monkeypatch.setattr(runner, "start_turn", recording)
    return calls


async def _project_session(api_env: ApiEnv) -> tuple[str, str]:
    pid = (await api_env.create_project())["id"]
    created = await api_env.client.post(
        f"/api/projects/{pid}/stages/topic/sessions",
        json={"model_profile_id": _fake_profile_id(api_env)},
    )
    return pid, created.json()["id"]


async def _brainstorm_session(api_env: ApiEnv) -> str:
    created = await api_env.client.post(
        "/api/brainstorm/sessions", json={"model_profile_id": _fake_profile_id(api_env)}
    )
    return created.json()["id"]


async def _send(api_env: ApiEnv, session_id: str, text: str, files: list[tuple[str, bytes]]) -> Any:
    return await api_env.client.post(
        f"/api/sessions/{session_id}/messages",
        data={"text": text},
        files=[("files", (name, data)) for name, data in files],
    )


async def _wait(api_env: ApiEnv, turn_id: str) -> None:
    await api_env.app.state.turn_runner.wait(turn_id)


def _uploads(workdir: Path) -> list[Path]:
    root = workdir / "uploads"
    return sorted(root.iterdir()) if root.is_dir() else []


class TestProjectSession:
    async def test_image_goes_to_user_input_images(
        self, api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _record_start_turn(api_env, monkeypatch)
        _, sid = await _project_session(api_env)

        response = await _send(api_env, sid, "看图", [("a.png", PNG)])

        assert response.status_code == 202, response.text
        await _wait(api_env, response.json()["turn_id"])
        (user_input, kwargs) = calls[0]
        assert user_input.text == "看图"
        assert base64.b64decode(user_input.images[0].data_base64) == PNG
        assert kwargs["attachments"][0]["kind"] == "image"

    async def test_file_lands_in_uploads_and_user_message_stays_original(
        self, api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _record_start_turn(api_env, monkeypatch)
        pid, sid = await _project_session(api_env)

        response = await _send(api_env, sid, "读一下", [("notes.md", b"# hi")])

        assert response.status_code == 202, response.text
        await _wait(api_env, response.json()["turn_id"])
        (uploaded,) = _uploads(api_env.workdir(pid))
        assert uploaded.read_bytes() == b"# hi"
        assert "uploads/" in calls[0][0].text
        detail = (await api_env.client.get(f"/api/sessions/{sid}")).json()
        turn = detail["turns"][0]
        assert turn["user_message"] == "读一下"
        assert turn["attachments"][0]["path"] == f"uploads/{uploaded.name}"

    async def test_json_body_still_works(self, api_env: ApiEnv) -> None:
        _, sid = await _project_session(api_env)
        response = await api_env.client.post(f"/api/sessions/{sid}/messages", json={"text": "你好"})
        assert response.status_code == 202, response.text
        await _wait(api_env, response.json()["turn_id"])

    async def test_oversized_file_is_422_and_writes_nothing(self, api_env: ApiEnv) -> None:
        pid, sid = await _project_session(api_env)

        response = await _send(
            api_env, sid, "x", [("ok.md", b"ok"), ("big.txt", b"a" * (MAX_FILE_BYTES + 1))]
        )

        assert response.status_code == 422
        assert_detail(response)
        assert _uploads(api_env.workdir(pid)) == []

    async def test_empty_message_is_422(self, api_env: ApiEnv) -> None:
        _, sid = await _project_session(api_env)
        response = await _send(api_env, sid, "  ", [])
        assert response.status_code == 422

    async def test_busy_session_is_409_and_writes_nothing(self, api_env: ApiEnv) -> None:
        pid, sid = await _project_session(api_env)
        create_turn_if_session_idle(api_env.app.state.engine, sid, "占位")

        response = await _send(api_env, sid, "x", [("a.md", b"a")])

        assert response.status_code == 409
        assert _uploads(api_env.workdir(pid)) == []

    async def test_session_turning_busy_after_write_removes_the_files(
        self, api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pid, sid = await _project_session(api_env)

        async def busy(session_id: str, user_input: UserInput, **kwargs: Any) -> str:
            raise SessionBusyError(session_id)

        monkeypatch.setattr(api_env.app.state.turn_runner, "start_turn", busy)

        response = await _send(api_env, sid, "x", [("a.md", b"a")])

        assert response.status_code == 409
        assert _uploads(api_env.workdir(pid)) == []


class TestProjectBusy:
    """另一个会话的一轮正在跑时，它结束时的越界检查会把新出现的 `uploads/` 文件当越权改动删掉，
    所以带文件的消息要等项目空闲；只带图片的不写工作区，照常排队。"""

    async def test_file_is_409_while_another_session_runs(
        self, api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pid, sid = await _project_session(api_env)
        monkeypatch.setattr(api_env.app.state.turn_runner, "is_project_busy", lambda _pid: True)

        response = await _send(api_env, sid, "x", [("a.md", b"a")])

        assert response.status_code == 409
        assert_detail(response)
        assert _uploads(api_env.workdir(pid)) == []

    async def test_image_is_accepted_while_another_session_runs(
        self, api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, sid = await _project_session(api_env)
        monkeypatch.setattr(api_env.app.state.turn_runner, "is_project_busy", lambda _pid: True)

        response = await _send(api_env, sid, "x", [("a.png", PNG)])

        assert response.status_code == 202, response.text
        monkeypatch.undo()
        await _wait(api_env, response.json()["turn_id"])


class TestBrainstormSession:
    async def test_file_is_rejected(self, api_env: ApiEnv) -> None:
        sid = await _brainstorm_session(api_env)
        response = await _send(api_env, sid, "x", [("a.md", b"a")])
        assert response.status_code == 422
        assert response.json()["detail"] == "选题对话只支持上传图片"

    async def test_image_is_accepted(
        self, api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _record_start_turn(api_env, monkeypatch)
        sid = await _brainstorm_session(api_env)

        response = await _send(api_env, sid, "x", [("a.png", PNG)])

        assert response.status_code == 202, response.text
        await _wait(api_env, response.json()["turn_id"])
        assert len(calls[0][0].images) == 1


class TestStyleSession:
    async def test_file_lands_in_the_style_draft_uploads(self, api_env: ApiEnv) -> None:
        style_id = (await api_env.client.post("/api/styles")).json()["id"]
        created = await api_env.client.post(
            f"/api/styles/{style_id}/sessions",
            json={"model_profile_id": _fake_profile_id(api_env)},
        )
        sid = created.json()["id"]

        response = await _send(api_env, sid, "参考", [("ref.md", b"ref")])

        assert response.status_code == 202, response.text
        (uploaded,) = _uploads(draft_dir(api_env.data_dir, style_id))
        assert uploaded.read_bytes() == b"ref"
        await _wait(api_env, response.json()["turn_id"])


class TestAttachmentImage:
    async def test_serves_an_image_of_this_session(self, api_env: ApiEnv) -> None:
        _, sid = await _project_session(api_env)
        sent = await _send(api_env, sid, "x", [("a.png", PNG)])
        await _wait(api_env, sent.json()["turn_id"])
        detail = (await api_env.client.get(f"/api/sessions/{sid}")).json()
        sha = detail["turns"][0]["attachments"][0]["sha256"]

        response = await api_env.client.get(f"/api/sessions/{sid}/attachments/{sha}")

        assert response.status_code == 200
        assert response.content == PNG
        assert response.headers["content-type"] == "image/png"

    async def test_image_of_another_session_is_404(self, api_env: ApiEnv) -> None:
        _, sid = await _project_session(api_env)
        sent = await _send(api_env, sid, "x", [("a.png", PNG)])
        await _wait(api_env, sent.json()["turn_id"])
        sha = (await api_env.client.get(f"/api/sessions/{sid}")).json()["turns"][0]["attachments"][
            0
        ]["sha256"]
        other = await _brainstorm_session(api_env)

        response = await api_env.client.get(f"/api/sessions/{other}/attachments/{sha}")

        assert response.status_code == 404


class TestContinueNeverStarted:
    async def test_resends_the_original_attachments(
        self, api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pid = (await api_env.create_project())["id"]
        engine = api_env.app.state.engine
        session = create_session(
            engine,
            project_id=pid,
            stage="topic",
            model_profile_id=_fake_profile_id(api_env),
            runtime="fake",
        )
        sha = api_env.app.state.blobs.put(PNG)
        records = [
            {"kind": "image", "name": "a.png", "size": len(PNG), "sha256": sha, "path": None},
            {
                "kind": "file",
                "name": "b.md",
                "size": 2,
                "sha256": None,
                "path": "uploads/abcd1234-b.md",
                "binary": False,
            },
        ]
        turn = create_turn_if_session_idle(engine, session.id, "原文", attachments=records)
        assert turn is not None
        interrupt_turn(engine, turn.id, end_snapshot_id=None, error=NEVER_STARTED_ERROR)
        calls = _record_start_turn(api_env, monkeypatch)

        response = await api_env.client.post(f"/api/sessions/{session.id}/continue")

        assert response.status_code == 202, response.text
        await asyncio.wait_for(_wait(api_env, response.json()["turn_id"]), 10)
        user_input, kwargs = calls[0]
        assert user_input.text.startswith("原文")
        assert "uploads/abcd1234-b.md" in user_input.text
        assert base64.b64decode(user_input.images[0].data_base64) == PNG
        assert [r["name"] for r in kwargs["attachments"]] == ["a.png", "b.md"]
