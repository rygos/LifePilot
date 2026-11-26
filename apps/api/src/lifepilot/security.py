from datetime import datetime, timedelta, timezone
from typing import Literal
import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session
from lifepilot.config import settings
from lifepilot.db import get_db
from lifepilot.models import User

password_hash = PasswordHash.recommended()
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/token")
SCOPES = {"memory:read","memory:write","family:read"}
PLACEHOLDERS = {"development-only-change-me","replace-with-a-long-random-secret","change-this-password","replace-with-a-long-random-password"}

def validate_secret_key():
    value=settings.secret_key
    if len(value.encode())<32 or value.strip().lower() in PLACEHOLDERS or not value.strip():
        raise RuntimeError("SECRET_KEY muss durch einen zufälligen Schlüssel mit mindestens 32 Byte ersetzt werden")

def validate_bootstrap_password():
    value=settings.life_pilot_bootstrap_password
    if not 12<=len(value)<=128 or value.strip().lower() in PLACEHOLDERS or not value.strip():
        raise RuntimeError("LIFE_PILOT_BOOTSTRAP_PASSWORD für neue Konten muss ein individuelles Passwort mit 12–128 Zeichen sein")

def hash_password(password: str) -> str: return password_hash.hash(password)
def verify_password(password: str, hashed: str) -> bool:
    try:
        return password_hash.verify(password, hashed)
    except (UnknownHashError, ValueError):
        return False

def create_token(user_id: str, scopes: list[str] | None = None, token_use: Literal["user", "mcp"] = "user", token_version: int = 0) -> str:
    granted_scopes = scopes if scopes is not None else (["memory:read"] if token_use=="mcp" else ["memory:read", "memory:write"])
    claims = {"sub": user_id, "ver": token_version, "scope": " ".join(granted_scopes), "token_use":token_use, "exp": datetime.now(timezone.utc) + timedelta(hours=12)}
    return jwt.encode(claims, settings.secret_key, algorithm="HS256")

def unauthorized():
    return HTTPException(status_code=401, detail="Ungültige Anmeldung", headers={"WWW-Authenticate": "Bearer","Cache-Control":"no-store"})

def claims(token: str):
    if len(token)>8192:
        raise unauthorized()
    try:
        payload=jwt.decode(token, settings.secret_key, algorithms=["HS256"], options={"require":["sub","ver","scope","token_use","exp"]})
    except (jwt.InvalidTokenError,TypeError,ValueError,OverflowError):
        raise unauthorized() from None
    if (not isinstance(payload["sub"],str) or not 1<=len(payload["sub"])<=36
        or type(payload["ver"]) is not int or payload["ver"]<0
        or type(payload["exp"]) is not int
        or payload["token_use"] not in ("user","mcp")
        or not isinstance(payload["scope"],str)
        or not set(payload["scope"].split()).issubset(SCOPES)
        or "memory:read" not in payload["scope"].split()):
        raise unauthorized()
    return payload

def resolve_bearer_scopes(token: str) -> list[str]:
    return claims(token)["scope"].split()

def resolve_bearer_token_use(token: str) -> str:
    return claims(token)["token_use"]

def user_for_claims(payload,db):
    user=db.scalar(select(User).where(User.id==payload["sub"],User.deleted_at.is_(None)))
    if user is None or payload["ver"]!=user.token_version:
        raise unauthorized()
    return user

def current_user(token: str = Depends(oauth2), db: Session = Depends(get_db)) -> User:
    payload=claims(token)
    user=user_for_claims(payload,db)
    if payload["token_use"]!="user":
        raise HTTPException(status_code=403, detail="MCP-Token kann keine Benutzeraktion bestätigen")
    return user

def resolve_bearer_user(token: str, db: Session) -> User:
    return user_for_claims(claims(token),db)
