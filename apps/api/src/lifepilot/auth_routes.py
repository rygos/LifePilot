from typing import Literal, Self

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from lifepilot.db import get_db
from lifepilot.models import User
from lifepilot.security import current_user, hash_password, verify_password

router = APIRouter()


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=128)

    @model_validator(mode="after")
    def new_password_must_differ(self) -> Self:
        if self.new_password == self.current_password:
            raise ValueError("Das neue Passwort muss sich vom aktuellen unterscheiden")
        return self


class PasswordChangeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["password_changed"]


@router.post("/api/auth/password", response_model=PasswordChangeResponse)
def change_password(
    data: PasswordChangeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> PasswordChangeResponse:
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Das aktuelle Passwort ist falsch")
    user.password_hash = hash_password(data.new_password)
    db.commit()
    return PasswordChangeResponse(status="password_changed")
