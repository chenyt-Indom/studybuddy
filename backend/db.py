"""数据库连接与会话。SQLite 起步，表结构按方案第十三章一次建全。"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DB_URL

engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False},
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


def init_db() -> None:
    from . import models  # noqa: F401  注册所有表
    from .seeds import load_seeds

    Base.metadata.create_all(engine)
    _ensure_columns()
    load_seeds()
