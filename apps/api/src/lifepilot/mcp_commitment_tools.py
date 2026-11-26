from datetime import datetime
from mcp.server.fastmcp import FastMCP

from lifepilot.commitment_routes import (
    CheckpointIn, CheckpointOut, CommitmentIn, CommitmentOut, CommitmentStatus, Direction,
    create_checkpoint, create_commitment, list_checkpoints, list_commitments, owned, set_commitment_status,
)
from lifepilot.mcp_tools import mcp_session, mcp_user
from lifepilot.models import WorkCheckpoint
from lifepilot.next_action import Context, Effort, TaskPlanning, next_actions, set_planning
from lifepilot.schemas import TaskOut
from lifepilot.task_steps import StepOut, StepBatch, StepState, list_steps, draft_steps, add_steps, set_step_state
from lifepilot.focus_routes import FocusStart, FocusEnd, FocusOut, start_focus, end_focus, active_focus, focus_history, CheckInIn, companion_context, record_checkin


def register_commitment_tools(mcp: FastMCP) -> None:
    @mcp.tool(name="commitment_create")
    def commitment_create_mcp(title: str, direction: Direction, notes: str = "", person_id: str | None = None, project_id: str | None = None, conversation_id: str | None = None, due_at: datetime | None = None) -> dict:
        """Save a promise made by the user or an outstanding promise from another person."""
        owner = mcp_user("memory:write")
        with mcp_session(owner) as db:
            return CommitmentOut.model_validate(create_commitment(db, owner, CommitmentIn(title=title, direction=direction, notes=notes, person_id=person_id, project_id=project_id, conversation_id=conversation_id, due_at=due_at), "mcp")).model_dump(mode="json")

    @mcp.tool(name="commitment_list")
    def commitment_list_mcp(status: CommitmentStatus = "open", direction: Direction | None = None) -> list[dict]:
        owner = mcp_user()
        with mcp_session(owner) as db:
            return [CommitmentOut.model_validate(row).model_dump(mode="json") for row in list_commitments(db, owner, status, direction)]

    @mcp.tool(name="waiting_for_list")
    def waiting_for_list_mcp() -> list[dict]:
        owner = mcp_user()
        with mcp_session(owner) as db:
            return [CommitmentOut.model_validate(row).model_dump(mode="json") for row in list_commitments(db, owner, "open", "incoming")]

    @mcp.tool(name="commitment_set_status")
    def commitment_set_status_mcp(commitment_id: str, status: CommitmentStatus) -> dict:
        owner = mcp_user("memory:write")
        with mcp_session(owner) as db:
            return CommitmentOut.model_validate(set_commitment_status(db, owner, commitment_id, status, "mcp")).model_dump(mode="json")

    @mcp.tool(name="work_checkpoint_save")
    def work_checkpoint_save_mcp(title: str, next_step: str, progress: str = "", blocker: str = "", resources: str = "", task_id: str | None = None, project_id: str | None = None) -> dict:
        """Save an explicit work interruption and the next concrete step."""
        owner = mcp_user("memory:write")
        with mcp_session(owner) as db:
            return CheckpointOut.model_validate(create_checkpoint(db, owner, CheckpointIn(title=title, next_step=next_step, progress=progress, blocker=blocker, resources=resources, task_id=task_id, project_id=project_id), "mcp")).model_dump(mode="json")

    @mcp.tool(name="work_checkpoint_list")
    def work_checkpoint_list_mcp(archived: bool = False) -> list[dict]:
        owner = mcp_user()
        with mcp_session(owner) as db:
            return [CheckpointOut.model_validate(row).model_dump(mode="json") for row in list_checkpoints(db, owner, archived)]

    @mcp.tool(name="work_checkpoint_resume")
    def work_checkpoint_resume_mcp(checkpoint_id: str) -> dict:
        owner = mcp_user()
        with mcp_session(owner) as db:
            return CheckpointOut.model_validate(owned(db, WorkCheckpoint, owner, checkpoint_id)).model_dump(mode="json")

    @mcp.tool(name="next_best_action")
    def next_best_action_mcp(minutes: int = 15, energy: Effort = "medium", context: Context = "any") -> dict:
        """Find open tasks matching available time, energy and context; does not modify tasks."""
        if not 1 <= minutes <= 1440:
            raise ValueError("Zeit muss zwischen 1 und 1440 Minuten liegen")
        owner = mcp_user()
        with mcp_session(owner) as db:
            return next_actions(db, owner, minutes, energy, context).model_dump(mode="json")

    @mcp.tool(name="task_planning_update")
    def task_planning_update_mcp(task_id: str, planning: TaskPlanning) -> dict:
        owner = mcp_user("memory:write")
        with mcp_session(owner) as db:
            return TaskOut.model_validate(set_planning(db, owner, task_id, planning, "mcp")).model_dump(mode="json")

    @mcp.tool(name="focus_start")
    def focus_start_mcp(task_id: str, planned_minutes: int = 25, companion_interval_minutes: int | None = None, companion_goal: str = "") -> dict:
        owner = mcp_user("memory:write")
        with mcp_session(owner) as db:
            return FocusOut.model_validate(start_focus(db, owner, FocusStart(task_id=task_id, planned_minutes=planned_minutes, companion_interval_minutes=companion_interval_minutes, companion_goal=companion_goal), "mcp")).model_dump(mode="json")

    @mcp.tool(name="focus_active")
    def focus_active_mcp() -> dict | None:
        owner = mcp_user()
        with mcp_session(owner) as db:
            row = active_focus(db, owner)
            return FocusOut.model_validate(row).model_dump(mode="json") if row else None

    @mcp.tool(name="focus_end")
    def focus_end_mcp(session_id: str, data: FocusEnd) -> dict:
        owner = mcp_user("memory:write")
        with mcp_session(owner) as db:
            return FocusOut.model_validate(end_focus(db, owner, session_id, data, "mcp")).model_dump(mode="json")

    @mcp.tool(name="focus_history")
    def focus_history_mcp(task_id: str | None = None) -> list[dict]:
        owner = mcp_user()
        with mcp_session(owner) as db:
            return [FocusOut.model_validate(row).model_dump(mode="json") for row in focus_history(db, owner, task_id=task_id)]

    @mcp.tool(name="task_steps_list")
    def task_steps_list_mcp(task_id: str) -> list[dict]:
        owner = mcp_user()
        with mcp_session(owner) as db:
            return [StepOut.model_validate(row).model_dump(mode="json") for row in list_steps(db, owner, task_id)]

    @mcp.tool(name="task_steps_draft")
    def task_steps_draft_mcp(task_id: str) -> dict:
        """Generate a preview only. Do not save suggestions until the user approves."""
        owner = mcp_user()
        with mcp_session(owner) as db:
            return draft_steps(db, owner, task_id).model_dump(mode="json")

    @mcp.tool(name="task_steps_add")
    def task_steps_add_mcp(task_id: str, data: StepBatch, confirm: bool = False) -> list[dict]:
        """Save explicitly approved steps."""
        owner = mcp_user("memory:write")
        if not confirm:
            raise ValueError("Bitte die Schritte zuerst durch den Nutzer bestätigen lassen")
        with mcp_session(owner) as db:
            return [StepOut.model_validate(row).model_dump(mode="json") for row in add_steps(db, owner, task_id, data, "mcp")]

    @mcp.tool(name="task_step_set_state")
    def task_step_set_state_mcp(task_id: str, step_id: str, completed: bool) -> dict:
        owner = mcp_user("memory:write")
        with mcp_session(owner) as db:
            return StepOut.model_validate(set_step_state(db, owner, task_id, step_id, StepState(completed=completed), "mcp")).model_dump(mode="json")


    @mcp.tool(name="focus_companion")
    def focus_companion_mcp(session_id: str) -> dict:
        """Read the virtual work companion, upcoming check-in and recent self-reports."""
        owner = mcp_user()
        with mcp_session(owner) as db:
            return companion_context(db, owner, session_id).model_dump(mode="json")

    @mcp.tool(name="focus_checkin")
    def focus_checkin_mcp(session_id: str, data: CheckInIn) -> dict:
        """Record the user's explicit self-report; use a unique request UUID for each check-in."""
        owner = mcp_user("memory:write")
        with mcp_session(owner) as db:
            return record_checkin(db, owner, session_id, data, "mcp").model_dump(mode="json")
