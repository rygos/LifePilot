import ast
import inspect
import textwrap
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from lifepilot.config import settings
from lifepilot.main import mcp
from lifepilot.mcp_permissions import ALL_SCOPES, DOMAIN_SCOPES, permits, valid_scopes
from lifepilot.security import claims
from fastapi import HTTPException


def test_scope_matrix_and_fail_closed_tools():
    for scope in DOMAIN_SCOPES:
        assert permits([scope],scope)
        assert not permits([scope],"memory:read")
        assert not permits([scope],"memory:write")
        for other in DOMAIN_SCOPES-{scope}:
            assert not permits([scope],other)
    assert not permits(["memory:read"],"tasks:write")
    assert permits(["memory:read"],"notes:read")
    assert permits(["memory:read","memory:write"],"tasks:write")
    assert not permits(["memory:read","memory:write"],"family:read")
    assert not permits(["memory:read","memory:write"],"mcp:access")
    # Audit every registered implementation: every tool has an explicit
    # owner/scope gate, even when invoking the underlying tool directly.
    expected={
        "capture:write":{"capture_submit"},
        "capture:read":{"memory_capture_status","memory_capture_list"},
        "tasks:read":{"task_search","task_history","task_steps_list","next_best_action"},
        "tasks:write":{"task_create","task_update","task_complete","task_planning_update","task_steps_add","task_step_set_state"},
        "notes:read":{"memory_get","note_get","note_search"},
        "notes:write":{"memory_capture_tool","memory_update","note_create","note_update"},
        "people:read":{"person_search_tool","person_get","person_contact_methods","person_call_search","relationship_search"},
        "people:write":{"person_create_tool","person_update","person_contact_method_create","person_contact_method_update","person_call_log","relationship_create","relationship_update"},
        "projects:read":{"project_get","project_search"},
        "projects:write":{"project_create","project_update"},
        "calendar:read":{"upcoming_events","event_search"},
        "calendar:write":{"event_create","event_update"},
        "documents:read":{"document_list","document_search","document_read"},
        "family:read":{"family_spaces","family_items","family_shared_records"},
    }
    actual={scope:set() for scope in DOMAIN_SCOPES}
    for tool in mcp._tool_manager.list_tools():
        tree=ast.parse(textwrap.dedent(inspect.getsource(tool.fn)))
        checks=sorted((node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=="mcp_user"),key=lambda n:n.lineno)
        assert checks,tool.name
        assert not checks[0].keywords,tool.name
        scope=checks[0].args[0].value if checks[0].args else "memory:read"
        assert scope in ALL_SCOPES,tool.name
        if scope in actual:
            actual[scope].add(tool.name)
    assert actual==expected


@pytest.mark.parametrize("extra",[
    {"access":"scoped","scopes":[]},
    {"access":"scoped","scopes":["tasks:write"]},
    {"access":"scoped","scopes":["capture:write","memory:read"]},
    {"access":"scoped","scopes":["capture:write","capture:write"]},
    {"access":"scoped","scopes":["mcp:access"]},
    {"access":"scoped","scopes":["capture:write"],"family_read":True},
    {"access":"read_only","scopes":["tasks:read"]},
    {"access":"scoped","scopes":["capture:write"],"scope":"memory:write"},
])
def test_invalid_token_requests_rejected(client,extra):
    response=client.post("/api/auth/mcp-token",json={"username":"testuser","password":"test-password",**extra})
    assert response.status_code==422,response.text


def test_jwt_scopes_cannot_be_mixed_or_elevated():
    for scope,token_use in [
        ("tasks:write","mcp"),("memory:read tasks:write","mcp"),
        ("mcp:access","mcp"),("capture:write","user"),
        ("memory:read memory:write family:read","user"),
    ]:
        token=jwt.encode({"sub":"dummy","scope":scope,"token_use":token_use,"ver":0,
            "exp":int((datetime.now(timezone.utc)+timedelta(hours=1)).timestamp())},settings.secret_key,algorithm="HS256")
        with pytest.raises(HTTPException):
            claims(token)
    assert valid_scopes(["capture:write"],"mcp")
    assert valid_scopes(["family:read"],"mcp")
    assert valid_scopes(["tasks:read","tasks:write"],"mcp")
