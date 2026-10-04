"""`/api/styles`（计划 style-library T3）：列表、详情、草稿、保存、复制、删除、默认风格。"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import Engine

from studio.agent.fake import FakeRuntime, sleep, write
from studio.agent.runtime import UserInput
from studio.db.repo.profiles import get_model_profile
from studio.db.repo.sessions import get_session
from studio.styles import store
from studio.styles.layout import draft_dir, style_dir

from .conftest import ApiEnv, assert_detail

ENTRY = """---
name: 暖纸双色
description: 暖色纸张质感的双色风格
category: 概念传记
---

先读 `references/color-scheme.md`，再看 `exemplars/exemplar-1.json`。
"""


def _files(entry: str = ENTRY) -> dict[str, str]:
    return {
        "STYLE.md": entry,
        "references/color-scheme.md": "主色：暖白",
        "exemplars/exemplar-1.json": "{}",
    }


def _entry(name: str) -> str:
    return ENTRY.replace("name: 暖纸双色", f"name: {name}")


def _make(api_env: ApiEnv, name: str = "暖纸双色") -> str:
    return store.import_style(api_env.data_dir, _files(_entry(name))).id


class TestListAndRead:
    async def test_empty_library(self, api_env: ApiEnv) -> None:
        response = await api_env.client.get("/api/styles")
        assert response.status_code == 200
        assert response.json() == []

    async def test_list_returns_summaries_without_file_contents(self, api_env: ApiEnv) -> None:
        style_id = _make(api_env)

        response = await api_env.client.get("/api/styles")

        assert response.status_code == 200
        [item] = response.json()
        assert item["id"] == style_id
        assert item["name"] == "暖纸双色"
        assert item["category"] == "概念传记"
        assert item["description"] == "暖色纸张质感的双色风格"
        assert (item["reference_count"], item["exemplar_count"]) == (1, 1)
        assert item["is_default"] is False
        assert item["has_draft"] is False
        assert item["is_new"] is False
        assert "modified_at" in item
        assert "files" not in item

    async def test_get_returns_every_file(self, api_env: ApiEnv) -> None:
        style_id = _make(api_env)

        response = await api_env.client.get(f"/api/styles/{style_id}")

        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "暖纸双色"
        assert body["files"] == _files(_entry("暖纸双色"))

    async def test_unknown_or_malformed_ids_are_404(self, api_env: ApiEnv) -> None:
        for style_id in ("missing", "a.b", ".hidden"):
            response = await api_env.client.get(f"/api/styles/{style_id}")
            assert response.status_code == 404, style_id
            assert "风格不存在" in assert_detail(response)
        # an encoded slash never reaches the handler: the router answers 404 itself
        assert (await api_env.client.get("/api/styles/..%2Fevil")).status_code == 404

    async def test_a_broken_directory_does_not_break_the_list(self, api_env: ApiEnv) -> None:
        good = _make(api_env)
        broken = style_dir(api_env.data_dir, "broken")
        broken.mkdir(parents=True)
        (broken / "STYLE.md").write_text("没有 frontmatter")

        response = await api_env.client.get("/api/styles")

        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == [good]


class TestNewStyle:
    async def test_create_opens_a_template_draft_listed_as_a_new_style(
        self, api_env: ApiEnv
    ) -> None:
        response = await api_env.client.post("/api/styles")

        assert response.status_code == 201
        body = response.json()
        assert body["is_new"] is True and body["dirty"] is True
        assert body["files"] == ["STYLE.md"]
        [item] = (await api_env.client.get("/api/styles")).json()
        assert item["id"] == body["id"]
        assert item["is_new"] is True and item["has_draft"] is True
        # there is no saved version yet
        assert (await api_env.client.get(f"/api/styles/{body['id']}")).status_code == 404

    async def test_edit_and_save_makes_it_a_listed_style(self, api_env: ApiEnv) -> None:
        style_id = (await api_env.client.post("/api/styles")).json()["id"]
        path = f"/api/styles/{style_id}/draft/files/STYLE.md"
        content = (await api_env.client.get(path)).json()["content"]
        edited = content.replace("name: 新风格", "name: 我的风格")
        assert (await api_env.client.put(path, json={"content": edited})).status_code == 200

        response = await api_env.client.post(f"/api/styles/{style_id}/draft/save")

        assert response.status_code == 200
        assert response.json()["name"] == "我的风格"
        [item] = (await api_env.client.get("/api/styles")).json()
        assert item["id"] == style_id and item["has_draft"] is False
        assert (await api_env.client.get(f"/api/styles/{style_id}/draft/files")).status_code == 404

    async def test_discarding_a_never_saved_draft_removes_it(self, api_env: ApiEnv) -> None:
        style_id = (await api_env.client.post("/api/styles")).json()["id"]

        response = await api_env.client.delete(f"/api/styles/{style_id}/draft")

        assert response.status_code == 204
        assert not draft_dir(api_env.data_dir, style_id).exists()
        assert (await api_env.client.get("/api/styles")).json() == []


class TestDraftFiles:
    async def test_open_edit_read_and_delete_files(self, api_env: ApiEnv) -> None:
        style_id = _make(api_env)
        base = f"/api/styles/{style_id}/draft"

        opened = await api_env.client.post(base)
        assert opened.status_code == 200
        assert opened.json() == {
            "id": style_id,
            "is_new": False,
            "dirty": False,
            "busy": False,
            "files": ["STYLE.md", "exemplars/exemplar-1.json", "references/color-scheme.md"],
        }

        put = await api_env.client.put(f"{base}/files/references/notes.md", json={"content": "n"})
        assert put.status_code == 200
        assert (await api_env.client.get(f"{base}/files/references/notes.md")).json() == {
            "content": "n"
        }
        status = (await api_env.client.get(f"{base}/files")).json()
        assert status["dirty"] is True
        assert "references/notes.md" in status["files"]

        deleted = await api_env.client.delete(f"{base}/files/references/notes.md")
        assert deleted.status_code == 204
        assert (await api_env.client.get(f"{base}/files/references/notes.md")).status_code == 404

    async def test_the_saved_version_is_untouched_until_save(self, api_env: ApiEnv) -> None:
        style_id = _make(api_env)
        base = f"/api/styles/{style_id}/draft"
        await api_env.client.post(base)
        await api_env.client.put(
            f"{base}/files/references/color-scheme.md", json={"content": "主色：深蓝"}
        )

        saved = (await api_env.client.get(f"/api/styles/{style_id}")).json()
        assert saved["files"]["references/color-scheme.md"] == "主色：暖白"
        assert (await api_env.client.get("/api/styles")).json()[0]["has_draft"] is True

        await api_env.client.post(f"{base}/save")
        saved = (await api_env.client.get(f"/api/styles/{style_id}")).json()
        assert saved["files"]["references/color-scheme.md"] == "主色：深蓝"

    async def test_discard_restores_the_saved_version(self, api_env: ApiEnv) -> None:
        style_id = _make(api_env)
        base = f"/api/styles/{style_id}/draft"
        await api_env.client.post(base)
        await api_env.client.put(f"{base}/files/STYLE.md", json={"content": "乱写"})

        assert (await api_env.client.delete(base)).status_code == 204

        assert (await api_env.client.get("/api/styles")).json()[0]["has_draft"] is False
        assert (await api_env.client.get(f"/api/styles/{style_id}")).json()["name"] == "暖纸双色"

    async def test_paths_outside_the_layout_are_400(self, api_env: ApiEnv) -> None:
        style_id = _make(api_env)
        base = f"/api/styles/{style_id}/draft"
        await api_env.client.post(base)
        for path in ("notes.md", "other/a.md", "references/.hidden.md", "references/a/b.md"):
            response = await api_env.client.put(f"{base}/files/{path}", json={"content": "x"})
            assert response.status_code == 400, path
        assert not (api_env.data_dir / "evil.md").exists()

    async def test_unknown_style_and_missing_draft_are_404(self, api_env: ApiEnv) -> None:
        style_id = _make(api_env)
        assert (await api_env.client.post("/api/styles/missing/draft")).status_code == 404
        # the style exists but no draft was opened
        for method, path in (
            ("GET", f"/api/styles/{style_id}/draft/files"),
            ("GET", f"/api/styles/{style_id}/draft/files/STYLE.md"),
            ("POST", f"/api/styles/{style_id}/draft/save"),
        ):
            response = await api_env.client.request(method, path)
            assert response.status_code == 404, (method, path)

    async def test_oversized_file_is_422(self, api_env: ApiEnv) -> None:
        style_id = _make(api_env)
        base = f"/api/styles/{style_id}/draft"
        await api_env.client.post(base)

        response = await api_env.client.put(
            f"{base}/files/references/big.md", json={"content": "x" * 200_001}
        )

        assert response.status_code == 422


class TestSave:
    async def test_invalid_draft_is_422_with_named_problems_and_nothing_changes(
        self, api_env: ApiEnv
    ) -> None:
        style_id = _make(api_env)
        base = f"/api/styles/{style_id}/draft"
        await api_env.client.post(base)
        await api_env.client.put(f"{base}/files/STYLE.md", json={"content": "# 没有 frontmatter"})

        response = await api_env.client.post(f"{base}/save")

        assert response.status_code == 422
        assert "frontmatter" in assert_detail(response)
        assert (await api_env.client.get(f"/api/styles/{style_id}")).json()["name"] == "暖纸双色"
        assert (await api_env.client.get(f"{base}/files")).status_code == 200

    async def test_renaming_to_an_existing_name_is_409(self, api_env: ApiEnv) -> None:
        _make(api_env, "甲")
        other = _make(api_env, "乙")
        base = f"/api/styles/{other}/draft"
        await api_env.client.post(base)
        await api_env.client.put(f"{base}/files/STYLE.md", json={"content": _entry("甲")})

        response = await api_env.client.post(f"{base}/save")

        assert response.status_code == 409
        assert "甲" in assert_detail(response)
        assert (await api_env.client.get(f"/api/styles/{other}")).json()["name"] == "乙"

    async def test_content_planted_in_the_draft_directory_is_rejected(
        self, api_env: ApiEnv
    ) -> None:
        style_id = _make(api_env)
        await api_env.client.post(f"/api/styles/{style_id}/draft")
        (draft_dir(api_env.data_dir, style_id) / "notes.md").write_text("顶层多余文件")

        response = await api_env.client.post(f"/api/styles/{style_id}/draft/save")

        assert response.status_code == 422
        assert "notes.md" in assert_detail(response)


class TestDuplicateAndDelete:
    async def test_duplicate_creates_an_independent_copy(self, api_env: ApiEnv) -> None:
        source = _make(api_env)

        response = await api_env.client.post(f"/api/styles/{source}/duplicate")

        assert response.status_code == 201
        copy = response.json()
        assert copy["id"] != source
        assert copy["name"] == "暖纸双色（副本）"
        assert copy["files"]["references/color-scheme.md"] == "主色：暖白"
        assert len((await api_env.client.get("/api/styles")).json()) == 2

    async def test_duplicate_of_unknown_style_is_404(self, api_env: ApiEnv) -> None:
        assert (await api_env.client.post("/api/styles/missing/duplicate")).status_code == 404

    async def test_delete_removes_the_style_and_its_draft(self, api_env: ApiEnv) -> None:
        style_id = _make(api_env)
        await api_env.client.post(f"/api/styles/{style_id}/draft")

        response = await api_env.client.delete(f"/api/styles/{style_id}")

        assert response.status_code == 204
        assert (await api_env.client.get("/api/styles")).json() == []
        assert not draft_dir(api_env.data_dir, style_id).exists()

    async def test_delete_unknown_style_is_404(self, api_env: ApiEnv) -> None:
        assert (await api_env.client.delete("/api/styles/missing")).status_code == 404


class TestDefaultStyle:
    async def _set_default(self, api_env: ApiEnv, style_id: str | None) -> Any:
        return await api_env.client.patch(
            "/api/settings", json={"default_style_preset_id": style_id}
        )

    async def test_default_is_flagged_in_the_list(self, api_env: ApiEnv) -> None:
        style_id = _make(api_env, "甲")
        _make(api_env, "乙")
        assert (await self._set_default(api_env, style_id)).status_code == 200

        flags = {
            i["name"]: i["is_default"] for i in (await api_env.client.get("/api/styles")).json()
        }

        assert flags == {"甲": True, "乙": False}

    async def test_default_must_exist(self, api_env: ApiEnv) -> None:
        response = await self._set_default(api_env, "missing")

        assert response.status_code == 422
        assert "风格不存在" in assert_detail(response)

    async def test_deleting_the_default_clears_the_setting(self, api_env: ApiEnv) -> None:
        style_id = _make(api_env)
        await self._set_default(api_env, style_id)

        await api_env.client.delete(f"/api/styles/{style_id}")

        settings = (await api_env.client.get("/api/settings")).json()
        assert settings["default_style_preset_id"] is None

    async def test_deleting_another_style_keeps_the_default(self, api_env: ApiEnv) -> None:
        keep = _make(api_env, "甲")
        other = _make(api_env, "乙")
        await self._set_default(api_env, keep)

        await api_env.client.delete(f"/api/styles/{other}")

        settings = (await api_env.client.get("/api/settings")).json()
        assert settings["default_style_preset_id"] == keep


def _is_active(engine: Engine, session_id: str) -> bool:
    session = get_session(engine, session_id)
    assert session is not None
    return session.is_active


def _fake_profile_id(api_env: ApiEnv) -> str:
    profile = get_model_profile(api_env.app.state.engine, "fake")
    assert profile is not None
    return profile.id


async def _new_session(api_env: ApiEnv, style_id: str) -> dict[str, Any]:
    response = await api_env.client.post(
        f"/api/styles/{style_id}/sessions", json={"model_profile_id": _fake_profile_id(api_env)}
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestStyleSessions:
    async def test_create_session_belongs_to_the_style(self, api_env: ApiEnv) -> None:
        style_id = _make(api_env)

        body = await _new_session(api_env, style_id)

        assert body["subject_id"] == style_id
        assert body["stage"] == "style"
        assert body["project_id"] is None
        assert body["is_active"] is True and body["status"] == "idle"

    async def test_a_never_saved_new_style_can_have_a_session_too(self, api_env: ApiEnv) -> None:
        style_id = (await api_env.client.post("/api/styles")).json()["id"]

        body = await _new_session(api_env, style_id)

        assert body["subject_id"] == style_id

    async def test_unknown_style_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post(
            "/api/styles/missing/sessions", json={"model_profile_id": _fake_profile_id(api_env)}
        )
        assert response.status_code == 404
        listing = await api_env.client.get("/api/styles/missing/sessions")
        assert listing.status_code == 404

    async def test_unknown_model_profile_is_400(self, api_env: ApiEnv) -> None:
        style_id = _make(api_env)
        response = await api_env.client.post(
            f"/api/styles/{style_id}/sessions", json={"model_profile_id": "nope"}
        )
        assert response.status_code == 400

    async def test_a_new_session_deactivates_only_that_styles_older_session(
        self, api_env: ApiEnv
    ) -> None:
        a, b = _make(api_env, "甲"), _make(api_env, "乙")
        old_a = await _new_session(api_env, a)
        only_b = await _new_session(api_env, b)

        new_a = await _new_session(api_env, a)

        engine = api_env.app.state.engine
        flags = {sid: _is_active(engine, sid) for sid in (old_a["id"], new_a["id"], only_b["id"])}
        assert flags == {old_a["id"]: False, new_a["id"]: True, only_b["id"]: True}

    async def test_list_returns_that_styles_sessions_in_creation_order(
        self, api_env: ApiEnv
    ) -> None:
        a, b = _make(api_env, "甲"), _make(api_env, "乙")
        first = await _new_session(api_env, a)
        second = await _new_session(api_env, a)
        await _new_session(api_env, b)

        response = await api_env.client.get(f"/api/styles/{a}/sessions")

        assert response.status_code == 200
        assert [s["id"] for s in response.json()] == [first["id"], second["id"]]

    async def test_deleting_the_style_removes_its_sessions(self, api_env: ApiEnv) -> None:
        style_id = _make(api_env)
        session = await _new_session(api_env, style_id)

        await api_env.client.delete(f"/api/styles/{style_id}")

        assert (await api_env.client.get(f"/api/sessions/{session['id']}")).status_code == 404

    async def test_discarding_a_never_saved_style_removes_its_sessions_too(
        self, api_env: ApiEnv
    ) -> None:
        style_id = (await api_env.client.post("/api/styles")).json()["id"]
        session = await _new_session(api_env, style_id)

        await api_env.client.delete(f"/api/styles/{style_id}/draft")

        assert (await api_env.client.get(f"/api/sessions/{session['id']}")).status_code == 404

    async def test_does_not_touch_brainstorm_sessions(self, api_env: ApiEnv) -> None:
        brainstorm = (
            await api_env.client.post(
                "/api/brainstorm/sessions", json={"model_profile_id": _fake_profile_id(api_env)}
            )
        ).json()
        style_id = _make(api_env)

        await _new_session(api_env, style_id)

        listing = (await api_env.client.get("/api/brainstorm/sessions")).json()
        assert [s["id"] for s in listing] == [brainstorm["id"]]
        assert listing[0]["is_active"] is True
        assert listing[0]["subject_id"] is None


async def _make_style_busy(api_env: ApiEnv, style_id: str) -> str:
    """让这套风格有一个永远不结束的对话轮次；用完要 `release_busy`。"""
    session = await _new_session(api_env, style_id)
    api_env.app.state.runtime_factory.register("fake", lambda: FakeRuntime([sleep(30)]))
    turn_id = await api_env.app.state.turn_runner.start_turn(session["id"], UserInput(text="占位"))
    for _ in range(200):
        if api_env.app.state.turn_runner.is_subject_busy(style_id):
            break
        await asyncio.sleep(0.01)
    return turn_id


class TestBusyWhileAiIsEditing:
    """同一套风格有对话轮次运行时，草稿的改动类操作被拒绝；读取和打开草稿仍然可以。"""

    async def test_writes_saves_discards_and_deletes_are_409_but_reads_are_fine(
        self, api_env: ApiEnv
    ) -> None:
        style_id = _make(api_env)
        base = f"/api/styles/{style_id}/draft"
        await api_env.client.post(base)
        turn_id = await _make_style_busy(api_env, style_id)
        try:
            writes = [
                ("PUT", f"{base}/files/references/color-scheme.md", {"json": {"content": "x"}}),
                ("DELETE", f"{base}/files/references/color-scheme.md", {}),
                ("POST", f"{base}/save", {}),
                ("DELETE", base, {}),
                ("DELETE", f"/api/styles/{style_id}", {}),
            ]
            for method, path, kwargs in writes:
                response = await api_env.client.request(method, path, **kwargs)
                assert response.status_code == 409, (method, path)
                assert "AI 正在修改" in assert_detail(response)

            assert (await api_env.client.get(f"{base}/files")).status_code == 200
            assert (await api_env.client.get(f"{base}/files/STYLE.md")).status_code == 200
            assert (await api_env.client.post(base)).status_code == 200  # reopening is idempotent
            assert (await api_env.client.get("/api/styles")).status_code == 200
        finally:
            await api_env.release_busy(turn_id)

        assert (
            await api_env.client.put(
                f"{base}/files/references/color-scheme.md", json={"content": "x"}
            )
        ).status_code == 200

    async def test_the_draft_status_says_whether_ai_is_working_on_it(self, api_env: ApiEnv) -> None:
        busy_id, other_id = _make(api_env, "甲"), _make(api_env, "乙")
        for style_id in (busy_id, other_id):
            await api_env.client.post(f"/api/styles/{style_id}/draft")

        async def busy(style_id: str) -> bool:
            body = (await api_env.client.get(f"/api/styles/{style_id}/draft/files")).json()
            return body["busy"]

        assert await busy(busy_id) is False
        turn_id = await _make_style_busy(api_env, busy_id)
        try:
            assert await busy(busy_id) is True
            assert await busy(other_id) is False
            opened = (await api_env.client.post(f"/api/styles/{busy_id}/draft")).json()
            assert opened["busy"] is True
        finally:
            await api_env.release_busy(turn_id)
        assert await busy(busy_id) is False

    async def test_another_style_is_not_affected(self, api_env: ApiEnv) -> None:
        busy_id, other_id = _make(api_env, "甲"), _make(api_env, "乙")
        await api_env.client.post(f"/api/styles/{other_id}/draft")
        turn_id = await _make_style_busy(api_env, busy_id)
        try:
            response = await api_env.client.put(
                f"/api/styles/{other_id}/draft/files/references/color-scheme.md",
                json={"content": "x"},
            )
            assert response.status_code == 200
        finally:
            await api_env.release_busy(turn_id)

    async def test_a_session_turn_can_actually_edit_the_draft(self, api_env: ApiEnv) -> None:
        style_id = _make(api_env)
        session = await _new_session(api_env, style_id)
        api_env.app.state.runtime_factory.register(
            "fake", lambda: FakeRuntime([write("references/color-scheme.md", "主色：深蓝")])
        )

        response = await api_env.client.post(
            f"/api/sessions/{session['id']}/messages", json={"text": "改配色"}
        )
        assert response.status_code == 202
        await api_env.app.state.turn_runner.wait(response.json()["turn_id"])

        draft = await api_env.client.get(
            f"/api/styles/{style_id}/draft/files/references/color-scheme.md"
        )
        assert draft.json() == {"content": "主色：深蓝"}
        saved = (await api_env.client.get(f"/api/styles/{style_id}")).json()
        assert saved["files"]["references/color-scheme.md"] == "主色：暖白"
