from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from lifepilot.config import settings


def test_planning_migrations_on_isolated_sqlite(tmp_path, monkeypatch):
    api = Path(__file__).resolve().parents[1]
    database_url = f"sqlite:///{tmp_path / 'migration-test.db'}"
    monkeypatch.setattr(settings, "database_url", database_url)
    config = Config(str(api / "alembic.ini"))
    command.upgrade(config, "0032_token_version")
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert {"commitments", "work_checkpoints", "focus_sessions", "task_steps", "focus_checkins", "routines", "routine_steps", "routine_completions", "capture_keys", "push_subscriptions", "dav_keys", "temporal_facts", "fact_conflict_decisions", "face_training_cards", "document_indexes", "document_pages", "decision_entries", "decision_reviews", "places", "place_entries", "inventory_items", "inventory_history", "inventory_loans", "trash_entries"}.issubset(inspector.get_table_names())
        assert "value_key" in {column["name"] for column in inspector.get_columns("temporal_facts")}
        assert "scope" in {column["name"] for column in inspector.get_columns("capture_keys")}
        assert "client_request_id" in {column["name"] for column in inspector.get_columns("captures")}
        assert {"companion_interval_minutes", "companion_goal"}.issubset({column["name"] for column in inspector.get_columns("focus_sessions")})
        assert {"source_capture_id", "source_quote"}.issubset({column["name"] for column in inspector.get_columns("commitments")})
        assert {"estimated_minutes", "mental_effort", "start_friction", "work_context", "next_step"}.issubset(
            {column["name"] for column in inspector.get_columns("tasks")}
        )
        command.downgrade(config, "0032_token_version")
        inspector = inspect(engine)
        assert "trash_entries" not in inspector.get_table_names()
        assert not {"inventory_items", "inventory_history", "inventory_loans"}.intersection(inspector.get_table_names())
        assert not {"places", "place_entries"}.intersection(inspector.get_table_names())
        assert not {"decision_entries", "decision_reviews"}.intersection(inspector.get_table_names())
        assert not {"document_indexes", "document_pages"}.intersection(inspector.get_table_names())
        assert "face_training_cards" not in inspector.get_table_names()
        assert "fact_conflict_decisions" not in inspector.get_table_names()
        assert "temporal_facts" not in inspector.get_table_names()
        assert "dav_keys" not in inspector.get_table_names()
        assert "push_subscriptions" not in inspector.get_table_names()
        assert "capture_keys" not in inspector.get_table_names()
        assert "client_request_id" not in {column["name"] for column in inspector.get_columns("captures")}
        assert "commitments" not in inspector.get_table_names()
        assert "focus_sessions" not in inspector.get_table_names()
        assert "task_steps" not in inspector.get_table_names()
        assert "focus_checkins" not in inspector.get_table_names()
        assert not {"routines", "routine_steps", "routine_completions"}.intersection(inspector.get_table_names())
        assert "estimated_minutes" not in {column["name"] for column in inspector.get_columns("tasks")}
        command.upgrade(config, "head")
    finally:
        engine.dispose()
