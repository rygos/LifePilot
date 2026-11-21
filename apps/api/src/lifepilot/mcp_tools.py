from datetime import datetime
from typing import Literal
from fastapi import HTTPException
from sqlalchemy import Text, or_, select
from sqlalchemy.orm import Session
from lifepilot.audit import ACTOR_KEY
from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.embedding_jobs import enqueue_memory_embedding
from lifepilot.entity_embedding_jobs import enqueue_person_context_embeddings
from lifepilot.models import ApprovalRequest, Conversation, Gift, Loan, Memory, Person, Relationship, Task, User
from lifepilot.schemas import ConversationIn, ConversationOut, EventIn, GiftIn, GiftOut, LoanIn, LoanOut, MemoryOut, PersonIn, PersonOut, ProjectOut, RelationshipIn, RelationshipOut, TaskIn, TaskOut
from lifepilot.security import resolve_bearer_scopes, resolve_bearer_token_use, resolve_bearer_user
from lifepilot.services import owned_person, search
from lifepilot.relationship_language import refresh_relationship_labels
from lifepilot.main import conversation_create, conversation_list, daily_briefing, gift_create, gift_list, loan_create, loan_list, loan_return, person_briefing, person_get, relationship_add, relationship_list

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.server.auth.provider import AccessToken, TokenVerifier
    from mcp.server.auth.middleware.auth_context import get_access_token
    from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
    class LifePilotTokenVerifier(TokenVerifier):
        async def verify_token(self, token: str) -> AccessToken | None:
            with Session(engine) as db:
                try:
                    if resolve_bearer_token_use(token) != "mcp":
                        return None
                    user = resolve_bearer_user(token, db)
                    return AccessToken(token=token, client_id=user.id, scopes=resolve_bearer_scopes(token), resource="http://localhost/mcp/")
                except HTTPException:
                    return None
    mcp = FastMCP("LifePilot", token_verifier=LifePilotTokenVerifier(), auth=AuthSettings(issuer_url="http://localhost", resource_server_url="http://localhost/mcp/", required_scopes=["memory:read"], client_registration_options=ClientRegistrationOptions(enabled=False), revocation_options=RevocationOptions(enabled=False), validate_token_resource=False), stateless_http=True, json_response=True, streamable_http_path="/mcp")
    def mcp_user(required_scope: str = "memory:read"):
        token = get_access_token()
        if token is None: raise ValueError("Bearer token erforderlich")
        if required_scope not in token.scopes: raise ValueError(f"MCP-Token benötigt den Bereich {required_scope}")
        return token.client_id

    def mcp_session(owner_id: str) -> Session:
        session = Session(engine)
        session.info[ACTOR_KEY] = owner_id
        return session

    def request_approval(db: Session, owner_id: str, operation: str, resource_id: str, resource_label: str) -> dict:
        row = db.scalar(select(ApprovalRequest).where(ApprovalRequest.owner_id == owner_id, ApprovalRequest.operation == operation, ApprovalRequest.resource_id == resource_id, ApprovalRequest.status == "pending"))
        if row is not None:
            return {"approval_id": row.id, "operation": operation, "resource_id": resource_id, "status": row.status, "message": "Im LifePilot-Eingang durch den Benutzer freigeben"}
        row = ApprovalRequest(owner_id=owner_id, operation=operation, resource_id=resource_id, resource_label=resource_label)
        db.add(row)
        db.commit()
        db.refresh(row)
        return {"approval_id": row.id, "operation": operation, "resource_id": resource_id, "status": row.status, "message": "Im LifePilot-Eingang durch den Benutzer freigeben"}
    @mcp.tool()
    def person_create_tool(first_name: str, last_name: str = "", nickname: str | None = None, birthday: str | None = None, gender: Literal["female", "male", "diverse", "unspecified"] = "unspecified", email: str | None = None, phone: str | None = None, address: str = "", website: str | None = None, job_title: str | None = None, organization: str | None = None, how_met: str = "", tags: list[str] | None = None, is_favorite: bool = False, notes: str = "") -> dict:
        owner_id = mcp_user("memory:write")
        data = PersonIn(first_name=first_name, last_name=last_name, nickname=nickname, birthday=birthday, gender=gender, email=email, phone=phone, address=address, website=website, job_title=job_title, organization=organization, how_met=how_met, tags=tags or [], is_favorite=is_favorite, notes=notes)
        with mcp_session(owner_id) as db:
            row = Person(owner_id=owner_id, **data.model_dump(exclude_none=True)); db.add(row); db.commit(); db.refresh(row)
            return PersonOut.model_validate(row).model_dump(mode="json")
    @mcp.tool()
    def person_search_tool(query: str) -> list[dict]:
        owner_id = mcp_user(); term = f"%{query}%"
        with mcp_session(owner_id) as db:
            rows = db.scalars(select(Person).where(Person.owner_id == owner_id, or_(Person.first_name.ilike(term), Person.last_name.ilike(term), Person.nickname.ilike(term), Person.email.ilike(term), Person.phone.ilike(term), Person.organization.ilike(term), Person.job_title.ilike(term), Person.how_met.ilike(term), Person.tags.cast(Text).ilike(term), Person.notes.ilike(term)))).all()
            return [PersonOut.model_validate(r).model_dump(mode="json") for r in rows]
    @mcp.tool()
    def memory_capture_tool(title: str, content: str, person_id: str | None = None) -> dict:
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            user = db.get(User, owner_id); owned_person(db, person_id, user)
            row = Memory(owner_id=owner_id, person_id=person_id, title=title, content=content); db.add(row); db.commit(); db.refresh(row)
            enqueue_memory_embedding(row.id, owner_id)
            return MemoryOut.model_validate(row).model_dump(mode="json")
    @mcp.tool()
    def memory_search_tool(query: str) -> dict:
        owner_id = mcp_user()
        with mcp_session(owner_id) as db:
            user = db.get(User, owner_id); result = search(db, user, query)
            return {"people": [PersonOut.model_validate(x).model_dump(mode="json") for x in result["people"]], "memories": [MemoryOut.model_validate(x).model_dump(mode="json") for x in result["memories"]], "tasks": [TaskOut.model_validate(x).model_dump(mode="json") for x in result["tasks"]], "conversations": [ConversationOut.model_validate(x).model_dump(mode="json") for x in result["conversations"]], "loans": [LoanOut.model_validate(x).model_dump(mode="json") for x in result["loans"]], "gifts": [GiftOut.model_validate(x).model_dump(mode="json") for x in result["gifts"]], "relationships": [row.model_dump(mode="json") for row in result["relationships"]], "projects": [ProjectOut.model_validate(row).model_dump(mode="json") for row in result["projects"]], "life_events": [{"id": row.id, "person_id": row.person_id, "title": row.title, "details": row.details, "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None, "date_precision": row.date_precision, "source_capture_id": row.source_capture_id} for row in result["life_events"]], "search_info": result["search_info"]}

    @mcp.tool(name="person_get")
    def person_get_mcp(person_id: str) -> dict:
        owner_id = mcp_user()
        with mcp_session(owner_id) as db:
            return PersonOut.model_validate(person_get(person_id, db, db.get(User, owner_id))).model_dump(mode="json")

    @mcp.tool(name="person_update")
    def person_update_mcp(person_id: str, first_name: str | None = None, last_name: str | None = None, nickname: str | None = None, birthday: str | None = None, gender: Literal["female", "male", "diverse", "unspecified"] | None = None, email: str | None = None, phone: str | None = None, address: str | None = None, website: str | None = None, job_title: str | None = None, organization: str | None = None, how_met: str | None = None, tags: list[str] | None = None, is_favorite: bool | None = None, notes: str | None = None) -> dict:
        owner_id = mcp_user("memory:write")
        changes = {key: value for key, value in locals().copy().items() if key in PersonIn.model_fields and value is not None}
        with mcp_session(owner_id) as db:
            person = owned_person(db, person_id, db.get(User, owner_id))
            for key, value in changes.items(): setattr(person, key, value)
            if "gender" in changes:
                refresh_relationship_labels(db, owner_id, person)
            db.commit(); db.refresh(person)
            enqueue_person_context_embeddings(db, person.id, owner_id)
            return PersonOut.model_validate(person).model_dump(mode="json")

    @mcp.tool(name="relationship_create")
    def relationship_create_mcp(source_person_id: str, target_person_id: str, relationship_type: str, inverse_relationship_type: str | None = None, source_memory_id: str | None = None, confirmed: bool = True) -> dict:
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            row = relationship_add(RelationshipIn(source_person_id=source_person_id, target_person_id=target_person_id, relationship_type=relationship_type, inverse_relationship_type=inverse_relationship_type, source_memory_id=source_memory_id, confirmed=confirmed), db, db.get(User, owner_id))
            names = relationship_list(db, db.get(User, owner_id), source_person_id)
            match = next(item for item in names if item.id == row.id)
            return match.model_dump(mode="json")

    @mcp.tool(name="relationship_search")
    def relationship_search_mcp(person_id: str | None = None) -> list[dict]:
        owner_id = mcp_user()
        with mcp_session(owner_id) as db:
            return [item.model_dump(mode="json") for item in relationship_list(db, db.get(User, owner_id), person_id)]

    @mcp.tool(name="memory_get")
    def memory_get_mcp(memory_id: str) -> dict:
        owner_id = mcp_user()
        with mcp_session(owner_id) as db:
            row = db.scalar(select(Memory).where(Memory.id == memory_id, Memory.owner_id == owner_id))
            if row is None: raise ValueError("Erinnerung nicht gefunden")
            return MemoryOut.model_validate(row).model_dump(mode="json")

    @mcp.tool(name="memory_update")
    def memory_update_mcp(memory_id: str, title: str | None = None, content: str | None = None, person_id: str | None = None, occurred_at: str | None = None) -> dict:
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            row = db.scalar(select(Memory).where(Memory.id == memory_id, Memory.owner_id == owner_id))
            if row is None: raise ValueError("Erinnerung nicht gefunden")
            if person_id is not None: owned_person(db, person_id, db.get(User, owner_id))
            parsed_occurred_at = datetime.fromisoformat(occurred_at.replace("Z", "+00:00")) if occurred_at is not None else None
            for key, value in (("title", title), ("content", content), ("person_id", person_id), ("occurred_at", parsed_occurred_at)):
                if value is not None: setattr(row, key, value)
            db.commit(); db.refresh(row)
            enqueue_memory_embedding(row.id, owner_id)
            return MemoryOut.model_validate(row).model_dump(mode="json")

    @mcp.tool(name="memory_delete")
    def memory_delete_mcp(memory_id: str) -> dict:
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            row = db.scalar(select(Memory).where(Memory.id == memory_id, Memory.owner_id == owner_id))
            if row is None: raise ValueError("Erinnerung nicht gefunden")
            return request_approval(db, owner_id, "memory_delete", row.id, row.title)

    @mcp.tool(name="conversation_create")
    def conversation_create_mcp(title: str, original_note: str, participant_ids: list[str] | None = None, project_ids: list[str] | None = None, occurred_at: str | None = None, location: str = "", summary: str = "") -> dict:
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            row = conversation_create(ConversationIn(title=title, original_note=original_note, participant_ids=participant_ids or [], project_ids=project_ids or [], occurred_at=occurred_at, location=location, summary=summary), db, db.get(User, owner_id))
            return row.model_dump(mode="json")

    @mcp.tool(name="conversation_search")
    def conversation_search_mcp(query: str = "", person_id: str | None = None) -> list[dict]:
        owner_id = mcp_user()
        with mcp_session(owner_id) as db:
            return [row.model_dump(mode="json") for row in conversation_list(db, db.get(User, owner_id), person_id, query)]

    @mcp.tool(name="task_create")
    def task_create_mcp(title: str, description: str = "", person_id: str | None = None, project_id: str | None = None, due_at: str | None = None, priority: int = 2, repeat_interval_days: int | None = None, repeat_until: str | None = None) -> dict:
        from lifepilot.planner import task_create as create_task
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            row = create_task(TaskIn(title=title, description=description, person_id=person_id, project_id=project_id, due_at=due_at, priority=priority, repeat_interval_days=repeat_interval_days, repeat_until=repeat_until), db, db.get(User, owner_id))
            return TaskOut.model_validate(row).model_dump(mode="json")

    @mcp.tool(name="task_search")
    def task_search_mcp(status: str | None = None, person_id: str | None = None) -> list[dict]:
        from lifepilot.planner import task_list
        owner_id = mcp_user()
        with mcp_session(owner_id) as db:
            rows = task_list(db, db.get(User, owner_id), status)
            if person_id is not None: rows = [row for row in rows if row.person_id == person_id]
            return [TaskOut.model_validate(row).model_dump(mode="json") for row in rows]

    @mcp.tool(name="task_complete")
    def task_complete_mcp(task_id: str) -> dict:
        from lifepilot.planner import task_complete
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            row = task_complete(task_id, db, db.get(User, owner_id))
            return TaskOut.model_validate(row).model_dump(mode="json")

    @mcp.tool(name="event_create")
    def event_create_mcp(title: str, starts_at: str, description: str = "", location: str = "", location_address: str = "", record_type: str = "appointment", ends_at: str | None = None, participant_ids: list[str] | None = None, source_memory_id: str | None = None) -> dict:
        from lifepilot.planner import event_create
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            row = event_create(EventIn(title=title, starts_at=starts_at, description=description, location=location, location_address=location_address, record_type=record_type, ends_at=ends_at, participant_ids=participant_ids or [], source_memory_id=source_memory_id), db, db.get(User, owner_id))
            return row.model_dump(mode="json")

    @mcp.tool(name="upcoming_events")
    def upcoming_events_mcp(from_at: str | None = None, to_at: str | None = None, person_id: str | None = None) -> list[dict]:
        from lifepilot.planner import event_list
        owner_id = mcp_user()
        with mcp_session(owner_id) as db:
            start = datetime.fromisoformat(from_at.replace("Z", "+00:00")) if from_at else None
            end = datetime.fromisoformat(to_at.replace("Z", "+00:00")) if to_at else None
            rows = event_list(db, db.get(User, owner_id), start, end, person_id)
            return [row.model_dump(mode="json") for row in rows]

    @mcp.tool(name="loan_create")
    def loan_create_mcp(item_name: str, lender_person_id: str | None = None, borrower_person_id: str | None = None, due_at: str | None = None, condition_note: str = "", source_memory_id: str | None = None) -> dict:
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            row = loan_create(LoanIn(item_name=item_name, lender_person_id=lender_person_id, borrower_person_id=borrower_person_id, due_at=due_at, condition_note=condition_note, source_memory_id=source_memory_id), db, db.get(User, owner_id))
            return LoanOut.model_validate(row).model_dump(mode="json")

    @mcp.tool(name="loan_search")
    def loan_search_mcp(open_only: bool = True, person_id: str | None = None) -> list[dict]:
        owner_id = mcp_user()
        with mcp_session(owner_id) as db:
            rows = loan_list(db, db.get(User, owner_id), open_only, person_id)
            return [LoanOut.model_validate(row).model_dump(mode="json") for row in rows]

    @mcp.tool(name="loan_return")
    def loan_return_mcp(loan_id: str) -> dict:
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            row = loan_return(loan_id, db, db.get(User, owner_id))
            return LoanOut.model_validate(row).model_dump(mode="json")

    @mcp.tool(name="gift_create")
    def gift_create_mcp(person_id: str, title: str, note: str = "", occasion: str = "", budget: int | None = None, source_memory_id: str | None = None) -> dict:
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            row = gift_create(GiftIn(person_id=person_id, title=title, note=note, occasion=occasion, budget=budget, source_memory_id=source_memory_id), db, db.get(User, owner_id))
            return GiftOut.model_validate(row).model_dump(mode="json")

    @mcp.tool(name="gift_search")
    def gift_search_mcp(person_id: str | None = None) -> list[dict]:
        owner_id = mcp_user()
        with mcp_session(owner_id) as db:
            rows = gift_list(db, db.get(User, owner_id), person_id)
            return [GiftOut.model_validate(row).model_dump(mode="json") for row in rows]

    @mcp.tool(name="person_context")
    def person_context_mcp(person_id: str) -> dict:
        owner_id = mcp_user()
        with mcp_session(owner_id) as db:
            data = person_briefing(person_id, db, db.get(User, owner_id))
            data["relationships"] = [row.model_dump(mode="json") for row in relationship_list(db, db.get(User, owner_id), person_id)]
            return data

    @mcp.tool(name="daily_briefing")
    def daily_briefing_mcp() -> dict:
        owner_id = mcp_user()
        with mcp_session(owner_id) as db:
            return daily_briefing(db, db.get(User, owner_id))

    @mcp.tool(name="open_commitments")
    def open_commitments_mcp() -> dict:
        owner_id = mcp_user()
        with mcp_session(owner_id) as db:
            tasks = db.scalars(select(Task).where(Task.owner_id == owner_id, Task.status == "open").order_by(Task.due_at)).all()
            loans = db.scalars(select(Loan).where(Loan.owner_id == owner_id, Loan.returned_at.is_(None)).order_by(Loan.due_at)).all()
            return {"tasks": [TaskOut.model_validate(row).model_dump(mode="json") for row in tasks], "loans": [LoanOut.model_validate(row).model_dump(mode="json") for row in loans]}

except ImportError:
    pass

if "mcp" in globals():
    from lifepilot.mcp_planning_tools import register_planning_tools
    from lifepilot.mcp_extended_tools import register_extended_tools
    register_planning_tools(mcp)
    register_extended_tools(mcp)
