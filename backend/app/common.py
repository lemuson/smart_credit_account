from typing import Annotated

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_session


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, str_strip_whitespace=True)


def session_dependency(request: Request):
    yield from get_session(request)


DB = Annotated[Session, Depends(session_dependency, scope="function")]


def fail(http_status: int, code: str, **context):
    raise HTTPException(http_status, detail={"code": code, **context})
