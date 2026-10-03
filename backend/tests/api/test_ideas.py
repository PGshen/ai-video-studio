"""`/api/ideas` 接口测试（计划 M4 T2）。"""

from __future__ import annotations

from .conftest import ApiEnv


async def _create(api_env: ApiEnv, **body: object) -> dict:
    payload = {"title": "标题", **body}
    response = await api_env.client.post("/api/ideas", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


class TestCreateAndList:
    async def test_create_returns_full_card(self, api_env: ApiEnv) -> None:
        body = await _create(
            api_env,
            title="排序为什么快",
            pitch="卖点",
            counterintuitive="反直觉",
            tags=["算法"],
            scores={"novelty": 4},
        )
        assert body["status"] == "idea"
        assert body["tags"] == ["算法"]
        assert body["scores"] == {"novelty": 4}
        assert body["id"]

    async def test_list_default_hides_archived_and_is_newest_first(self, api_env: ApiEnv) -> None:
        a = await _create(api_env, title="A")
        b = await _create(api_env, title="B")
        await api_env.client.patch(f"/api/ideas/{a['id']}", json={"status": "archived"})

        response = await api_env.client.get("/api/ideas")
        assert [i["id"] for i in response.json()] == [b["id"]]

        archived = await api_env.client.get("/api/ideas", params={"status": "archived"})
        assert [i["id"] for i in archived.json()] == [a["id"]]
        everything = await api_env.client.get("/api/ideas", params={"status": "all"})
        assert [i["id"] for i in everything.json()] == [b["id"], a["id"]]

    async def test_list_rejects_unknown_status(self, api_env: ApiEnv) -> None:
        response = await api_env.client.get("/api/ideas", params={"status": "weird"})
        assert response.status_code == 422

    async def test_duplicate_title_is_409_and_names_existing(self, api_env: ApiEnv) -> None:
        first = await _create(api_env, title="Hello World")
        response = await api_env.client.post("/api/ideas", json={"title": " hello  world"})
        assert response.status_code == 409
        assert first["id"] in response.json()["detail"]

    async def test_invalid_scores_and_blank_title_are_422(self, api_env: ApiEnv) -> None:
        bad_score = await api_env.client.post(
            "/api/ideas", json={"title": "x", "scores": {"novelty": 9}}
        )
        assert bad_score.status_code == 422
        bad_key = await api_env.client.post(
            "/api/ideas", json={"title": "x", "scores": {"boring": 3}}
        )
        assert bad_key.status_code == 422
        blank = await api_env.client.post("/api/ideas", json={"title": "  "})
        assert blank.status_code == 422
        missing = await api_env.client.post("/api/ideas", json={})
        assert missing.status_code == 422


class TestUpdate:
    async def test_patch_updates_only_provided_fields(self, api_env: ApiEnv) -> None:
        idea = await _create(api_env, pitch="旧", tags=["x"])
        response = await api_env.client.patch(f"/api/ideas/{idea['id']}", json={"pitch": "新"})
        assert response.status_code == 200
        body = response.json()
        assert body["pitch"] == "新"
        assert body["tags"] == ["x"]

    async def test_patch_null_clears_text(self, api_env: ApiEnv) -> None:
        idea = await _create(api_env, pitch="旧")
        response = await api_env.client.patch(f"/api/ideas/{idea['id']}", json={"pitch": None})
        assert response.json()["pitch"] is None

    async def test_archive_and_restore(self, api_env: ApiEnv) -> None:
        idea = await _create(api_env)
        archived = await api_env.client.patch(
            f"/api/ideas/{idea['id']}", json={"status": "archived"}
        )
        assert archived.json()["status"] == "archived"
        restored = await api_env.client.patch(f"/api/ideas/{idea['id']}", json={"status": "idea"})
        assert restored.json()["status"] == "idea"

    async def test_cannot_set_unknown_status(self, api_env: ApiEnv) -> None:
        idea = await _create(api_env)
        response = await api_env.client.patch(f"/api/ideas/{idea['id']}", json={"status": "picked"})
        assert response.status_code == 422

    async def test_unknown_id_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.patch("/api/ideas/nope", json={"pitch": "x"})
        assert response.status_code == 404

    async def test_rename_to_duplicate_is_409(self, api_env: ApiEnv) -> None:
        await _create(api_env, title="A")
        b = await _create(api_env, title="B")
        response = await api_env.client.patch(f"/api/ideas/{b['id']}", json={"title": "a"})
        assert response.status_code == 409


class TestGet:
    async def test_get_one(self, api_env: ApiEnv) -> None:
        idea = await _create(api_env)
        response = await api_env.client.get(f"/api/ideas/{idea['id']}")
        assert response.status_code == 200
        assert response.json()["id"] == idea["id"]
        assert (await api_env.client.get("/api/ideas/nope")).status_code == 404
