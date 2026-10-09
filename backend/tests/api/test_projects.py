"""`/api/projects` 及定稿/重新打开接口（任务简报 T7）。"""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from brief_builder import make_brief
from studio.db.models import Project, ProjectStage, Snapshot
from studio.db.repo.jobs import claim_next, complete, create_job, get_job
from studio.db.repo.profiles import get_model_profile
from studio.db.repo.projects import get_project
from studio.db.repo.sessions import create_session, get_session
from studio.db.repo.snapshots import list_snapshots
from studio.db.repo.stages import list_stages
from studio.db.repo.suggestions import create_suggestion, get_suggestion
from studio.db.repo.turns import append_event, create_turn_if_session_idle, list_events, list_turns
from studio.styles import store as style_store
from studio.styles.layout import style_dir
from studio.workspace import files

from .conftest import ApiEnv, assert_detail


def _row_counts(api_env: ApiEnv) -> tuple[int, int, int]:
    def count(session: Session, model: type) -> int:
        return session.scalar(select(func.count()).select_from(model)) or 0

    with Session(api_env.app.state.engine) as session:
        return (count(session, Project), count(session, ProjectStage), count(session, Snapshot))


class TestCreateProjectKinds:
    async def test_default_kind_is_html_explainer(self, api_env: ApiEnv) -> None:
        body = await api_env.create_project()

        assert body["kind"] == {
            "video_kind": "explainer_html",
            "engine": "html",
            "narration": True,
            "music_source": "none",
            "pipeline": ["topic", "narrative", "animation_html"],
        }
        stages = list_stages(api_env.app.state.engine, body["id"])
        assert [(s.stage, s.status) for s in stages] == [
            ("topic", "active"),
            ("narrative", "locked"),
            ("animation_html", "locked"),
        ]

    async def test_explicit_kind_writes_settings(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post(
            "/api/projects",
            json={"title": "t", "engine": "html", "narration": True, "music_source": "none"},
        )

        assert response.status_code == 201
        settings = response.json()["settings"]
        assert settings["video_kind"] == "explainer_html"
        assert settings["engine"] == "html"
        assert settings["narration"] is True
        assert settings["music_source"] == "none"
        assert settings["pipeline"] == ["topic", "narrative", "animation_html"]

    async def test_manim_is_retired_and_422(self, api_env: ApiEnv) -> None:
        before = _row_counts(api_env)
        response = await api_env.client.post(
            "/api/projects",
            json={"title": "t", "engine": "manim", "narration": True, "music_source": "none"},
        )

        assert response.status_code == 422
        assert "Manim 动画已下线" in assert_detail(response)
        assert _row_counts(api_env) == before

    async def test_unavailable_kind_is_422_and_leaves_nothing(self, api_env: ApiEnv) -> None:
        before = _row_counts(api_env)
        workspaces_root = api_env.workdir("probe").parent

        def workspaces() -> list[str]:
            return (
                sorted(p.name for p in workspaces_root.iterdir())
                if workspaces_root.is_dir()
                else []
            )

        workspaces_before = workspaces()

        response = await api_env.client.post(
            "/api/projects",
            json={"title": "t", "engine": "html", "narration": True, "music_source": "import"},
        )

        assert response.status_code == 422
        assert "配乐" in assert_detail(response)
        assert _row_counts(api_env) == before
        assert workspaces() == workspaces_before

    async def test_invalid_kind_is_422_with_reason(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post(
            "/api/projects",
            json={"title": "t", "engine": "html", "narration": False, "music_source": "none"},
        )

        assert response.status_code == 422
        assert "无旁白的项目必须配乐" in assert_detail(response)

    async def test_partial_kind_is_422(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post("/api/projects", json={"title": "t", "engine": "html"})

        assert response.status_code == 422
        assert "同时提供 engine、narration、music_source" in assert_detail(response)

    async def test_client_settings_cannot_smuggle_kind_fields(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post(
            "/api/projects",
            json={
                "title": "t",
                "settings": {
                    "pipeline": ["animation"],
                    "video_kind": "music_video",
                    "engine": "html",
                },
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["kind"]["video_kind"] == "explainer_html"
        assert body["kind"]["pipeline"] == ["topic", "narrative", "animation_html"]
        assert body["settings"]["engine"] == "html"
        stages = list_stages(api_env.app.state.engine, body["id"])
        assert [s.stage for s in stages] == ["topic", "narrative", "animation_html"]

    async def test_html_explainer_is_creatable(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post(
            "/api/projects",
            json={
                "title": "HTML 讲解",
                "engine": "html",
                "narration": True,
                "music_source": "none",
            },
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["current_stage"] == "topic"
        assert body["kind"]["video_kind"] == "explainer_html"
        assert body["settings"]["pipeline"] == ["topic", "narrative", "animation_html"]
        stages = list_stages(api_env.app.state.engine, body["id"])
        assert [(s.stage, s.status) for s in stages] == [
            ("topic", "active"),
            ("narrative", "locked"),
            ("animation_html", "locked"),
        ]

    async def test_motion_reel_pipeline_stages_and_idea_card(self, api_env: ApiEnv) -> None:
        from studio.db.repo.ideas import create_idea

        idea = create_idea(api_env.app.state.engine, title="想法", pitch="p")

        response = await api_env.client.post(
            "/api/projects",
            json={
                "title": "短片",
                "idea_id": idea.id,
                "engine": "html",
                "narration": False,
                "music_source": "synth",
            },
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["current_stage"] == "concept"
        assert body["kind"]["video_kind"] == "motion_reel"
        stages = list_stages(api_env.app.state.engine, body["id"])
        assert [(s.stage, s.status) for s in stages] == [
            ("concept", "active"),
            ("produce", "locked"),
        ]
        assert (api_env.workdir(body["id"]) / "concept/notes/idea-card.md").is_file()
        assert not (api_env.workdir(body["id"]) / "topic").exists()
        stored = get_project(api_env.app.state.engine, body["id"])
        assert stored is not None
        assert stored.current_stage == "concept"

    async def test_patch_settings_cannot_change_kind(self, api_env: ApiEnv) -> None:
        body = await api_env.create_project()

        await api_env.client.patch(f"/api/projects/{body['id']}/settings", json={"engine": "manim"})

        detail = (await api_env.client.get(f"/api/projects/{body['id']}")).json()
        assert detail["kind"] == body["kind"]
        assert detail["settings"]["pipeline"] == ["topic", "narrative", "animation_html"]


class TestCreateProject:
    async def test_creates_workspace_stages_and_init_snapshot(self, api_env: ApiEnv) -> None:
        body = await api_env.create_project(title="我的视频")

        assert body["title"] == "我的视频"
        assert body["current_stage"] == "topic"
        project_id = body["id"]

        style = api_env.workdir(project_id) / "style" / "STYLE.md"
        assert style.is_file()

        stages = {s.stage: s.status for s in list_stages(api_env.app.state.engine, project_id)}
        assert stages == {"topic": "active", "narrative": "locked", "animation_html": "locked"}

        snapshots = list_snapshots(api_env.app.state.engine, project_id)
        assert len(snapshots) == 1
        assert snapshots[0].reason == "init"
        assert "style/STYLE.md" in snapshots[0].manifest

    async def test_accepts_settings(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post(
            "/api/projects", json={"title": "带设置", "settings": {"aspect_ratio": "16:9"}}
        )
        assert response.status_code == 201
        settings = response.json()["settings"]
        assert settings["aspect_ratio"] == "16:9"
        assert settings["video_kind"] == "explainer_html"


class TestListAndGetProject:
    async def test_list_returns_created_projects(self, api_env: ApiEnv) -> None:
        a = await api_env.create_project(title="A")
        b = await api_env.create_project(title="B")

        response = await api_env.client.get("/api/projects")

        assert response.status_code == 200
        ids = [p["id"] for p in response.json()]
        assert {a["id"], b["id"]} <= set(ids)

    async def test_get_includes_stage_statuses(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()

        response = await api_env.client.get(f"/api/projects/{project['id']}")

        assert response.status_code == 200
        body = response.json()
        stages = {s["stage"]: s["status"] for s in body["stages"]}
        assert stages == {"topic": "active", "narrative": "locked", "animation_html": "locked"}

    async def test_get_unknown_project_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.get("/api/projects/does-not-exist")
        assert response.status_code == 404
        assert_detail(response)

    async def test_get_busy_is_false_when_idle(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()

        response = await api_env.client.get(f"/api/projects/{project['id']}")

        assert response.status_code == 200
        assert response.json()["busy"] is False

    async def test_get_busy_is_true_while_a_turn_is_running(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()
        turn_id = await api_env.make_busy(project["id"])
        try:
            response = await api_env.client.get(f"/api/projects/{project['id']}")
            assert response.status_code == 200
            assert response.json()["busy"] is True
        finally:
            await api_env.release_busy(turn_id)


class TestFinalizeAndReopen:
    async def test_finalize_unlocks_downstream_stage(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()
        pid = project["id"]
        files.write_text_unscoped(api_env.workdir(pid), "topic/brief.md", make_brief())

        response = await api_env.client.post(f"/api/projects/{pid}/stages/topic/finalize")

        assert response.status_code == 200
        assert response.json()["status"] == "finalized"
        narrative = next(
            s for s in list_stages(api_env.app.state.engine, pid) if s.stage == "narrative"
        )
        assert narrative.status == "active"

    async def test_reopen_finalized_stage(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()
        pid = project["id"]
        files.write_text_unscoped(api_env.workdir(pid), "topic/brief.md", make_brief())
        await api_env.client.post(f"/api/projects/{pid}/stages/topic/finalize")

        response = await api_env.client.post(f"/api/projects/{pid}/stages/topic/reopen")

        assert response.status_code == 200
        assert response.json()["status"] == "active"

    async def test_current_stage_follows_finalize_and_reopen(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()
        pid = project["id"]
        assert project["current_stage"] == "topic"
        files.write_text_unscoped(api_env.workdir(pid), "topic/brief.md", make_brief())

        await api_env.client.post(f"/api/projects/{pid}/stages/topic/finalize")
        detail = (await api_env.client.get(f"/api/projects/{pid}")).json()
        assert detail["current_stage"] == "narrative"
        listed = (await api_env.client.get("/api/projects")).json()
        assert next(p for p in listed if p["id"] == pid)["current_stage"] == "narrative"

        await api_env.client.post(f"/api/projects/{pid}/stages/topic/reopen")
        detail = (await api_env.client.get(f"/api/projects/{pid}")).json()
        assert detail["current_stage"] == "topic"

    async def test_reopen_not_finalized_stage_is_conflict(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()

        response = await api_env.client.post(f"/api/projects/{project['id']}/stages/topic/reopen")

        assert response.status_code == 409
        assert_detail(response)

    async def test_unknown_stage_name_is_404(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()

        response = await api_env.client.post(
            f"/api/projects/{project['id']}/stages/no-such-stage/finalize"
        )

        assert response.status_code == 404
        assert_detail(response)

    async def test_finalize_while_project_busy_is_409(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()
        pid = project["id"]
        turn_id = await api_env.make_busy(pid)

        response = await api_env.client.post(f"/api/projects/{pid}/stages/topic/finalize")

        assert response.status_code == 409
        await api_env.release_busy(turn_id)

    async def test_finalize_on_unknown_project_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post("/api/projects/does-not-exist/stages/topic/finalize")
        assert response.status_code == 404


class TestCreateProjectFailureCleanup:
    async def test_failure_after_files_leaves_no_visible_project(
        self, api_env: ApiEnv, monkeypatch
    ) -> None:
        from studio.api import projects as projects_module

        fixed_id = UUID("11111111-1111-1111-1111-111111111111")
        monkeypatch.setattr(projects_module, "uuid4", lambda: fixed_id)

        def boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("模拟阶段行创建失败")

        monkeypatch.setattr(projects_module, "create_stage", boom)

        response = await api_env.client.post("/api/projects", json={"title": "会失败"})

        assert response.status_code == 500
        assert_detail(response)
        # every project row that might have been inserted before the failure is gone
        listing = await api_env.client.get("/api/projects")
        assert listing.json() == []
        # the `init` snapshot created by `_init_workspace` before the DB rows
        # is not left orphaned either (review finding: was previously leaked).
        assert list_snapshots(api_env.app.state.engine, fixed_id.hex) == []


class TestCreateProjectFromIdea:
    async def _idea(self, api_env: ApiEnv, **extra: object) -> dict:
        response = await api_env.client.post(
            "/api/ideas",
            json={
                "title": "排序为什么这么快",
                "pitch": "十亿条记录一秒排完",
                "counterintuitive": "大家以为排序慢，其实分治让它很快",
                "tags": ["算法", "排序"],
                "scores": {"counterintuitive": 5, "visual": 4},
                **extra,
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    async def test_creates_project_linked_to_idea_and_keeps_it_usable(
        self, api_env: ApiEnv
    ) -> None:
        idea = await self._idea(api_env)
        response = await api_env.client.post(
            "/api/projects", json={"title": "排序视频", "idea_id": idea["id"]}
        )
        assert response.status_code == 201, response.text
        project = response.json()
        assert project["idea_id"] == idea["id"]

        card = (await api_env.client.get(f"/api/ideas/{idea['id']}")).json()
        assert card["status"] == "idea"
        assert "project_id" not in card

    async def test_idea_card_is_seeded_into_workspace_and_init_snapshot(
        self, api_env: ApiEnv
    ) -> None:
        idea = await self._idea(api_env)
        project = (
            await api_env.client.post(
                "/api/projects", json={"title": "排序视频", "idea_id": idea["id"]}
            )
        ).json()

        path = api_env.workdir(project["id"]) / "topic" / "notes" / "idea-card.md"
        text = path.read_text(encoding="utf-8")
        assert "排序为什么这么快" in text
        assert "十亿条记录一秒排完" in text
        assert "大家以为排序慢，其实分治让它很快" in text
        assert "算法" in text
        assert "反直觉" in text and "5" in text

        snapshots = list_snapshots(api_env.app.state.engine, project["id"])
        assert len(snapshots) == 1 and snapshots[0].reason == "init"
        assert "topic/notes/idea-card.md" in snapshots[0].manifest
        assert "style/STYLE.md" in snapshots[0].manifest

    async def test_card_without_optional_fields_renders(self, api_env: ApiEnv) -> None:
        idea = (await api_env.client.post("/api/ideas", json={"title": "只有标题"})).json()
        response = await api_env.client.post(
            "/api/projects", json={"title": "P", "idea_id": idea["id"]}
        )
        assert response.status_code == 201
        text = (
            api_env.workdir(response.json()["id"]) / "topic" / "notes" / "idea-card.md"
        ).read_text(encoding="utf-8")
        assert "只有标题" in text

    async def test_unknown_idea_is_404_and_leaves_nothing(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post(
            "/api/projects", json={"title": "P", "idea_id": "nope"}
        )
        assert response.status_code == 404
        assert (await api_env.client.get("/api/projects")).json() == []
        assert not (api_env.data_dir / "projects").exists() or not list(
            (api_env.data_dir / "projects").iterdir()
        )

    async def test_one_idea_can_create_several_projects(self, api_env: ApiEnv) -> None:
        idea = await self._idea(api_env)
        first = await api_env.client.post(
            "/api/projects", json={"title": "P1", "idea_id": idea["id"]}
        )
        second = await api_env.client.post(
            "/api/projects", json={"title": "P2", "idea_id": idea["id"]}
        )
        assert first.status_code == 201 and second.status_code == 201
        projects = (await api_env.client.get("/api/projects")).json()
        assert {p["idea_id"] for p in projects} == {idea["id"]}
        assert len(projects) == 2

    async def test_archived_idea_is_409(self, api_env: ApiEnv) -> None:
        idea = await self._idea(api_env)
        await api_env.client.patch(f"/api/ideas/{idea['id']}", json={"status": "archived"})
        response = await api_env.client.post(
            "/api/projects", json={"title": "P", "idea_id": idea["id"]}
        )
        assert response.status_code == 409

    async def test_project_without_idea_still_works(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()
        assert project["idea_id"] is None
        assert not (api_env.workdir(project["id"]) / "topic").exists()


STYLE_ENTRY = """---
name: 暖纸双色
description: 暖色纸张质感的双色风格
---

先读 `references/color-scheme.md`。
"""


class TestCreateProjectWithStyle:
    async def _preset(self, api_env: ApiEnv, name: str = "暖纸双色", **extra: object) -> dict:
        entry = STYLE_ENTRY.replace("name: 暖纸双色", f"name: {name}")
        detail = style_store.import_style(
            api_env.data_dir,
            {
                "STYLE.md": entry,
                "references/color-scheme.md": "主色：暖白",
                "exemplars/exemplar-1.json": "{}",
            },
        )
        return {"id": detail.id, "name": detail.name}

    def _style_files(self, api_env: ApiEnv, project_id: str) -> dict[str, str]:
        workdir = api_env.workdir(project_id)
        return {
            path: files.read_text(workdir, path)
            for path in files.list_tree(workdir)
            if path.startswith("style/")
        }

    async def test_chosen_preset_is_written_into_style_dir_and_init_snapshot(
        self, api_env: ApiEnv
    ) -> None:
        preset = await self._preset(api_env)

        response = await api_env.client.post(
            "/api/projects", json={"title": "P", "style_preset_id": preset["id"]}
        )

        assert response.status_code == 201, response.text
        project = response.json()
        assert self._style_files(api_env, project["id"]) == {
            "style/STYLE.md": STYLE_ENTRY,
            "style/references/color-scheme.md": "主色：暖白",
            "style/exemplars/exemplar-1.json": "{}",
        }
        assert project["settings"]["style_preset_id"] == preset["id"]
        assert project["settings"]["style_name"] == "暖纸双色"
        snapshots = list_snapshots(api_env.app.state.engine, project["id"])
        assert [s.reason for s in snapshots] == ["init"]
        assert {p for p in snapshots[0].manifest if p.startswith("style/")} == {
            "style/STYLE.md",
            "style/references/color-scheme.md",
            "style/exemplars/exemplar-1.json",
        }

    async def test_screenshots_are_not_copied_into_the_project(self, api_env: ApiEnv) -> None:
        preset = await self._preset(api_env)
        style_store.open_draft(api_env.data_dir, preset["id"])
        style_store.add_draft_screenshot(
            api_env.data_dir, preset["id"], b"RIFF\x00\x00\x00\x00WEBPimage"
        )
        style_store.save_draft(api_env.data_dir, preset["id"])

        response = await api_env.client.post(
            "/api/projects", json={"title": "P", "style_preset_id": preset["id"]}
        )

        assert response.status_code == 201, response.text
        assert set(self._style_files(api_env, response.json()["id"])) == {
            "style/STYLE.md",
            "style/references/color-scheme.md",
            "style/exemplars/exemplar-1.json",
        }

    async def test_default_preset_is_used_when_none_is_requested(self, api_env: ApiEnv) -> None:
        await self._preset(api_env, name="别的")
        default = await self._preset(api_env)
        await api_env.client.patch("/api/settings", json={"default_style_preset_id": default["id"]})

        project = await api_env.create_project()

        assert project["settings"]["style_preset_id"] == default["id"]
        assert "style/references/color-scheme.md" in self._style_files(api_env, project["id"])

    async def test_requested_preset_beats_the_default(self, api_env: ApiEnv) -> None:
        default = await self._preset(api_env, name="默认")
        chosen = await self._preset(api_env)
        await api_env.client.patch("/api/settings", json={"default_style_preset_id": default["id"]})

        response = await api_env.client.post(
            "/api/projects", json={"title": "P", "style_preset_id": chosen["id"]}
        )

        assert response.json()["settings"]["style_name"] == "暖纸双色"

    async def test_without_any_preset_falls_back_to_the_placeholder(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project(title="我的视频")

        assert list(self._style_files(api_env, project["id"])) == ["style/STYLE.md"]
        assert "我的视频" in self._style_files(api_env, project["id"])["style/STYLE.md"]
        assert "style_preset_id" not in project["settings"]

    async def test_presets_without_a_default_also_fall_back_to_the_placeholder(
        self, api_env: ApiEnv
    ) -> None:
        await self._preset(api_env)

        project = await api_env.create_project()

        assert list(self._style_files(api_env, project["id"])) == ["style/STYLE.md"]
        assert "style_preset_id" not in project["settings"]

    async def test_later_edits_and_deletion_do_not_change_existing_projects(
        self, api_env: ApiEnv
    ) -> None:
        preset = await self._preset(api_env)
        project = (
            await api_env.client.post(
                "/api/projects", json={"title": "P", "style_preset_id": preset["id"]}
            )
        ).json()
        before = self._style_files(api_env, project["id"])

        draft = f"/api/styles/{preset['id']}/draft"
        await api_env.client.post(draft)
        await api_env.client.put(
            f"{draft}/files/references/color-scheme.md", json={"content": "改了"}
        )
        await api_env.client.post(f"{draft}/save")
        await api_env.client.delete(f"/api/styles/{preset['id']}")

        assert self._style_files(api_env, project["id"]) == before

    async def test_deleted_default_style_falls_back_to_the_placeholder(
        self, api_env: ApiEnv
    ) -> None:
        default = await self._preset(api_env, name="默认")
        await api_env.client.patch("/api/settings", json={"default_style_preset_id": default["id"]})
        await api_env.client.delete(f"/api/styles/{default['id']}")

        project = (await api_env.client.post("/api/projects", json={"title": "P"})).json()

        assert list(self._style_files(api_env, project["id"])) == ["style/STYLE.md"]
        assert "style_preset_id" not in project["settings"]

    async def test_a_broken_default_style_falls_back_to_the_placeholder(
        self, api_env: ApiEnv
    ) -> None:
        """默认风格目录被手工弄坏（没有 STYLE.md）：创建项目不能 500（评审 I4）。"""
        default = await self._preset(api_env, name="默认")
        await api_env.client.patch("/api/settings", json={"default_style_preset_id": default["id"]})
        (style_dir(api_env.data_dir, default["id"]) / "STYLE.md").unlink()

        response = await api_env.client.post("/api/projects", json={"title": "P"})

        assert response.status_code == 201
        project = response.json()
        assert list(self._style_files(api_env, project["id"])) == ["style/STYLE.md"]
        assert "style_preset_id" not in project["settings"]

    async def test_a_broken_requested_style_is_404_not_500(self, api_env: ApiEnv) -> None:
        preset = await self._preset(api_env)
        (style_dir(api_env.data_dir, preset["id"]) / "STYLE.md").unlink()

        response = await api_env.client.post(
            "/api/projects", json={"title": "P", "style_preset_id": preset["id"]}
        )

        assert response.status_code == 404
        assert "风格不存在" in assert_detail(response)

    async def test_unknown_preset_is_404_and_leaves_nothing(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post(
            "/api/projects", json={"title": "P", "style_preset_id": "missing"}
        )

        assert response.status_code == 404
        assert "风格不存在" in assert_detail(response)
        assert (await api_env.client.get("/api/projects")).json() == []
        projects_dir = api_env.data_dir / "projects"
        assert not projects_dir.exists() or list(projects_dir.iterdir()) == []

    async def test_style_can_be_combined_with_an_idea(self, api_env: ApiEnv) -> None:
        preset = await self._preset(api_env)
        idea = (await api_env.client.post("/api/ideas", json={"title": "排序为什么这么快"})).json()

        response = await api_env.client.post(
            "/api/projects",
            json={"title": "P", "idea_id": idea["id"], "style_preset_id": preset["id"]},
        )

        assert response.status_code == 201, response.text
        project = response.json()
        files_in_workspace = files.list_tree(api_env.workdir(project["id"]))
        assert "topic/notes/idea-card.md" in files_in_workspace
        assert "style/references/color-scheme.md" in files_in_workspace

    async def test_client_cannot_forge_the_recorded_style(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post(
            "/api/projects",
            json={"title": "P", "settings": {"style_name": "伪造", "style_preset_id": "x"}},
        )

        assert response.status_code == 201
        assert "style_name" not in response.json()["settings"]
        assert "style_preset_id" not in response.json()["settings"]


class TestProjectEffortSetting:
    async def test_create_accepts_effort(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post(
            "/api/projects", json={"title": "P", "settings": {"effort": "low"}}
        )

        assert response.status_code == 201, response.text
        assert response.json()["settings"]["effort"] == "low"

    async def test_create_rejects_unknown_effort(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post(
            "/api/projects", json={"title": "P", "settings": {"effort": "max"}}
        )

        assert response.status_code == 422
        assert "effort" in response.text

    async def test_patch_sets_and_clears_effort(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()
        url = f"/api/projects/{project['id']}/settings"

        response = await api_env.client.patch(url, json={"effort": "high"})
        assert response.status_code == 200, response.text
        assert response.json()["settings"]["effort"] == "high"

        response = await api_env.client.patch(url, json={"effort": None})
        assert "effort" not in response.json()["settings"]

    async def test_patch_rejects_unknown_effort(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()

        response = await api_env.client.patch(
            f"/api/projects/{project['id']}/settings", json={"effort": "max"}
        )

        assert response.status_code == 422


class TestProjectVoiceSettings:
    async def _patch(self, api_env: ApiEnv, project_id: str, body: dict) -> Response:
        return await api_env.client.patch(f"/api/projects/{project_id}/settings", json=body)

    async def test_sets_voice_and_speech_rate_using_the_keys_synthesize_tts_reads(
        self, api_env: ApiEnv
    ) -> None:
        project = await api_env.create_project()

        response = await self._patch(
            api_env, project["id"], {"voice": "xiaohe", "speech_rate": 1.3}
        )

        assert response.status_code == 200, response.text
        assert response.json()["settings"]["voice"] == "xiaohe"
        assert response.json()["settings"]["speech_rate"] == 1.3
        stored = get_project(api_env.app.state.engine, project["id"])
        assert stored is not None
        assert (stored.settings["voice"], stored.settings["speech_rate"]) == ("xiaohe", 1.3)

    async def test_merges_with_existing_settings_and_partial_updates_keep_the_rest(
        self, api_env: ApiEnv
    ) -> None:
        preset = {
            "id": style_store.import_style(
                api_env.data_dir, {"STYLE.md": "---\nname: S\ndescription: d\n---\n"}
            ).id
        }
        project = (
            await api_env.client.post(
                "/api/projects", json={"title": "P", "style_preset_id": preset["id"]}
            )
        ).json()
        await self._patch(api_env, project["id"], {"voice": "xiaohe", "speech_rate": 1.3})

        response = await self._patch(api_env, project["id"], {"speech_rate": 0.9})

        settings = response.json()["settings"]
        assert settings["style_name"] == "S"
        assert (settings["voice"], settings["speech_rate"]) == ("xiaohe", 0.9)

    async def test_null_clears_a_key(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()
        await self._patch(api_env, project["id"], {"voice": "xiaohe", "speech_rate": 1.3})

        response = await self._patch(api_env, project["id"], {"voice": None})

        settings = response.json()["settings"]
        assert "voice" not in settings
        assert settings["speech_rate"] == 1.3

    @pytest.mark.parametrize(
        ("body", "needle"),
        [
            ({"voice": "not-a-voice"}, "音色"),
            ({"speech_rate": 0.2}, "语速"),
            ({"speech_rate": 3}, "语速"),
            ({"speech_rate": "fast"}, "speech_rate"),
            ({"style_name": "x"}, "style_name"),
            ({"anything": 1}, "anything"),
        ],
    )
    async def test_invalid_or_unsupported_keys_are_422_and_change_nothing(
        self, api_env: ApiEnv, body: dict, needle: str
    ) -> None:
        project = await api_env.create_project()

        response = await self._patch(api_env, project["id"], {"voice": "xiaohe", **body})

        assert response.status_code == 422
        assert needle in str(response.json()["detail"])
        stored = get_project(api_env.app.state.engine, project["id"])
        assert stored is not None and "voice" not in stored.settings

    async def test_unknown_project_is_404(self, api_env: ApiEnv) -> None:
        response = await self._patch(api_env, "nope", {"voice": "zizi"})

        assert response.status_code == 404

    async def test_busy_project_is_409(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()
        turn_id = await api_env.make_busy(project["id"])
        try:
            response = await self._patch(api_env, project["id"], {"voice": "xiaohe"})

            assert response.status_code == 409
        finally:
            await api_env.release_busy(turn_id)

    async def test_new_projects_copy_the_default_voice_and_rate_from_settings(
        self, api_env: ApiEnv
    ) -> None:
        await api_env.client.patch(
            "/api/settings", json={"tts_default": {"voice": "xiaohe", "speech_rate": 1.2}}
        )

        project = await api_env.create_project()

        assert project["settings"]["voice"] == "xiaohe"
        assert project["settings"]["speech_rate"] == 1.2

    async def test_a_later_change_of_the_default_does_not_touch_existing_projects(
        self, api_env: ApiEnv
    ) -> None:
        await api_env.client.patch("/api/settings", json={"tts_default": {"voice": "xiaohe"}})
        project = await api_env.create_project()

        await api_env.client.patch("/api/settings", json={"tts_default": {"voice": "yunzhou"}})

        stored = get_project(api_env.app.state.engine, project["id"])
        assert stored is not None and stored.settings["voice"] == "xiaohe"

    async def test_explicit_values_at_creation_beat_the_defaults(self, api_env: ApiEnv) -> None:
        await api_env.client.patch(
            "/api/settings", json={"tts_default": {"voice": "xiaohe", "speech_rate": 1.2}}
        )

        response = await api_env.client.post(
            "/api/projects", json={"title": "P", "settings": {"voice": "yunzhou"}}
        )

        settings = response.json()["settings"]
        assert (settings["voice"], settings["speech_rate"]) == ("yunzhou", 1.2)

    async def test_without_stored_defaults_the_keys_are_absent(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()

        assert "voice" not in project["settings"] and "speech_rate" not in project["settings"]


class TestProjectStatus:
    async def test_new_project_is_active(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()
        assert project["status"] == "active"
        assert project["completed_at"] is None and project["abandoned_at"] is None

    async def test_can_mark_completed_abandoned_and_back_to_active(self, api_env: ApiEnv) -> None:
        pid = (await api_env.create_project())["id"]

        for status in ("completed", "abandoned", "active"):
            response = await api_env.client.patch(
                f"/api/projects/{pid}/status", json={"status": status}
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["status"] == status
            assert (body["completed_at"] is not None) == (status == "completed")
            assert (body["abandoned_at"] is not None) == (status == "abandoned")

        detail = (await api_env.client.get(f"/api/projects/{pid}")).json()
        assert detail["status"] == "active"

    async def test_unknown_status_is_422(self, api_env: ApiEnv) -> None:
        pid = (await api_env.create_project())["id"]
        response = await api_env.client.patch(f"/api/projects/{pid}/status", json={"status": "x"})
        assert response.status_code == 422

    async def test_unknown_project_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.patch(
            "/api/projects/nope/status", json={"status": "completed"}
        )
        assert response.status_code == 404

    async def test_status_can_change_while_a_turn_is_running(self, api_env: ApiEnv) -> None:
        """状态只是项目标记，不碰工作区，所以不受项目级串行限制。"""
        pid = (await api_env.create_project())["id"]
        turn_id = await api_env.make_busy(pid)
        try:
            response = await api_env.client.patch(
                f"/api/projects/{pid}/status", json={"status": "abandoned"}
            )
            assert response.status_code == 200
        finally:
            await api_env.release_busy(turn_id)


class TestDelete:
    async def test_removes_workspace_and_every_related_row(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()
        pid = project["id"]
        engine = api_env.app.state.engine
        profile = get_model_profile(engine, "fake")
        assert profile is not None
        session = create_session(
            engine, project_id=pid, stage="topic", model_profile_id=profile.id, runtime="fake"
        )
        turn = create_turn_if_session_idle(engine, session.id, "你好")
        assert turn is not None
        append_event(
            engine, turn_id=turn.id, session_id=session.id, type="text", payload={"text": "hi"}
        )
        assert list_events(engine, session.id)
        suggestion = create_suggestion(
            engine, project_id=pid, from_stage="narrative", to_stage="topic", content="改选题"
        )
        job = create_job(engine, type="render", project_id=pid)
        claim_next(engine, type="render")
        complete(engine, job.id, result={})
        other = await api_env.create_project("另一个")
        other_job = create_job(engine, type="render", project_id=other["id"])
        assert api_env.workdir(pid).exists()

        response = await api_env.client.delete(f"/api/projects/{pid}")
        assert response.status_code == 204

        assert not api_env.workdir(pid).exists()
        assert get_project(engine, pid) is None
        assert list_stages(engine, pid) == []
        assert list_snapshots(engine, pid) == []
        assert get_session(engine, session.id) is None
        assert list_turns(engine, session.id) == []
        assert list_events(engine, session.id) == []
        assert get_suggestion(engine, suggestion.id) is None
        assert get_job(engine, job.id) is None
        # 别的项目不受影响。
        assert get_job(engine, other_job.id) is not None
        assert get_project(engine, other["id"]) is not None
        assert api_env.workdir(other["id"]).exists()
        assert (await api_env.client.get(f"/api/projects/{pid}")).status_code == 404

    async def test_unknown_project_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.delete("/api/projects/nope")
        assert response.status_code == 404

    async def test_linked_idea_stays_and_can_be_used_again(self, api_env: ApiEnv) -> None:
        idea = (await api_env.client.post("/api/ideas", json={"title": "选题"})).json()
        created = await api_env.client.post(
            "/api/projects", json={"title": "项目", "idea_id": idea["id"]}
        )
        pid = created.json()["id"]
        await api_env.client.delete(f"/api/projects/{pid}")
        assert (await api_env.client.get(f"/api/ideas/{idea['id']}")).json()["status"] == "idea"

    async def test_running_turn_blocks_delete(self, api_env: ApiEnv) -> None:
        pid = (await api_env.create_project())["id"]
        turn_id = await api_env.make_busy(pid)
        try:
            response = await api_env.client.delete(f"/api/projects/{pid}")
            assert response.status_code == 409
            assert "运行" in assert_detail(response)
            assert api_env.workdir(pid).exists()
        finally:
            await api_env.release_busy(turn_id)

    @pytest.mark.parametrize("job_status", ["queued", "running"])
    async def test_unfinished_job_blocks_delete(self, api_env: ApiEnv, job_status: str) -> None:
        pid = (await api_env.create_project())["id"]
        engine = api_env.app.state.engine
        job = create_job(engine, type="render", project_id=pid)
        if job_status == "running":
            claimed = claim_next(engine, type="render")
            assert claimed is not None and claimed.id == job.id

        response = await api_env.client.delete(f"/api/projects/{pid}")
        assert response.status_code == 409
        assert get_project(engine, pid) is not None

    async def test_finished_job_does_not_block_delete(self, api_env: ApiEnv) -> None:
        pid = (await api_env.create_project())["id"]
        engine = api_env.app.state.engine
        job = create_job(engine, type="render", project_id=pid)
        claim_next(engine, type="render")
        complete(engine, job.id, result={})

        response = await api_env.client.delete(f"/api/projects/{pid}")
        assert response.status_code == 204
