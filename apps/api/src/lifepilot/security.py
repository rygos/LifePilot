from datetime import datetime, timedelta, timezone
from typing import Literal
import jwt
from pwdlib import PasswordHash
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session
from lifepilot.config import settings
from lifepilot.db import get_db
from lifepilot.models import User

password_hash = PasswordHash.recommended()
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

def hash_password(password: str) -> str: return password_hash.hash(password)
def verify_password(password: str, hashed: str) -> bool: return password_hash.verify(password, hashed)
def create_token(user_id: str, scopes: list[str] | None = None, token_use: Literal["user", "mcp"] = "user") -> str:
    granted_scopes = scopes if scopes is not None else ["memory:read", "memory:write"]
    claims = {"sub": user_id, "scope": " ".join(granted_scopes), "exp": datetime.now(timezone.utc) + timedelta(hours=12)}
    if token_use == "mcp":
        claims["token_use"] = "mcp"
    return jwt.encode(claims, settings.secret_key, algorithm="HS256")

def resolve_bearer_scopes(token: str) -> list[str]:
    payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    return str(payload.get("scope", "memory:read memory:write")).split()

def resolve_bearer_token_use(token: str) -> str:
    payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    return str(payload.get("token_use", "user"))
def current_user(token: str = Depends(oauth2), db: Session = Depends(get_db)) -> User:
    token_use = "user"
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        token_use = str(payload.get("token_use", "user"))
        user = db.scalar(select(User).where(User.id == payload.get("sub"), User.deleted_at.is_(None)))
    except (jwt.InvalidTokenError, TypeError):
        user = None
    if user is None: raise HTTPException(status_code=401, detail="Ungültige Anmeldung", headers={"WWW-Authenticate": "Bearer"})
    if token_use == "mcp": raise HTTPException(status_code=403, detail="MCP-Token kann keine Benutzeraktion bestätigen")
    return user

def resolve_bearer_user(token: str, db: Session) -> User:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        user = db.scalar(select(User).where(User.id == payload.get("sub"), User.deleted_at.is_(None)))
    except (jwt.InvalidTokenError, TypeError):
        user = None
    if user is None: raise HTTPException(status_code=401, detail="Ungültige Anmeldung")
    return user
