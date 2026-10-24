"""FastAPI 依赖：当前用户。"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import get_db
from .models import User
from .security import decode_token


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth = request.headers.get("Authorization") or ""
    token = auth[7:] if auth.lower().startswith("bearer ") else request.cookies.get("sb_token", "")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    uid = decode_token(token)
    if not uid:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    user = db.get(User, uid)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user
