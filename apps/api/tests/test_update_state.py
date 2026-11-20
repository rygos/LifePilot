from pathlib import Path

from lifepilot import update_state
from lifepilot.config import settings


def test_successful_startup_promotes_the_requested_commit(tmp_path: Path, monkeypatch) -> None:
    target_commit = "c" * 40
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(update_state, "image_commit_sha", lambda: target_commit)
    update_state.write_update_state(update_state.UpdateState(current_commit="a" * 40, pending_commit=target_commit))

    update_state.complete_pending_update()

    state = update_state.read_update_state()
    assert state.current_commit == target_commit
    assert state.pending_commit is None


def test_successful_startup_uses_requested_commit_when_build_marker_is_stale(tmp_path: Path, monkeypatch) -> None:
    target_commit = "c" * 40
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(update_state, "image_commit_sha", lambda: "b" * 40)
    update_state.write_update_state(update_state.UpdateState(current_commit="a" * 40, pending_commit=target_commit))

    update_state.complete_pending_update()

    state = update_state.read_update_state()
    assert state.current_commit == target_commit
    assert state.pending_commit is None
