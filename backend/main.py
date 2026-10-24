"""StudyBuddy 后端入口。

启动：python -m uvicorn backend.main:app --reload --port 8787
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import (
    auth,
    chat,
    cross,
    grade,
    insight,
    memory,
    mistake,
    profile,
    review,
    system,
    textbook,
)
from .config import BASE_DIR, settings
from .db import init_db

FRONTEND_DIR = BASE_DIR / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    print("=" * 62)
    print(" StudyBuddy 已启动")
    print(f"  星辰 base_url : {settings.base_url}")
    print(f"  星辰 model    : {settings.model or '(未配置)'}")
    print(f"  当前模式      : {'真实模型' if settings.configured else '离线演示（未填 AppKey）'}")
    print(f"  打开          : http://127.0.0.1:8787")
    print("=" * 62)

    # 记忆自动整理：每小时检查一次，距上次 >=20 小时就整理（等效"每晚整理"）
    task = asyncio.create_task(_auto_consolidate_loop())
    try:
        yield
    finally:
        task.cancel()


async def _auto_consolidate_loop() -> None:
    from .services.memory.consolidate import consolidate_all

    await asyncio.sleep(45)  # 启动后缓一下，别和数据库初始化抢
    while True:
        try:
            done = await consolidate_all(min_hours=20)
            for r in done:
                if r.get("ok") and r.get("mode") != "skip":
                    print(f"[记忆自动整理] user={r.get('user_id', '?')} {r.get('message')}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"[记忆自动整理] 失败：{exc}")
        await asyncio.sleep(3600)


app = FastAPI(title="StudyBuddy", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (
    auth.router,
    chat.router,
    profile.router,
    grade.router,
    review.router,
    mistake.router,
    insight.router,
    cross.router,
    memory.router,
    textbook.router,
    system.router,
):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"ok": True, "app": "StudyBuddy", "version": "0.1.0"}


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(FRONTEND_DIR / "index.html")
