import anyio
import json

from httpx import ASGITransport, AsyncClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy.orm import Session

from lifepilot.db import engine
from lifepilot.main import mcp
from lifepilot.models import Person, User
from lifepilot.security import create_token, resolve_bearer_scopes


def test_mcp_tools_are_registered() -> None:
    names = {tool.name for tool in mcp._tool_manager.list_tools()}
    assert {"person_create_tool", "person_search_tool", "memory_capture_tool", "memory_search_tool", "person_get", "person_update", "relationship_create", "relationship_search", "memory_get", "memory_update", "memory_delete", "conversation_create", "conversation_search", "conversation_get", "conversation_update", "task_create", "task_search", "task_update", "task_complete", "event_create", "event_update", "upcoming_events", "reminder_create", "reminder_update", "loan_create", "loan_search", "loan_return", "loan_update", "gift_create", "gift_search", "gift_update", "person_context", "daily_briefing", "open_commitments", "person_delete", "relationship_delete", "audit_search"} <= names


def test_official_mcp_client_auth_and_scope_enforcement(client) -> None:
    writable = client.post("/api/auth/mcp-token", json={"username": "testuser", "password": "test-password", "access": "read_write"})
    assert writable.status_code == 200
    token = writable.json()["access_token"]
    assert resolve_bearer_scopes(token) == ["memory:read", "memory:write"]
    readonly = client.post("/api/auth/mcp-token", json={"username": "testuser", "password": "test-password", "access": "read_only"})
    assert readonly.status_code == 200
    readonly_token = readonly.json()["access_token"]
    assert resolve_bearer_scopes(readonly_token) == ["memory:read"]
    with Session(engine) as db:
        other = User(username="mcp-private-user", password_hash="unused")
        db.add(other); db.flush()
        other_user_id = other.id
        private_person = Person(owner_id=other.id, first_name="Geheim")
        db.add(private_person); db.commit()
        foreign_person_id = private_person.id

    async def connect_and_check() -> None:
        app = mcp.streamable_http_app()
        async with mcp.session_manager.run():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:8002", headers={"Authorization": f"Bearer {token}"}) as http:
                async with streamable_http_client("http://localhost:8002/mcp", http_client=http) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        listed = await session.list_tools()
                        assert "relationship_create" in {tool.name for tool in listed.tools}
                        created = await session.call_tool("person_create_tool", {"first_name": "MCP", "last_name": "Client"})
                        assert not created.isError
                        person_id = json.loads(created.content[0].text)["id"]
                        searched = await session.call_tool("person_search_tool", {"query": "MCP"})
                        assert not searched.isError and "MCP" in str(searched.content)
                        child = await session.call_tool("person_create_tool", {"first_name": "MCP-Kind"})
                        child_id = json.loads(child.content[0].text)["id"]
                        relation = await session.call_tool("relationship_create", {"source_person_id": person_id, "target_person_id": child_id, "relationship_type": "Vater von"})
                        assert not relation.isError and "Tochter von" in str(relation.content)
                        context = await session.call_tool("person_context", {"person_id": person_id})
                        assert not context.isError and "MCP-Kind" in str(context.content)
                        forbidden = await session.call_tool("person_get", {"person_id": foreign_person_id})
                        assert forbidden.isError
                        task_result = await session.call_tool("task_create", {"title": "MCP Aufgabe"})
                        task_id = json.loads(task_result.content[0].text)["id"]
                        updated_task = await session.call_tool("task_update", {"task_id": task_id, "title": "MCP Aufgabe geändert"})
                        assert not updated_task.isError and "geändert" in str(updated_task.content)
                        event_result = await session.call_tool("event_create", {"title": "MCP Termin", "starts_at": "2026-12-01T12:00:00Z"})
                        event_id = json.loads(event_result.content[0].text)["id"]
                        updated_event = await session.call_tool("event_update", {"event_id": event_id, "location": "Vereinsheim"})
                        assert not updated_event.isError and "Vereinsheim" in str(updated_event.content)
                        reminder_result = await session.call_tool("reminder_create", {"due_at": "2026-12-01T12:00:00Z", "event_id": event_id})
                        reminder_id = json.loads(reminder_result.content[0].text)["id"]
                        muted = await session.call_tool("reminder_update", {"reminder_id": reminder_id, "state": "muted"})
                        assert not muted.isError and "muted" in str(muted.content)
                        conversation_result = await session.call_tool("conversation_create", {"title": "MCP Gespräch", "original_note": "Original bleibt erhalten", "participant_ids": [person_id]})
                        conversation_id = json.loads(conversation_result.content[0].text)["id"]
                        changed_conversation = await session.call_tool("conversation_update", {"conversation_id": conversation_id, "summary": "Zusammenfassung"})
                        assert not changed_conversation.isError and "Zusammenfassung" in str(changed_conversation.content)
                        audit = await session.call_tool("audit_search", {"limit": 100})
                        audit_rows = audit.structuredContent["result"]
                        assert not audit.isError and any(row["resource_type"] == "tasks" and row["action"] == "update" for row in audit_rows)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:8002", headers={"Authorization": f"Bearer {readonly_token}"}) as http:
                async with streamable_http_client("http://localhost:8002/mcp", http_client=http) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        denied = await session.call_tool("task_create", {"title": "Soll nicht gespeichert werden"})
                        assert denied.isError
                        denied_person = await session.call_tool("person_create_tool", {"first_name": "Soll auch nicht gespeichert werden"})
                        assert denied_person.isError
        other_headers = {"Authorization": f"Bearer {create_token(other_user_id)}"}
        assert client.get("/api/audit", headers=other_headers).json() == []

    anyio.run(connect_and_check)
