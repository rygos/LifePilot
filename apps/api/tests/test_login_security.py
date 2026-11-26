from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from lifepilot import login_guard
from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.models import LoginBudget, User
from lifepilot.security import create_token, hash_password, validate_bootstrap_password, validate_secret_key


@pytest.fixture
def clean_budgets():
    def clear():
        with Session(engine) as db:
            db.execute(delete(LoginBudget));db.commit()
    clear()
    yield
    clear()


def account():
    username="security-"+uuid4().hex
    with Session(engine) as db:
        user=User(username=username,password_hash=hash_password("valid-password-123"))
        db.add(user);db.commit()
        return user.id,username


def test_login_budget_shared_across_entrypoints_and_fixed_expiry(client,monkeypatch,clean_budgets):
    monkeypatch.setattr(settings,"login_account_per_10_minutes",3)
    tick=1800000001
    monkeypatch.setattr(login_guard,"clock",lambda:tick)
    _,username=account()
    bad={"username":username,"password":"incorrect"}
    assert client.post("/api/auth/login",json=bad).status_code==401
    assert client.post("/api/auth/token",data=bad).status_code==401
    assert client.post("/api/auth/mcp-token",json=bad).status_code==401
    good={"username":username,"password":"valid-password-123"}
    blocked=client.post("/api/auth/login",json=good)
    assert blocked.status_code==429 and blocked.headers["Retry-After"]=="599"
    assert client.post("/api/auth/mcp-token",json=good,headers={"X-Forwarded-For":"203.0.113.2"}).status_code==429
    tick+=600
    success=client.post("/api/auth/login",json=good)
    assert success.status_code==200 and success.headers["Cache-Control"]=="no-store"
    with Session(engine) as db:
        assert db.get(LoginBudget,login_guard.budget_key("account",username.casefold())) is None
        assert all(row.expires_at>tick for row in db.scalars(select(LoginBudget)))
    assert client.post("/api/auth/login",json=bad).status_code==401
    assert client.post("/api/auth/login",json=good).status_code==200
    assert client.post("/api/auth/login",json=bad).status_code==401


def test_peer_limit_unknown_accounts_and_no_secret_echo(client,monkeypatch,clean_budgets):
    monkeypatch.setattr(settings,"login_peer_per_minute",5)
    monkeypatch.setattr(login_guard,"clock",lambda:1800000001)
    for i in range(5):
        response=client.post("/api/auth/login",json={"username":f"missing-{i}","password":"secret"},headers={"X-Forwarded-For":f"198.51.100.{i}"})
        assert response.status_code==401
    assert client.post("/api/auth/login",json={"username":"missing-6","password":"secret"}).status_code==429
    secret="sensitive-value-"*100
    response=client.post("/api/auth/login",json={"username":"test","password":secret})
    assert response.status_code==422
    assert secret not in response.text and "sensitive-value" not in response.text
    assert client.post("/api/auth/token",data={"username":"test","password":"a"*17000}).status_code==413


def test_jwt_claims_are_explicit_and_legacy_tokens_rejected(client):
    uid,_=account()
    now=datetime.now(timezone.utc)
    payload={"sub":uid,"ver":0,"scope":"memory:read memory:write","token_use":"user","exp":int((now+timedelta(hours=1)).timestamp())}
    for field in payload:
        invalid={k:v for k,v in payload.items() if k!=field}
        token=jwt.encode(invalid,settings.secret_key,algorithm="HS256")
        assert client.get("/api/auth/me",headers={"Authorization":"Bearer "+token}).status_code==401
    for override in ({"ver":True},{"ver":-1},{"scope":"memory:read admin"},{"token_use":"other"},{"exp":1},{"sub":[]},{"exp":"invalid"}):
        token=jwt.encode({**payload,**override},settings.secret_key,algorithm="HS256")
        assert client.get("/api/auth/me",headers={"Authorization":"Bearer "+token}).status_code==401
    assert client.get("/api/auth/me",headers={"Authorization":"Bearer "+create_token(uid)}).status_code==200


def test_insecure_bootstrap_values_rejected(monkeypatch):
    for key in ("development-only-change-me","replace-with-a-long-random-secret","short"):
        monkeypatch.setattr(settings,"secret_key",key)
        with pytest.raises(RuntimeError,match="SECRET_KEY"):
            validate_secret_key()
    monkeypatch.setattr(settings,"secret_key","c"*64)
    validate_secret_key()
    for pwd in ("change-this-password","short"," "*20):
        monkeypatch.setattr(settings,"life_pilot_bootstrap_password",pwd)
        with pytest.raises(RuntimeError,match="BOOTSTRAP_PASSWORD"):
            validate_bootstrap_password()
    monkeypatch.setattr(settings,"life_pilot_bootstrap_password","a-valid-individual-password")
    validate_bootstrap_password()


def test_global_limit_and_mcp_default_readonly(client,monkeypatch,clean_budgets):
    from lifepilot.security import resolve_bearer_scopes
    monkeypatch.setattr(settings,"login_global_per_minute",10)
    monkeypatch.setattr(settings,"login_peer_per_minute",100)
    monkeypatch.setattr(login_guard,"clock",lambda:1800000001)
    for i in range(10):
        assert client.post("/api/auth/login",json={"username":f"unknown-{i}","password":"wrong"}).status_code==401
    assert client.post("/api/auth/login",json={"username":"unknown-11","password":"wrong"}).status_code==429
    uid,_=account()
    assert resolve_bearer_scopes(create_token(uid,token_use="mcp"))==["memory:read"]
