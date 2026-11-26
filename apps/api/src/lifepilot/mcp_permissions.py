"""Explicitly granted MCP domains. Legacy memory scopes retain their old meaning."""
from typing import Literal, get_args

DomainScope = Literal[
    "capture:write", "capture:read",
    "tasks:read", "tasks:write",
    "notes:read", "notes:write",
    "people:read", "people:write",
    "projects:read", "projects:write",
    "calendar:read", "calendar:write",
    "documents:read", "family:read",
]
DOMAIN_SCOPES = frozenset(get_args(DomainScope))
LEGACY_SCOPES = frozenset({"memory:read", "memory:write", "family:read"})
ALL_SCOPES = DOMAIN_SCOPES | LEGACY_SCOPES
# Internal transport scope, never accepted from a caller or stored in a JWT.
TRANSPORT_SCOPE = "mcp:access"
WRITE_REQUIRES_READ = {
    name + ":write": name + ":read"
    for name in ("tasks", "notes", "people", "projects", "calendar")
}


def valid_scopes(scopes, token_use):
    values = set(scopes)
    if not values or len(values) != len(scopes) or not values <= ALL_SCOPES:
        return False
    if token_use == "user":
        return values == {"memory:read", "memory:write"}
    if token_use != "mcp":
        return False
    if values & {"memory:read", "memory:write"}:
        return values <= LEGACY_SCOPES and "memory:read" in values
    return all(read in values for write, read in WRITE_REQUIRES_READ.items() if write in values)


def permits(scopes, required):
    if required not in ALL_SCOPES:
        return False
    values = set(scopes)
    if required in values:
        return True
    # Family data always needs an independent grant. No domain token inherits
    # the old broad memory scopes or another domain's capabilities.
    if required in DOMAIN_SCOPES and required != "family:read":
        return "memory:" + required.rsplit(":", 1)[1] in values
    return False
