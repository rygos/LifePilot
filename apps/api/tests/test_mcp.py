import anyio
import json

from httpx import ASGITransport, AsyncClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy.orm import Session

from lifepilot.db import engine
from lifepilot.main import mcp
from lifepilot.models import Capture, Person, User
from lifepilot.capture_schemas import CaptureSuggestion
from lifepilot.security import create_token, resolve_bearer_scopes


def test_mcp_tools_are_registered() -> None:
    names = {tool.name for tool in mcp._tool_manager.list_tools()}
    assert {"person_create_tool", "person_search_tool", "memory_capture", "memory_capture_status", "memory_capture_list", "memory_capture_tool", "memory_search_tool", "person_get", "person_update", "relationship_create", "relationship_search", "relationship_update", "memory_get", "memory_update", "memory_delete", "memory_review", "note_create", "note_search", "note_get", "note_update", "note_delete", "conversation_create", "conversation_search", "conversation_get", "conversation_update", "conversation_history", "conversation_delete", "task_create", "task_search", "task_update", "task_history", "task_complete", "task_delete", "event_create", "event_update", "event_search", "event_delete", "upcoming_events", "reminder_create", "reminder_update", "reminder_search", "reminder_delete", "loan_create", "loan_search", "loan_return", "loan_update", "loan_delete", "gift_create", "gift_search", "gift_update", "gift_delete", "person_context", "person_merge", "profile_get", "profile_update", "daily_briefing", "open_commitments", "person_delete", "relationship_delete", "audit_search", "project_create", "project_search", "project_get", "project_update", "project_delete", "approval_search"} <= names


def test_official_mcp_client_auth_and_scope_enforcement(client, auth) -> None:
    writable = client.post("/api/auth/mcp-token", json={"username": "testuser", "password": "test-password", "access": "read_write"})
    assert writable.status_code == 200
    token = writable.json()["access_token"]
    assert resolve_bearer_scopes(token) == ["memory:read", "memory:write"]
    readonly = client.post("/api/auth/mcp-token", json={"username": "testuser", "password": "test-password", "access": "read_only"})
    assert readonly.status_code == 200
    readonly_token = readonly.json()["access_token"]
    assert resolve_bearer_scopes(readonly_token) == ["memory:read"]
    assert client.get("/api/approvals", headers={"Authorization": f"Bearer {token}"}).status_code == 403
    owner_id = client.get("/api/auth/me", headers=auth).json()["id"]
    with Session(engine) as db:
        other = User(username="mcp-private-user", password_hash="unused")
        db.add(other); db.flush()
        other_user_id = other.id
        private_person = Person(owner_id=other.id, first_name="Geheim")
        db.add(private_person); db.commit()
        foreign_person_id = private_person.id
        ready_capture = Capture(owner_id=owner_id, original_text="Geprüfte KI-Vorschläge")
        ready_capture.status = "ready"
        ready_capture.suggestions_json = json.dumps([{"title": "Geprüfte Notiz", "content": "Nur nach Bestätigung", "person_name": None, "occurred_at": None}])
        new_person_capture = Capture(owner_id=owner_id, original_text="MCP-Kontakt kennenlernen")
        new_person_capture.status = "ready"
        new_person_capture.suggestions_json = json.dumps([{"kind": "conversation", "title": "Gespräch mit MCP-Neu Person", "content": "Wir sprachen über den Verein.", "person_name": "MCP-Neu Person"}])
        owner_relationship_capture = Capture(owner_id=owner_id, original_text="Meine Arbeitskollegin MCP ist zu mir verknüpft.")
        owner_relationship_capture.status = "ready"
        owner_relationship_capture.suggestions_json = json.dumps([CaptureSuggestion(kind="owner_relationship", title="MCP ist meine Kollegin", content="MCP arbeitet mit mir.", person_name="MCP Client", relationship_type="Arbeitskollegin", confirmation_required=True).model_dump(mode="json")])
        merge_relationship_capture = Capture(owner_id=owner_id, original_text="Zusammenführen ist meine Projektkollegin.")
        merge_relationship_capture.status = "ready"
        merge_relationship_capture.suggestions_json = json.dumps([CaptureSuggestion(kind="owner_relationship", title="Zusammenführen ist meine Projektkollegin", content="Arbeitet gemeinsam im Projekt.", person_name="Zusammenführen", relationship_type="Projektkollegin", confirmation_required=True).model_dump(mode="json")])
        db.add_all([ready_capture, new_person_capture, owner_relationship_capture, merge_relationship_capture]); db.commit()
        ready_capture_id = ready_capture.id
        new_person_capture_id = new_person_capture.id
        owner_relationship_capture_id = owner_relationship_capture.id
        merge_relationship_capture_id = merge_relationship_capture.id

    pending_approval: dict[str, str] = {}
    resource_approvals: list[str] = []
    deleted_person: dict[str, str] = {}

    async def connect_and_check() -> None:
        app = mcp.streamable_http_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:8002", headers={**auth, "Accept": "application/json, text/event-stream"}) as user_http:
            rejected_session = await user_http.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test-user-token", "version": "1.0"}}})
            assert rejected_session.status_code == 401
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
                        child = await session.call_tool("person_create_tool", {"first_name": "MCP-Kind", "gender": "female"})
                        child_id = json.loads(child.content[0].text)["id"]
                        assert json.loads(child.content[0].text)["gender"] == "female"
                        deleted_person["id"] = child_id
                        project = await session.call_tool("project_create", {"name": "MCP-Projekt", "description": "Nur für den Benutzer"})
                        project_id = json.loads(project.content[0].text)["id"]
                        project_search = await session.call_tool("project_search", {"query": "MCP-Projekt"})
                        assert not project_search.isError and project_id in str(project_search.content)
                        project_get = await session.call_tool("project_get", {"project_id": project_id})
                        assert not project_get.isError and "Nur für den Benutzer" in str(project_get.content)
                        captured = await session.call_tool("memory_capture", {"original_text": "Der MCP-Originaltext bleibt erhalten."})
                        assert not captured.isError and "Der MCP-Originaltext bleibt erhalten." in str(captured.content)
                        capture_id = json.loads(captured.content[0].text)["id"]
                        capture_status = await session.call_tool("memory_capture_status", {"capture_id": capture_id})
                        assert not capture_status.isError and "Der MCP-Originaltext bleibt erhalten." in str(capture_status.content)
                        capture_list = await session.call_tool("memory_capture_list", {"limit": 10})
                        assert not capture_list.isError and capture_id in str(capture_list.content)
                        profile = await session.call_tool("profile_update", {"nickname": "MCP-Profil"})
                        assert not profile.isError and "MCP-Profil" in str(profile.content)
                        note = await session.call_tool("note_create", {"title": "MCP Notiz", "content": "Notizinhalt", "person_id": person_id})
                        note_id = json.loads(note.content[0].text)["id"]
                        edited_note = await session.call_tool("note_update", {"note_id": note_id, "content": "Geänderter Notizinhalt"})
                        assert not edited_note.isError and "Geänderter Notizinhalt" in str(edited_note.content)
                        found_note = await session.call_tool("note_search", {"query": "Geänderter Notizinhalt"})
                        assert not found_note.isError and note_id in str(found_note.content)
                        reviewed = await session.call_tool("memory_review", {"capture_id": ready_capture_id, "accepted_indices": [0], "suggestions": [{"title": "Korrigierte Notiz", "content": "Korrigierter Inhalt", "kind": "fact"}]})
                        assert not reviewed.isError and "Korrigierte Notiz" in str(reviewed.content)
                        new_contact = await session.call_tool("memory_review", {"capture_id": new_person_capture_id, "accepted_indices": [0], "create_people": [0], "confirmations": [0]})
                        assert not new_contact.isError and "conversation" in str(new_contact.content)
                        found_new_contact = await session.call_tool("person_search_tool", {"query": "MCP-Neu"})
                        assert not found_new_contact.isError and "Person" in str(found_new_contact.content)
                        relation = await session.call_tool("relationship_create", {"source_person_id": person_id, "target_person_id": child_id, "relationship_type": "Vater von"})
                        assert not relation.isError and "Tochter von" in str(relation.content)
                        relation_id = json.loads(relation.content[0].text)["id"]
                        updated_relation = await session.call_tool("relationship_update", {"relationship_id": relation_id, "relationship_type": "Elternteil von", "inverse_relationship_type": "Kind von"})
                        assert not updated_relation.isError and "Elternteil von" in str(updated_relation.content)
                        updated_child = await session.call_tool("person_update", {"person_id": child_id, "gender": "male"})
                        assert not updated_child.isError and '"gender": "male"' in str(updated_child.content)
                        updated_relation = await session.call_tool("relationship_search", {"person_id": person_id})
                        assert not updated_relation.isError and "Sohn von" in str(updated_relation.content)
                        owner_relationship = await session.call_tool("memory_review", {"capture_id": owner_relationship_capture_id, "accepted_indices": [0], "person_assignments": {"0": person_id}, "confirmations": [0]})
                        assert not owner_relationship.isError and "owner_relationship" in str(owner_relationship.content)
                        context = await session.call_tool("person_context", {"person_id": person_id})
                        assert not context.isError and "MCP-Kind" in str(context.content) and "Arbeitskollegin" in str(context.content)
                        forbidden = await session.call_tool("person_get", {"person_id": foreign_person_id})
                        assert forbidden.isError
                        task_result = await session.call_tool("task_create", {"title": "MCP Aufgabe"})
                        task_id = json.loads(task_result.content[0].text)["id"]
                        updated_task = await session.call_tool("task_update", {"task_id": task_id, "title": "MCP Aufgabe geändert"})
                        assert not updated_task.isError and "geändert" in str(updated_task.content)
                        task_versions = await session.call_tool("task_history", {"task_id": task_id})
                        assert not task_versions.isError and "MCP Aufgabe geändert" in str(task_versions.content)
                        event_result = await session.call_tool("event_create", {"title": "MCP Termin", "starts_at": "2026-12-01T12:00:00Z"})
                        event_id = json.loads(event_result.content[0].text)["id"]
                        updated_event = await session.call_tool("event_update", {"event_id": event_id, "location": "Vereinsheim"})
                        assert not updated_event.isError and "Vereinsheim" in str(updated_event.content)
                        found_events = await session.call_tool("event_search", {"from_at": "2026-11-01T00:00:00Z", "to_at": "2027-01-01T00:00:00Z"})
                        assert not found_events.isError and event_id in str(found_events.content)
                        reminder_result = await session.call_tool("reminder_create", {"due_at": "2026-12-01T12:00:00Z", "event_id": event_id})
                        reminder_id = json.loads(reminder_result.content[0].text)["id"]
                        muted = await session.call_tool("reminder_update", {"reminder_id": reminder_id, "state": "muted"})
                        assert not muted.isError and "muted" in str(muted.content)
                        conversation_result = await session.call_tool("conversation_create", {"title": "MCP Gespräch", "original_note": "Original bleibt erhalten", "participant_ids": [person_id]})
                        conversation_id = json.loads(conversation_result.content[0].text)["id"]
                        changed_conversation = await session.call_tool("conversation_update", {"conversation_id": conversation_id, "summary": "Zusammenfassung"})
                        assert not changed_conversation.isError and "Zusammenfassung" in str(changed_conversation.content)
                        conversation_versions = await session.call_tool("conversation_history", {"conversation_id": conversation_id})
                        assert not conversation_versions.isError and "Zusammenfassung" in str(conversation_versions.content)
                        loan_result = await session.call_tool("loan_create", {"item_name": "MCP Bohrmaschine", "borrower_person_id": person_id})
                        loan_id = json.loads(loan_result.content[0].text)["id"]
                        gift_result = await session.call_tool("gift_create", {"person_id": person_id, "title": "MCP Buch"})
                        gift_id = json.loads(gift_result.content[0].text)["id"]
                        audit = await session.call_tool("audit_search", {"limit": 100})
                        audit_rows = audit.structuredContent["result"]
                        assert not audit.isError and any(row["resource_type"] == "tasks" and row["action"] == "update" for row in audit_rows)
                        requested = await session.call_tool("person_delete", {"person_id": child_id})
                        assert not requested.isError
                        pending_approval["id"] = json.loads(requested.content[0].text)["approval_id"]
                        duplicate = await session.call_tool("person_delete", {"person_id": child_id})
                        assert json.loads(duplicate.content[0].text)["approval_id"] == pending_approval["id"]
                        approval_rows = await session.call_tool("approval_search", {})
                        assert not approval_rows.isError and pending_approval["id"] in str(approval_rows.content)
                        for tool_name, resource_key, resource_id in (
                            ("note_delete", "note_id", note_id),
                            ("conversation_delete", "conversation_id", conversation_id),
                            ("task_delete", "task_id", task_id),
                            ("event_delete", "event_id", event_id),
                            ("reminder_delete", "reminder_id", reminder_id),
                            ("loan_delete", "loan_id", loan_id),
                            ("gift_delete", "gift_id", gift_id),
                            ("project_delete", "project_id", project_id),
                        ):
                            requested_delete = await session.call_tool(tool_name, {resource_key: resource_id})
                            assert not requested_delete.isError, tool_name
                            resource_approvals.append(json.loads(requested_delete.content[0].text)["approval_id"])
                        listed_reminders = await session.call_tool("reminder_search", {"state": "muted"})
                        assert not listed_reminders.isError and reminder_id in str(listed_reminders.content)
                        merge_source = await session.call_tool("person_create_tool", {"first_name": "Zusammenführen"})
                        merge_source_id = json.loads(merge_source.content[0].text)["id"]
                        merge_note = await session.call_tool("note_create", {"title": "Wird übernommen", "content": "Erinnerung bleibt", "person_id": merge_source_id})
                        merge_note_id = json.loads(merge_note.content[0].text)["id"]
                        merge_relation = await session.call_tool("memory_review", {"capture_id": merge_relationship_capture_id, "accepted_indices": [0], "person_assignments": {"0": merge_source_id}, "confirmations": [0]})
                        assert not merge_relation.isError and "owner_relationship" in str(merge_relation.content)
                        not_confirmed = await session.call_tool("person_merge", {"source_person_id": merge_source_id, "target_person_id": person_id})
                        assert not_confirmed.isError
                        merged = await session.call_tool("person_merge", {"source_person_id": merge_source_id, "target_person_id": person_id, "confirm": True})
                        assert not merged.isError and person_id in str(merged.content)
                        merged_note = await session.call_tool("note_get", {"note_id": merge_note_id})
                        assert not merged_note.isError and person_id in str(merged_note.content)
                        merged_context = await session.call_tool("person_context", {"person_id": person_id})
                        assert not merged_context.isError and "Projektkollegin" in str(merged_context.content)
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
    pending = client.get("/api/approvals", headers=auth)
    assert pending.status_code == 200 and pending.json()[0]["id"] == pending_approval["id"]
    assert client.get(f"/api/people/{deleted_person['id']}", headers=auth).status_code == 200
    decided = client.post(f"/api/approvals/{pending_approval['id']}/approve", headers=auth)
    assert decided.status_code == 200 and decided.json()["status"] == "executed"
    assert client.get(f"/api/people/{deleted_person['id']}", headers=auth).status_code == 404
    audit_rows = client.get("/api/audit", headers=auth).json()
    assert any(row["action"] == "delete" and row["resource_type"] == "people" and row["resource_id"] == deleted_person["id"] and row["source"] == "web" for row in audit_rows)
    for approval_id in resource_approvals:
        decided_resource = client.post(f"/api/approvals/{approval_id}/approve", headers=auth)
        assert decided_resource.status_code == 200 and decided_resource.json()["status"] == "executed"
