"""`sessions` 仓储的 `list_sessions`（任务简报 T8：会话列表接口用它取数据）。"""

from __future__ import annotations

from sqlalchemy import Engine

from studio.db.repo.sessions import (
    SessionValue,
    create_session,
    delete_subject_sessions,
    get_session,
    list_sessions,
)
from studio.db.repo.turns import append_event, create_turn_if_session_idle, list_turns


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


class TestSubjectId:
    """会话可以属于一套风格（`subject_id`，ADR 0019）：同一风格内只有一个活动会话。"""

    def _style_session(self, engine: Engine, subject_id: str | None) -> SessionValue:
        return create_session(
            engine,
            project_id=None,
            stage="style",
            model_profile_id="m1",
            runtime="fake",
            subject_id=subject_id,
        )

    def test_subject_id_round_trips(self, migrated_engine: Engine) -> None:
        created = self._style_session(migrated_engine, "s1")

        assert created.subject_id == "s1"
        fetched = get_session(migrated_engine, created.id)
        assert fetched is not None and fetched.subject_id == "s1"

    def test_other_sessions_have_no_subject(self, migrated_engine: Engine) -> None:
        brainstorm = create_session(
            migrated_engine,
            project_id=None,
            stage="brainstorm",
            model_profile_id="m1",
            runtime="fake",
        )
        assert brainstorm.subject_id is None

    def test_a_new_session_deactivates_only_the_same_styles_older_ones(
        self, migrated_engine: Engine
    ) -> None:
        old = self._style_session(migrated_engine, "s1")
        other_style = self._style_session(migrated_engine, "s2")
        brainstorm = create_session(
            migrated_engine,
            project_id=None,
            stage="brainstorm",
            model_profile_id="m1",
            runtime="fake",
        )

        new = self._style_session(migrated_engine, "s1")

        active = {
            s.id: s.is_active
            for s in (
                get_session(migrated_engine, i)
                for i in (old.id, new.id, other_style.id, brainstorm.id)
            )
            if s
        }
        assert active == {old.id: False, new.id: True, other_style.id: True, brainstorm.id: True}

    def test_list_sessions_filters_by_subject(self, migrated_engine: Engine) -> None:
        first = self._style_session(migrated_engine, "s1")
        second = self._style_session(migrated_engine, "s1")
        self._style_session(migrated_engine, "s2")

        result = list_sessions(migrated_engine, None, "style", subject_id="s1")

        assert [s.id for s in result] == [first.id, second.id]
        assert list_sessions(migrated_engine, None, "style", subject_id="none-such") == []

    def test_a_listing_without_subject_does_not_include_style_sessions(
        self, migrated_engine: Engine
    ) -> None:
        self._style_session(migrated_engine, "s1")
        assert list_sessions(migrated_engine, None, "style") == []

    def test_delete_subject_sessions_removes_sessions_turns_and_events_of_that_style_only(
        self, migrated_engine: Engine
    ) -> None:
        doomed = self._style_session(migrated_engine, "s1")
        kept = self._style_session(migrated_engine, "s2")
        for session in (doomed, kept):
            turn = create_turn_if_session_idle(migrated_engine, session.id, "hi")
            assert turn is not None
            append_event(
                migrated_engine,
                turn_id=turn.id,
                session_id=session.id,
                type="text",
                payload={"text": "x"},
            )

        delete_subject_sessions(migrated_engine, "s1")

        assert get_session(migrated_engine, doomed.id) is None
        assert list_turns(migrated_engine, doomed.id) == []
        assert get_session(migrated_engine, kept.id) is not None
        assert len(list_turns(migrated_engine, kept.id)) == 1

    def test_delete_subject_sessions_is_a_no_op_without_sessions(
        self, migrated_engine: Engine
    ) -> None:
        delete_subject_sessions(migrated_engine, "nothing")
