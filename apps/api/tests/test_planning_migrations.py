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
        assert {"commitments", "work_checkpoints", "focus_sessions", "task_steps", "focus_checkins", "routines", "routine_steps", "routine_completions"}.issubset(inspector.get_table_names())
        assert "client_request_id" in {column["name"] for column in inspector.get_columns("captures")}
        assert {"companion_interval_minutes", "companion_goal"}.issubset({column["name"] for column in inspector.get_columns("focus_sessions")})
        assert {"source_capture_id", "source_quote"}.issubset({column["name"] for column in inspector.get_columns("commitments")})
        assert {"estimated_minutes", "mental_effort", "start_friction", "work_context", "next_step"}.issubset(
            {column["name"] for column in inspector.get_columns("tasks")}
        )
        command.downgrade(config, "0032_token_version")
        inspector = inspect(engine)
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
