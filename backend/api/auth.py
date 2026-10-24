"""注册 / 登录。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import User
from ..security import create_token, hash_password, verify_password
from ..services.profile.builder import get_or_create_profile

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    password: str = Field(min_length=6, max_length=64)
    nickname: str = ""


class LoginIn(BaseModel):
    username: str
    password: str


def _pub(user: User):
    return {"id": user.id, "username": user.username, "nickname": user.nickname}


@router.post("/register")
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(400, "用户名已存在")
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        nickname=body.nickname or body.username,
    )
    db.add(user)
    db.flush()
    get_or_create_profile(db, user.id)  # 建画像
    db.commit()
    return {"token": create_token(user.id), "user": _pub(user)}


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "用户名或密码错误")
    get_or_create_profile(db, user.id)
    db.commit()
    return {"token": create_token(user.id), "user": _pub(user)}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return _pub(user)
