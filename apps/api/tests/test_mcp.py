import anyio
import json

from httpx import ASGITransport, AsyncClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy.orm import Session

from lifepilot.db import engine
from lifepilot.config import settings
from lifepilot.main import mcp
from lifepilot.models import Capture, Person, User
from lifepilot.capture_schemas import CaptureSuggestion
from lifepilot.security import create_token, resolve_bearer_scopes


def test_mcp_tools_are_registered() -> None:
    tools = mcp._tool_manager.list_tools()
    names = {tool.name for tool in tools}
    assert sum(tool.name == "attachment_search" for tool in tools) == 1
    assert {"person_create_tool", "person_search_tool", "person_contact_methods", "person_contact_method_create", "person_contact_method_update", "person_contact_method_delete", "memory_capture", "memory_capture_status", "memory_capture_list", "memory_capture_tool", "memory_search_tool", "person_get", "person_update", "relationship_create", "relationship_search", "relationship_update", "memory_get", "memory_update", "memory_delete", "memory_review", "note_create", "note_search", "note_get", "note_update", "note_delete", "conversation_create", "conversation_search", "conversation_get", "conversation_update", "conversation_history", "conversation_delete", "task_create", "task_search", "task_update", "task_history", "task_complete", "task_delete", "event_create", "event_update", "event_search", "event_delete", "upcoming_events", "reminder_create", "reminder_update", "reminder_search", "reminder_delete", "loan_create", "loan_search", "loan_return", "loan_update", "loan_delete", "gift_create", "gift_search", "gift_update", "gift_delete", "person_context", "person_merge", "profile_get", "profile_update", "daily_briefing", "open_commitments", "person_delete", "relationship_delete", "audit_search", "project_create", "project_search", "project_get", "project_update", "project_delete", "approval_search", "attachment_search", "journal_create", "journal_search", "journal_get", "journal_update", "journal_delete", "pet_create", "pet_search", "pet_get", "pet_update", "pet_delete"} <= names


def test_official_mcp_client_auth_and_scope_enforcement(client, auth, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
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
                        assert {"next_best_action", "task_planning_update", "commitment_create", "work_checkpoint_save"}.issubset({tool.name for tool in listed.tools})
                        promise = await session.call_tool("commitment_create", {"title": "MCP-Rückmeldung", "direction": "incoming"})
                        assert not promise.isError
                        promise_id = json.loads(promise.content[0].text)["id"]
                        waiting = await session.call_tool("waiting_for_list", {})
                        assert not waiting.isError and promise_id in str(waiting.content)
                        finished = await session.call_tool("commitment_set_status", {"commitment_id": promise_id, "status": "done"})
                        assert not finished.isError
                        checkpoint = await session.call_tool("work_checkpoint_save", {"title": "MCP-Arbeitsstand", "next_step": "Test ausführen"})
                        assert not checkpoint.isError
                        checkpoint_id = json.loads(checkpoint.content[0].text)["id"]
                        resumed = await session.call_tool("work_checkpoint_resume", {"checkpoint_id": checkpoint_id})
                        assert not resumed.isError and "Test ausführen" in str(resumed.content)
                        planning_task = client.post("/api/tasks", headers=auth, json={"title": "MCP-Planungstest"}).json()["id"]
                        planned = await session.call_tool("task_planning_update", {"task_id": planning_task, "planning": {"estimated_minutes": 120, "mental_effort": "high", "work_context": "computer"}})
                        assert not planned.isError
                        rejected_steps = await session.call_tool("task_steps_add", {"task_id": planning_task, "data": {"steps": [{"title": "MCP Schritt"}]}})
                        assert rejected_steps.isError
                        accepted_steps = await session.call_tool("task_steps_add", {"task_id": planning_task, "data": {"steps": [{"title": "MCP Schritt"}]}, "confirm": True})
                        assert not accepted_steps.isError
                        listed_steps = await session.call_tool("task_steps_list", {"task_id": planning_task})
                        assert not listed_steps.isError and "MCP Schritt" in str(listed_steps.content)
                        step_id = client.get(f"/api/tasks/{planning_task}/steps", headers=auth).json()[0]["id"]
                        checked_step = await session.call_tool("task_step_set_state", {"task_id": planning_task, "step_id": step_id, "completed": True})
                        assert not checked_step.isError
                        focus = await session.call_tool("focus_start", {"task_id": planning_task, "planned_minutes": 15, "companion_interval_minutes": 5, "companion_goal": "MCP Ziel"})
                        assert not focus.isError
                        focus_id = json.loads(focus.content[0].text)["id"]
                        active_focus = await session.call_tool("focus_active", {})
                        assert not active_focus.isError and focus_id in str(active_focus.content)
                        companion = await session.call_tool("focus_companion", {"session_id": focus_id})
                        assert not companion.isError and "MCP Ziel" in str(companion.content)
                        checkin = await session.call_tool("focus_checkin", {"session_id": focus_id, "data": {"request_id": "82be80ab-83d7-4d8c-9a30-e946cba99187", "state": "on_track", "next_step": "MCP nächster Schritt"}})
                        assert not checkin.isError and "MCP nächster Schritt" in str(checkin.content)
                        ended_focus = await session.call_tool("focus_end", {"session_id": focus_id, "data": {"outcome": "finished"}})
                        assert not ended_focus.isError
                        routine = await session.call_tool("routine_create", {"data": {"title": "MCP Morgenroutine", "weekdays": [0, 1, 2, 3, 4, 5, 6], "steps": [{"title": "Tagesplan ansehen"}]}})
                        assert not routine.isError
                        routine_row = json.loads(routine.content[0].text)
                        routine_id = routine_row["id"]
                        routine_step_id = routine_row["steps"][0]["id"]
                        routines = await session.call_tool("routine_list", {})
                        assert not routines.isError and routine_id in str(routines.content)
                        marked = await session.call_tool("routine_step_complete", {"routine_id": routine_id, "step_id": routine_step_id, "local_date": routine_row["local_date"], "completed": True})
                        assert not marked.isError
                        routine_history = await session.call_tool("routine_history", {"routine_id": routine_id})
                        assert not routine_history.isError and routine_step_id in str(routine_history.content)
                        archived_routine = await session.call_tool("routine_archive", {"routine_id": routine_id, "archived": True})
                        assert not archived_routine.isError
                        fact_person = client.post("/api/people", headers=auth, json={"first_name":"MCP Faktenperson"}).json()["id"]
                        proposed_fact = await session.call_tool("temporal_fact_propose", {"data":{"person_id":fact_person,"predicate":"Wohnort","value":"Köln","valid_from":"2020-01-01"}})
                        assert not proposed_fact.isError
                        fact = json.loads(proposed_fact.content[0].text)
                        assert fact["status"] == "proposed"
                        denied = await session.call_tool("temporal_fact_review", {"fact_id":fact["id"],"status":"confirmed"})
                        assert denied.isError
                        approved = await session.call_tool("temporal_fact_review", {"fact_id":fact["id"],"status":"confirmed","confirm":True})
                        assert not approved.isError
                        facts = await session.call_tool("temporal_fact_list", {"person_id":fact_person,"as_of":"2021-01-01","status":"confirmed"})
                        assert not facts.isError and fact["id"] in str(facts.content)
                        ended_fact = await session.call_tool("temporal_fact_end", {"fact_id":fact["id"],"valid_until":"2022-01-01","confirm":True})
                        assert not ended_fact.isError
                        focus_history = await session.call_tool("focus_history", {"task_id": planning_task})
                        assert not focus_history.isError and focus_id in str(focus_history.content)
                        recommended = await session.call_tool("next_best_action", {"minutes": 120, "energy": "high", "context": "computer"})
                        assert not recommended.isError and planning_task in str(recommended.content)
                        assert client.patch(f"/api/tasks/{planning_task}/complete", headers=auth).status_code == 200
                        created = await session.call_tool("person_create_tool", {"first_name": "MCP", "last_name": "Client", "how_met": "MCP-Club", "tags": ["MCP", "Kontakt"], "is_favorite": True})
                        assert not created.isError
                        created_person = json.loads(created.content[0].text)
                        person_id = created_person["id"]
                        assert created_person["how_met"] == "MCP-Club" and created_person["tags"] == ["MCP", "Kontakt"] and created_person["is_favorite"] is True
                        attachment = client.post("/api/attachments", headers=auth, data={"resource_type": "person", "resource_id": person_id}, files={"file": ("mcp-notiz.txt", b"MCP attachment metadata", "text/plain")})
                        assert attachment.status_code == 201
                        attachment_id = attachment.json()["id"]
                        attachment_search = await session.call_tool("attachment_search", {"resource_type": "person", "resource_id": person_id})
                        assert not attachment_search.isError and attachment_id in str(attachment_search.content)
                        private_attachment_search = await session.call_tool("attachment_search", {"resource_type": "person", "resource_id": "foreign-resource-id"})
                        assert private_attachment_search.isError
                        searched = await session.call_tool("person_search_tool", {"query": "MCP-Club"})
                        assert not searched.isError and "MCP" in str(searched.content)
                        contact_method = await session.call_tool("person_contact_method_create", {"person_id": person_id, "method_type": "email", "value": "mcp@example.org", "label": "Arbeit"})
                        assert not contact_method.isError and "mcp@example.org" in str(contact_method.content)
                        contact_method_id = json.loads(contact_method.content[0].text)["id"]
                        found_contact = await session.call_tool("person_search_tool", {"query": "mcp@example.org"})
                        assert not found_contact.isError and person_id in str(found_contact.content)
                        contact_methods = await session.call_tool("person_contact_methods", {"person_id": person_id})
                        assert not contact_methods.isError and contact_method_id in str(contact_methods.content)
                        changed_contact = await session.call_tool("person_contact_method_update", {"method_id": contact_method_id, "method_type": "email", "value": "mcp-work@example.org", "label": "Geschäftlich"})
                        assert not changed_contact.isError and "mcp-work@example.org" in str(changed_contact.content)
                        deleted_contact = await session.call_tool("person_contact_method_delete", {"method_id": contact_method_id})
                        assert not deleted_contact.isError and "deleted" in str(deleted_contact.content)
                        child = await session.call_tool("person_create_tool", {"first_name": "MCP-Kind", "gender": "female"})
                        child_id = json.loads(child.content[0].text)["id"]
                        assert json.loads(child.content[0].text)["gender"] == "female"
                        deleted_person["id"] = child_id
                        project = await session.call_tool("project_create", {"name": "MCP-Projekt", "description": "Nur für den Benutzer"})
                        project_id = json.loads(project.content[0].text)["id"]
                        project_attachment = client.post("/api/attachments", headers=auth, data={"resource_type": "project", "resource_id": project_id}, files={"file": ("mcp-projekt.txt", b"MCP project attachment", "text/plain")})
                        assert project_attachment.status_code == 201
                        project_attachment_id = project_attachment.json()["id"]
                        project_attachment_search = await session.call_tool("attachment_search", {"resource_type": "project", "resource_id": project_id})
                        assert not project_attachment_search.isError and project_attachment_id in str(project_attachment_search.content)
                        project_search = await session.call_tool("project_search", {"query": "MCP-Projekt"})
                        assert not project_search.isError and project_id in str(project_search.content)
                        project_get = await session.call_tool("project_get", {"project_id": project_id})
                        assert not project_get.isError and "Nur für den Benutzer" in str(project_get.content)
                        pet = await session.call_tool("pet_create", {"name": "MCP-Hund", "species": "Hund", "breed": "Mischling", "birthday": "2021-04-12", "person_links": [{"person_id": person_id, "relationship_type": "owner"}]})
                        assert not pet.isError and "MCP-Hund" in str(pet.content)
                        pet_id = json.loads(pet.content[0].text)["id"]
                        found_pets = await session.call_tool("pet_search", {"query": "MCP-Hund"})
                        assert not found_pets.isError and pet_id in str(found_pets.content)
                        changed_pet = await session.call_tool("pet_update", {"pet_id": pet_id, "notes": "Lieblingshund"})
                        assert not changed_pet.isError and "Lieblingshund" in str(changed_pet.content)
                        journal_entry = await session.call_tool("journal_create", {"entry_date": "2026-11-20", "title": "MCP-Tagebuch", "content": "Ein privater Tagebucheintrag", "mood": "ruhig", "person_ids": [person_id], "project_ids": [project_id]})
                        assert not journal_entry.isError and "ruhig" in str(journal_entry.content)
                        journal_id = json.loads(journal_entry.content[0].text)["id"]
                        journal_search = await session.call_tool("journal_search", {"query": "privater Tagebucheintrag"})
                        assert not journal_search.isError and journal_id in str(journal_search.content)
                        journal_get = await session.call_tool("journal_get", {"entry_id": journal_id})
                        assert not journal_get.isError and project_id in str(journal_get.content)
                        journal_update = await session.call_tool("journal_update", {"entry_id": journal_id, "title": "Aktualisierter Tagebucheintrag"})
                        assert not journal_update.isError and "Aktualisierter Tagebucheintrag" in str(journal_update.content)
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
                        updated_child = await session.call_tool("person_update", {"person_id": child_id, "gender": "male", "how_met": "MCP-Update", "tags": ["Familie", "Kontakt"], "is_favorite": True})
                        assert not updated_child.isError and '"gender": "male"' in str(updated_child.content) and '"is_favorite": true' in str(updated_child.content)
                        searched_label = await session.call_tool("person_search_tool", {"query": "Familie"})
                        assert not searched_label.isError and child_id in str(searched_label.content)
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
                            ("journal_delete", "entry_id", journal_id),
                            ("pet_delete", "pet_id", pet_id),
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
                        denied_journal = await session.call_tool("journal_create", {"entry_date": "2026-11-20", "content": "Schreibzugriff muss gesperrt bleiben"})
                        assert denied_journal.isError
                        denied_pet = await session.call_tool("pet_create", {"name": "Nicht speichern", "species": "Hund"})
                        assert denied_pet.isError
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
