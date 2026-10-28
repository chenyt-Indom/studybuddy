"""数据库连接与会话。SQLite 起步，表结构按方案第十三章一次建全。"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DB_URL

# 连接池为什么要调大：
#   页面一切换就会并发打好几个接口（看板 7 个、档案 5 个…），
#   同时可能还有 SSE 流在跑、后台 _post_process 任务在写库。
#   默认 QueuePool 只有 5+10，实测会打出
#   "QueuePool limit of size 5 overflow 10 reached" → 接口 500。
#   SQLite 的连接就是一个文件句柄，放宽到 10+20 很便宜。
engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False},
    pool_size=10,
    max_overflow=20,
    pool_timeout=15,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI 依赖注入用。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """后台任务用（异步后处理管道）。"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _ensure_columns() -> None:
    """轻量迁移：SQLite 加列。create_all 不会给已有表补列，这里手动补。"""
    from sqlalchemy import text

    wanted = {
        "messages": {
            "reasoning": "TEXT",
            "sources": "TEXT",
            "attachments": "TEXT",
        },
        "textbook_sections": {
            "content": "TEXT",
        },
        "knowledge_points": {
            "grade": "VARCHAR(16) DEFAULT 'all'",
            "module": "VARCHAR(32) DEFAULT ''",
            "summary": "TEXT",
            "pitfall": "TEXT",
            "mnemonic": "TEXT",
            "keywords": "VARCHAR(200)",
        },
        "memories": {
            "scope": "VARCHAR(16) DEFAULT 'subject'",
            "evidence": "TEXT",
            "source": "VARCHAR(16) DEFAULT 'chat'",
            "source_message_id": "INTEGER",
            "confidence": "FLOAT DEFAULT 0.6",
            "accuracy": "VARCHAR(16) DEFAULT 'unverified'",
            "pinned": "BOOLEAN DEFAULT 0",
            "superseded": "BOOLEAN DEFAULT 0",
            "superseded_by": "INTEGER",
            "updated_at": "DATETIME",
            "verified_at": "DATETIME",
        },
        "textbooks": {
            "edition_code": "VARCHAR(16) DEFAULT ''",
            "edition_name": "VARCHAR(64) DEFAULT ''",
            "edition_year": "INTEGER",
            "latest_check_at": "DATETIME",
            "latest_verdict": "TEXT",
            "latest_sources": "TEXT",
        },
    }
    with engine.connect() as conn:
        for table, cols in wanted.items():
            try:
                rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            except Exception:
                continue
            existing = {r[1] for r in rows}
            if not existing:
                continue
            for name, ddl in cols.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))

        # 数据迁移：老版本用 subject_key 为空表示"全局"，现在有了 scope 字段
        try:
            conn.execute(text(
                "UPDATE memories SET scope = 'global' "
                "WHERE subject_key IS NULL AND (scope IS NULL OR scope = 'subject')"
            ))
        except Exception:
            pass
        conn.commit()


def _migrate_drop_college() -> None:
    """v0.1.13 起产品只做 小学→高中，大学学段下线。

    老库里的 stage='college' / grade='college_*' 统一归到高三，
    否则画像还在"大学"，知识点页却选不到对应学段，用户会看到空白。
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        try:
            n1 = conn.execute(text(
                "UPDATE user_profiles SET stage='senior' WHERE stage='college'"
            )).rowcount
            n2 = conn.execute(text(
                "UPDATE user_profiles SET grade='senior_3' WHERE grade LIKE 'college%'"
            )).rowcount
            if n1 or n2:
                print(f"[migrate] 大学学段已下线，{n1} 条 stage、{n2} 条 grade 归入高三")
        except Exception:
            pass        # 表还不存在等情况，忽略即可


def init_db() -> None:
    from . import models  # noqa: F401  注册所有表
    from .seeds import load_seeds
    from .seeds_textbook import load_textbook_seeds

    Base.metadata.create_all(engine)
    _ensure_columns()
    load_seeds()
    load_textbook_seeds()
    _migrate_drop_college()
