from __future__ import annotations

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from studio.db.repo.sessions import create_session, get_session
from studio.db.repo.turns import (
    append_event,
    create_turn_if_session_idle,
    finish_turn,
    get_turn,
    interrupt_turn,
    latest_turn,
    list_events,
    list_unfinished_turns,
    mark_turn_running,
    previous_turn,
)


def _session(engine: Engine, stage: str = "topic") -> str:
    return create_session(
        engine, project_id="p1", stage=stage, model_profile_id="m1", runtime="fake"
    ).id


class TestSessions:
    def test_new_session_is_active_and_deactivates_others_of_same_stage(
        self, migrated_engine: Engine
    ) -> None:
        first = _session(migrated_engine)
        other_stage = _session(migrated_engine, stage="narrative")
        second = _session(migrated_engine)

        first_value = get_session(migrated_engine, first)
        second_value = get_session(migrated_engine, second)
        other_value = get_session(migrated_engine, other_stage)
        assert first_value is not None and second_value is not None and other_value is not None
        assert first_value.is_active is False
        assert second_value.is_active is True
        assert other_value.is_active is True
        assert second_value.status == "idle"


class TestTurnLifecycle:
    def test_second_turn_rejected_while_first_queued_or_running(
        self, migrated_engine: Engine
    ) -> None:
        session_id = _session(migrated_engine)
        first = create_turn_if_session_idle(migrated_engine, session_id, "hi")
        assert first is not None and first.status == "queued"

        assert create_turn_if_session_idle(migrated_engine, session_id, "again") is None
        mark_turn_running(migrated_engine, first.id, start_snapshot_id="s0")
        assert create_turn_if_session_idle(migrated_engine, session_id, "again") is None

    def test_running_then_finish_updates_turn_and_session(self, migrated_engine: Engine) -> None:
        session_id = _session(migrated_engine)
        turn = create_turn_if_session_idle(migrated_engine, session_id, "hi")
        assert turn is not None

        mark_turn_running(migrated_engine, turn.id, start_snapshot_id="s0")
        running_session = get_session(migrated_engine, session_id)
        assert running_session is not None and running_session.status == "running"

        finish_turn(
            migrated_engine,
            turn.id,
            status="done",
            end_snapshot_id="s1",
            usage={"input_tokens": 1},
            cost_usd=0.5,
            error=None,
            resume_ref="ref-1",
        )
        done = get_turn(migrated_engine, turn.id)
        session = get_session(migrated_engine, session_id)
        assert done is not None and session is not None
        assert (done.status, done.start_snapshot_id, done.end_snapshot_id) == ("done", "s0", "s1")
        assert done.usage == {"input_tokens": 1}
        assert done.cost_usd == 0.5
        assert (session.status, session.sdk_ref) == ("idle", "ref-1")

        # resume_ref=None keeps the previous sdk_ref
        turn2 = create_turn_if_session_idle(migrated_engine, session_id, "next")
        assert turn2 is not None
        finish_turn(
            migrated_engine,
            turn2.id,
            status="failed",
            end_snapshot_id=None,
            usage=None,
            cost_usd=None,
            error="boom",
            resume_ref=None,
        )
        session = get_session(migrated_engine, session_id)
        assert session is not None and session.sdk_ref == "ref-1"

    def test_previous_turn_skips_current_and_unfinished(self, migrated_engine: Engine) -> None:
        session_id = _session(migrated_engine)
        first = create_turn_if_session_idle(migrated_engine, session_id, "1")
        assert first is not None
        assert previous_turn(migrated_engine, session_id, first.id) is None
        mark_turn_running(migrated_engine, first.id, start_snapshot_id="s0")
        finish_turn(
            migrated_engine,
            first.id,
            status="done",
            end_snapshot_id="s1",
            usage=None,
            cost_usd=None,
            error=None,
            resume_ref=None,
        )
        second = create_turn_if_session_idle(migrated_engine, session_id, "2")
        assert second is not None

        prev = previous_turn(migrated_engine, session_id, second.id)
        assert prev is not None and prev.id == first.id

        # a queued turn cancelled before it started is skipped
        finish_turn(
            migrated_engine,
            second.id,
            status="cancelled",
            end_snapshot_id=None,
            usage=None,
            cost_usd=None,
            error=None,
            resume_ref=None,
        )
        third = create_turn_if_session_idle(migrated_engine, session_id, "3")
        assert third is not None
        prev = previous_turn(migrated_engine, session_id, third.id)
        assert prev is not None and prev.id == first.id

    def test_interrupt_unfinished(self, migrated_engine: Engine) -> None:
        session_id = _session(migrated_engine)
        turn = create_turn_if_session_idle(migrated_engine, session_id, "1")
        assert turn is not None
        mark_turn_running(migrated_engine, turn.id, start_snapshot_id="s0")

        unfinished = list_unfinished_turns(migrated_engine)
        assert [t.id for t in unfinished] == [turn.id]

        interrupt_turn(migrated_engine, turn.id, end_snapshot_id="s9")
        after = get_turn(migrated_engine, turn.id)
        session = get_session(migrated_engine, session_id)
        assert after is not None and session is not None
        assert (after.status, after.end_snapshot_id) == ("interrupted", "s9")
        assert session.status == "interrupted"
        assert list_unfinished_turns(migrated_engine) == []


class TestLatestTurn:
    def test_returns_none_when_session_has_no_turns(self, migrated_engine: Engine) -> None:
        session_id = _session(migrated_engine)
        assert latest_turn(migrated_engine, session_id) is None

    def test_returns_most_recently_created_turn(self, migrated_engine: Engine) -> None:
        session_id = _session(migrated_engine)
        first = create_turn_if_session_idle(migrated_engine, session_id, "hi")
        assert first is not None
        finish_turn(
            migrated_engine,
            first.id,
            status="done",
            end_snapshot_id="s1",
            usage=None,
            cost_usd=None,
            error=None,
            resume_ref=None,
        )
        second = create_turn_if_session_idle(migrated_engine, session_id, "again")
        assert second is not None

        latest = latest_turn(migrated_engine, session_id)
        assert latest is not None and latest.id == second.id


class TestEvents:
    def test_seq_is_monotonic_per_session_across_turns(self, migrated_engine: Engine) -> None:
        s1 = _session(migrated_engine)
        s2 = _session(migrated_engine, stage="narrative")

        seqs = [
            append_event(migrated_engine, turn_id="t1", session_id=s1, type="text", payload={}).seq
            for _ in range(3)
        ]
        other = append_event(migrated_engine, turn_id="t9", session_id=s2, type="text", payload={})
        seqs.append(
            append_event(migrated_engine, turn_id="t2", session_id=s1, type="text", payload={}).seq
        )

        assert seqs == [1, 2, 3, 4]
        assert other.seq == 1
        assert [e.seq for e in list_events(migrated_engine, s1, after_seq=2)] == [3, 4]

    def test_session_seq_pair_is_unique(self, migrated_engine: Engine) -> None:
        append_event(migrated_engine, turn_id="t1", session_id="s", type="text", payload={})
        with pytest.raises(IntegrityError), migrated_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO turn_events (id, turn_id, session_id, seq, type, payload,"
                    " created_at) VALUES ('x', 't1', 's', 1, 'text', '{}', '2026-01-01')"
                )
            )


class TestTurnAttachments:
    def test_attachments_default_to_empty(self, migrated_engine: Engine) -> None:
        sid = _session(migrated_engine)
        turn = create_turn_if_session_idle(migrated_engine, sid, "hi")
        assert turn is not None
        assert turn.attachments == []
        fetched = get_turn(migrated_engine, turn.id)
        assert fetched is not None and fetched.attachments == []

    def test_attachments_round_trip(self, migrated_engine: Engine) -> None:
        sid = _session(migrated_engine)
        records = [
            {"kind": "image", "name": "a.png", "size": 3, "sha256": "abc", "path": None},
            {"kind": "file", "name": "b.md", "size": 4, "sha256": None, "path": "uploads/x-b.md"},
        ]
        turn = create_turn_if_session_idle(migrated_engine, sid, "hi", attachments=records)
        assert turn is not None
        fetched = get_turn(migrated_engine, turn.id)
        assert fetched is not None and fetched.attachments == records
