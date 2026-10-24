"""分科目对话 + SSE 流式（方案 4.4 / 6.5）。

方案约定 ②：对话不可删除 —— 这里不提供任何删除接口。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import Conversation, Message, User
from ..services.chat_service import get_or_create_conversation, stream_reply

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatIn(BaseModel):
    subject: str = "math"
    message: str


@router.post("/stream")
async def chat_stream(body: ChatIn, user: User = Depends(current_user)):
    async def gen():
        async for evt in stream_reply(user.id, body.subject, body.message):
            yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
        yield "data: {\"type\": \"end\"}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # 坑①：没有这个头，Nginx 会把流缓冲起来，前端就会「一次性收到」
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/conversations")
def list_conversations(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Conversation).where(Conversation.user_id == user.id).order_by(Conversation.id)
    ).all()
    out = []
    for c in rows:
        last = db.scalar(
            select(Message)
            .where(Message.conversation_id == c.id)
            .order_by(desc(Message.id))
            .limit(1)
        )
        cnt = db.query(Message).filter(Message.conversation_id == c.id).count()
        out.append(
            {
                "id": c.id,
                "subject": c.subject_key,
                "title": c.title,
                "messages": cnt,
                "last_message": (last.content[:60] if last else ""),
                "deletable": False,
            }
        )
    return out


@router.post("/ensure")
def ensure_conversation(subject: str = Query("math"), user: User = Depends(current_user),
                        db: Session = Depends(get_db)):
    conv = get_or_create_conversation(db, user.id, subject)
    db.commit()
    return {"conversation_id": conv.id, "subject": conv.subject_key}


@router.get("/messages")
def get_messages(conversation_id: int, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    conv = db.get(Conversation, conversation_id)
    if not conv or conv.user_id != user.id:
        return []
    rows = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id)
    ).all()
    return [
        {"id": m.id, "role": m.role, "content": m.content,
         "created_at": m.created_at.isoformat()}
        for m in rows
    ]
