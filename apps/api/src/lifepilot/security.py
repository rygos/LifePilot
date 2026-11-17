from datetime import datetime, timedelta, timezone
import jwt
from pwdlib import PasswordHash
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from lifepilot.config import settings
from lifepilot.db import get_db
from lifepilot.models import User

password_hash = PasswordHash.recommended()
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

def hash_password(password: str) -> str: return password_hash.hash(password)
def verify_password(password: str, hashed: str) -> bool: return password_hash.verify(password, hashed)
def create_token(user_id: str) -> str:
    return jwt.encode({"sub": user_id, "exp": datetime.now(timezone.utc) + timedelta(hours=12)}, settings.secret_key, algorithm="HS256")
def current_user(token: str = Depends(oauth2), db: Session = Depends(get_db)) -> User:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        user = db.get(User, payload.get("sub"))
    except (jwt.InvalidTokenError, TypeError):
        user = None
    if user is None: raise HTTPException(status_code=401, detail="Ungültige Anmeldung", headers={"WWW-Authenticate": "Bearer"})
    return user

def resolve_bearer_user(token: str, db: Session) -> User:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        user = db.get(User, payload.get("sub"))
    except (jwt.InvalidTokenError, TypeError):
        user = None
    if user is None: raise HTTPException(status_code=401, detail="Ungültige Anmeldung")
    return user
