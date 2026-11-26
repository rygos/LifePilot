"""Database-backed login budgets, shared across workers and login entrypoints."""
import hashlib
import hmac
import time
from threading import BoundedSemaphore

from fastapi import HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError

from lifepilot.config import settings
from lifepilot.models import LoginBudget, User
from lifepilot.security import hash_password, verify_password

# Equal-cost verification for nonexistent/deactivated accounts.
DUMMY_HASH = hash_password("non-account-dummy-verification-value")
HASH_SLOTS = BoundedSemaphore(4)


def clock():
    return int(time.time())


def budget_key(kind, identity):
    digest=hmac.new(settings.secret_key.encode(),identity.encode(),hashlib.sha256).hexdigest()
    return kind+":"+digest


def limited(seconds):
    return HTTPException(429,"Zu viele Anmeldeversuche. Bitte später erneut versuchen.",headers={"Retry-After":str(max(1,seconds)),"Cache-Control":"no-store"})


def increment(db,key,period,limit,now):
    expiry=(now//period+1)*period
    insert=pg_insert if db.get_bind().dialect.name=="postgresql" else sqlite_insert
    stmt=insert(LoginBudget).values(key=key,count=1,expires_at=expiry)
    # Atomic on both supported engines; never extend a blocked window.
    stmt=stmt.on_conflict_do_update(index_elements=[LoginBudget.key],
        set_={"count":LoginBudget.count+1},
        where=(LoginBudget.count<limit)&(LoginBudget.expires_at==expiry))
    result=db.execute(stmt)
    if result.rowcount!=1:
        raise limited(expiry-now)


def reserve(db,request,username):
    now=clock()
    # Do not inspect untrusted X-Forwarded-For ourselves. The ASGI server may
    # supply a client IP only from its configured trusted reverse proxies.
    peer=request.client.host if request.client else "unknown"
    account=budget_key("account",username.casefold())
    try:
        db.execute(delete(LoginBudget).where(LoginBudget.expires_at<=now))
        increment(db,"global",60,settings.login_global_per_minute,now)
        increment(db,budget_key("peer",peer),60,settings.login_peer_per_minute,now)
        # Commit the global/peer attempt even when the account budget is exhausted.
        db.commit()
        increment(db,account,600,settings.login_account_per_10_minutes,now)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(503,"Anmeldeschutz vorübergehend nicht verfügbar") from None
    return account


def authenticate(db,request:Request,username:str,password:str):
    if not 1<=len(username)<=120 or not 1<=len(password)<=1024:
        raise HTTPException(401,"Benutzername oder Passwort falsch")
    account=reserve(db,request,username)
    if not HASH_SLOTS.acquire(blocking=False):
        raise limited(1)
    try:
        user=db.scalar(select(User).where(User.username==username,User.deleted_at.is_(None)).with_for_update().execution_options(populate_existing=True))
        valid=verify_password(password,user.password_hash if user is not None else DUMMY_HASH)
        if user is None or not valid:
            db.rollback()
            raise HTTPException(401,"Benutzername oder Passwort falsch",headers={"Cache-Control":"no-store"})
        # Successful login resets only the account budget, not global/IP budgets.
        db.execute(delete(LoginBudget).where(LoginBudget.key==account))
        return user
    finally:
        HASH_SLOTS.release()


class LoginBodyLimit:
    """Bound unauthenticated credential bodies before framework parsing."""
    PATHS={"/api/auth/login","/api/auth/token","/api/auth/mcp-token","/api/auth/password"}
    LIMIT=16*1024

    def __init__(self,app):
        self.app=app

    async def __call__(self,scope,receive,send):
        if scope["type"]!="http" or scope["method"]!="POST" or scope["path"].rstrip("/") not in self.PATHS:
            return await self.app(scope,receive,send)
        from starlette.responses import JSONResponse
        data=bytearray()
        while True:
            message=await receive()
            if message["type"]=="http.disconnect":
                return
            chunk=message.get("body",b"")
            if len(data)+len(chunk)>self.LIMIT:
                return await JSONResponse({"detail":"Anmeldeanfrage zu groß"},status_code=413,headers={"Cache-Control":"no-store"})(scope,receive,send)
            data.extend(chunk)
            if not message.get("more_body",False):
                break
        delivered=False
        async def replay():
            nonlocal delivered
            if delivered:
                return await receive()
            delivered=True
            return {"type":"http.request","body":bytes(data),"more_body":False}
        return await self.app(scope,replay,send)
