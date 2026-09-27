"""`sessions` 仓储的 `list_sessions`（任务简报 T8：会话列表接口用它取数据）。"""

from __future__ import annotations

from sqlalchemy import Engine

from studio.db.repo.sessions import create_session, list_sessions


class TestListSessions:
    def test_lists_only_sessions_of_given_project_and_stage(self, migrated_engine: Engine) -> None:
        first = create_session(
            migrated_engine, project_id="p1", stage="topic", model_profile_id="m1", runtime="fake"
        )
        second = create_session(
            migrated_engine, project_id="p1", stage="topic", model_profile_id="m1", runtime="fake"
        )
        create_session(
            migrated_engine,
            project_id="p1",
            stage="narrative",
            model_profile_id="m1",
            runtime="fake",
        )
        create_session(
            migrated_engine, project_id="p2", stage="topic", model_profile_id="m1", runtime="fake"
        )

        result = list_sessions(migrated_engine, "p1", "topic")

        assert [s.id for s in result] == [first.id, second.id]

    def test_empty_when_no_sessions_match(self, migrated_engine: Engine) -> None:
        assert list_sessions(migrated_engine, "does-not-exist", "topic") == []
