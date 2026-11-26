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
