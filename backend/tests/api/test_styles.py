"""`/api/style-presets`（计划 M5 T2）：风格库增删改查、复制、默认风格。"""

from __future__ import annotations

from typing import Any

from .conftest import ApiEnv, assert_detail

ENTRY = """---
name: 暖纸双色
description: 暖色纸张质感的双色风格
---

先读 `references/color-scheme.md`。
"""


def _body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "暖纸双色",
        "category": "概念传记",
        "content": ENTRY,
        "references": [{"name": "color-scheme.md", "text": "主色：暖白"}],
        "exemplars": [{"name": "exemplar-1.json", "text": "{}"}],
    }
    body.update(overrides)
    return body


async def _create(api_env: ApiEnv, **overrides: Any) -> dict[str, Any]:
    response = await api_env.client.post("/api/style-presets", json=_body(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


class TestCreateAndRead:
    async def test_create_returns_the_full_preset(self, api_env: ApiEnv) -> None:
        created = await _create(api_env)

        assert created["name"] == "暖纸双色"
        assert created["description"] == "暖色纸张质感的双色风格"
        assert created["content"] == ENTRY
        assert created["references"] == [{"name": "color-scheme.md", "text": "主色：暖白"}]
        assert created["exemplars"] == [{"name": "exemplar-1.json", "text": "{}"}]

        response = await api_env.client.get(f"/api/style-presets/{created['id']}")
        assert response.status_code == 200
        assert response.json() == created

    async def test_list_returns_summaries_without_file_contents(self, api_env: ApiEnv) -> None:
        created = await _create(api_env)

        response = await api_env.client.get("/api/style-presets")

        assert response.status_code == 200
        assert response.json() == [
            {
                "id": created["id"],
                "name": "暖纸双色",
                "category": "概念传记",
                "description": "暖色纸张质感的双色风格",
                "reference_count": 1,
                "exemplar_count": 1,
                "is_default": False,
            }
        ]

    async def test_invalid_preset_is_422_with_named_problems(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post(
            "/api/style-presets", json=_body(references=[], content="# 没有 frontmatter")
        )

        assert response.status_code == 422
        detail = assert_detail(response)
        assert "frontmatter" in detail
        listing = await api_env.client.get("/api/style-presets")
        assert listing.json() == []

    async def test_duplicate_name_is_409(self, api_env: ApiEnv) -> None:
        await _create(api_env)

        response = await api_env.client.post("/api/style-presets", json=_body())

        assert response.status_code == 409

    async def test_unknown_id_is_404(self, api_env: ApiEnv) -> None:
        client = api_env.client
        assert (await client.get("/api/style-presets/nope")).status_code == 404
        assert (
            await client.patch("/api/style-presets/nope", json={"category": "x"})
        ).status_code == 404
        assert (await client.delete("/api/style-presets/nope")).status_code == 404
        assert (await client.post("/api/style-presets/nope/duplicate")).status_code == 404


class TestUpdate:
    async def test_patch_changes_only_given_fields(self, api_env: ApiEnv) -> None:
        created = await _create(api_env)

        response = await api_env.client.patch(
            f"/api/style-presets/{created['id']}", json={"category": "新分类"}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["category"] == "新分类"
        assert body["content"] == ENTRY
        assert body["references"] == created["references"]

    async def test_patch_that_breaks_the_entry_is_422_and_changes_nothing(
        self, api_env: ApiEnv
    ) -> None:
        created = await _create(api_env)

        response = await api_env.client.patch(
            f"/api/style-presets/{created['id']}", json={"references": []}
        )

        assert response.status_code == 422
        assert "references/color-scheme.md" in assert_detail(response)
        got = await api_env.client.get(f"/api/style-presets/{created['id']}")
        assert got.json()["references"] == created["references"]

    async def test_unknown_fields_are_rejected(self, api_env: ApiEnv) -> None:
        created = await _create(api_env)

        response = await api_env.client.patch(
            f"/api/style-presets/{created['id']}", json={"nope": 1}
        )

        assert response.status_code == 422


class TestDuplicate:
    async def test_duplicate_creates_an_independent_copy(self, api_env: ApiEnv) -> None:
        created = await _create(api_env)

        response = await api_env.client.post(f"/api/style-presets/{created['id']}/duplicate")

        assert response.status_code == 201
        copy = response.json()
        assert copy["id"] != created["id"]
        assert copy["name"] == "暖纸双色（副本）"
        assert copy["references"] == created["references"]


class TestDefaultStyle:
    async def test_default_is_flagged_in_the_list(self, api_env: ApiEnv) -> None:
        first = await _create(api_env)
        await _create(api_env, name="另一套")

        response = await api_env.client.patch(
            "/api/settings", json={"default_style_preset_id": first["id"]}
        )
        assert response.status_code == 200
        assert response.json()["default_style_preset_id"] == first["id"]

        listing = await api_env.client.get("/api/style-presets")
        flags = {p["name"]: p["is_default"] for p in listing.json()}
        assert flags == {"暖纸双色": True, "另一套": False}

    async def test_default_must_exist(self, api_env: ApiEnv) -> None:
        response = await api_env.client.patch(
            "/api/settings", json={"default_style_preset_id": "missing"}
        )

        assert response.status_code == 422
        assert "风格不存在" in assert_detail(response)
        settings = await api_env.client.get("/api/settings")
        assert settings.json()["default_style_preset_id"] is None

    async def test_deleting_the_default_clears_the_setting(self, api_env: ApiEnv) -> None:
        created = await _create(api_env)
        await api_env.client.patch("/api/settings", json={"default_style_preset_id": created["id"]})

        response = await api_env.client.delete(f"/api/style-presets/{created['id']}")

        assert response.status_code == 204
        settings = await api_env.client.get("/api/settings")
        assert settings.json()["default_style_preset_id"] is None

    async def test_deleting_another_preset_keeps_the_default(self, api_env: ApiEnv) -> None:
        default = await _create(api_env)
        other = await _create(api_env, name="另一套")
        await api_env.client.patch("/api/settings", json={"default_style_preset_id": default["id"]})

        await api_env.client.delete(f"/api/style-presets/{other['id']}")

        settings = await api_env.client.get("/api/settings")
        assert settings.json()["default_style_preset_id"] == default["id"]
