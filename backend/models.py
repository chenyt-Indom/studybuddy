"""ORM 模型 —— 对应方案第十三章表清单。

命名对齐方案，方便后续交接。
"""
from __future__ import annotations

from datetime import datetime, date

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _now() -> datetime:
    return datetime.now()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    nickname: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    profile: Mapped["UserProfile"] = relationship(back_populates="user", uselist=False)


class UserProfile(Base):
    """⭐ 四维画像（方案 5.1 / DDL 13.2）。"""

    __tablename__ = "user_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)

    # ① 学业基础
    stage: Mapped[str] = mapped_column(String(16), default="senior")  # primary/junior/senior
    grade: Mapped[str] = mapped_column(String(16), default="senior_1")
    target_major: Mapped[str | None] = mapped_column(String(128), default=None)
    electives: Mapped[str | None] = mapped_column(String(64), default=None)  # JSON 数组
    target_score: Mapped[int | None] = mapped_column(Integer, default=None)

    # ② 认知风格（推断得出）
    style_scores: Mapped[str | None] = mapped_column(String(256), default=None)
    primary_style: Mapped[str | None] = mapped_column(String(16), default=None)
    style_confidence: Mapped[float] = mapped_column(Float, default=0.0)

    # ③ 学习习惯
    preferred_hours: Mapped[str | None] = mapped_column(String(64), default=None)
    avg_study_minutes: Mapped[int] = mapped_column(Integer, default=0)
    streak_days: Mapped[int] = mapped_column(Integer, default=0)

    # ④ 心理状态
    confidence_level: Mapped[float] = mapped_column(Float, default=0.5)
    anxiety_level: Mapped[float] = mapped_column(Float, default=0.3)
    motivation: Mapped[float] = mapped_column(Float, default=0.5)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    user: Mapped[User] = relationship(back_populates="profile")


class Conversation(Base):
    """分科目对话。方案约定 ②：不可删除，不提供删除接口。"""

    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("user_id", "subject_key", name="uq_conv_user_subject"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(128), default="")
    stage: Mapped[str] = mapped_column(String(16), default="senior")
    is_deletable: Mapped[int] = mapped_column(Integer, default=0)  # 恒为 0
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("idx_msg_conv", "conversation_id", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user / assistant / system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # DeepSeek 思考模式的思维链。存下来是为了回翻历史时还能展开看
    reasoning: Mapped[str | None] = mapped_column(Text, default=None)
    # 本次回答引用的网页来源（JSON 数组）
    sources: Mapped[str | None] = mapped_column(Text, default=None)
    # 用户上传的图片附件（JSON 数组，元素为附件 id，见 services/attachments.py）
    attachments: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class KbSnippet(Base):
    """外部教材知识库（IMA）检索到的片段缓存。

    只存**片段 + 出处**：不存整本正文，不外传。
    作用：没网/没 token 时，之前同步过的片段还能继续给讲解当参考。
    """

    __tablename__ = "kb_snippets"
    __table_args__ = (UniqueConstraint("user_id", "hash", name="uq_kb_snippet"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    hash: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), default="")
    snippet: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(String(500), default="")
    source: Mapped[str] = mapped_column(String(80), default="IMA")
    stage: Mapped[str] = mapped_column(String(16), default="")
    grade: Mapped[str] = mapped_column(String(16), default="")
    subject_key: Mapped[str] = mapped_column(String(32), default="")
    query: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class WeeklyReport(Base):
    """学习周报：每用户每自然周一份（可重算覆盖）。

    为什么落库而不是每次现算：
      周报是"给过去的自己留的凭据"，下周再看要能对比；
      而 LLM 生成的文本不可复现，存下来才有对比价值。
    """

    __tablename__ = "weekly_reports"
    __table_args__ = (UniqueConstraint("user_id", "week_start", name="uq_weekly"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    week_end: Mapped[date] = mapped_column(Date, nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")     # Markdown 正文
    stats: Mapped[str | None] = mapped_column(Text, default=None)  # 数据快照（JSON）
    source: Mapped[str] = mapped_column(String(16), default="rule")  # llm / rule
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Grade(Base):
    __tablename__ = "grades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(32), nullable=False)
    exam_name: Mapped[str] = mapped_column(String(128), default="")
    score: Mapped[float] = mapped_column(Float, default=0)
    full_score: Mapped[float] = mapped_column(Float, default=100)
    exam_date: Mapped[date | None] = mapped_column(Date, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class QuestionRecord(Base):
    """⭐ 逐题记录 —— 题型分层分析的唯一数据源（方案 13.3）。"""

    __tablename__ = "question_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(32), nullable=False)
    exam_id: Mapped[int | None] = mapped_column(ForeignKey("grades.id"), default=None)
    q_no: Mapped[int] = mapped_column(Integer, nullable=False)
    kp_code: Mapped[str | None] = mapped_column(String(64), default=None)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=True)
    score: Mapped[float] = mapped_column(Float, default=0)
    full_score: Mapped[float] = mapped_column(Float, default=0)
    max_tier: Mapped[str | None] = mapped_column(String(16), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"

    kp_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    subject_key: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    stage: Mapped[str] = mapped_column(String(16), default="senior")
    # 第一次系统学这个知识点的年级；"all" = 贯穿型（比例、阅读理解这类跨年级能力）
    grade: Mapped[str] = mapped_column(String(16), default="all")
    # 模块（函数 / 力学 / 反应原理 ……），汇总页按它分组
    module: Mapped[str] = mapped_column(String(32), default="")
    importance: Mapped[float] = mapped_column(Float, default=0.5)  # 考频/依赖数 → 重要度
    difficulty: Mapped[int] = mapped_column(Integer, default=3)
    # 一句话要点 / 常见易错 / 记忆锚点 —— 「知识点提示」的三个落点
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    pitfall: Mapped[str | None] = mapped_column(Text, default=None)
    mnemonic: Mapped[str | None] = mapped_column(Text, default=None)
    keywords: Mapped[str | None] = mapped_column(String(200), default=None)


class KpDependency(Base):
    """⭐ 知识点依赖关系 —— P4 知识断层识别用。"""

    __tablename__ = "kp_dependency"
    __table_args__ = (UniqueConstraint("kp_code", "depends_on", name="uq_kp_dep"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kp_code: Mapped[str] = mapped_column(String(64), nullable=False)
    depends_on: Mapped[str] = mapped_column(String(64), nullable=False)


class CrossSubjectLink(Base):
    """⭐ 跨科目关联 —— 跨科目引擎用。"""

    __tablename__ = "cross_subject_link"
    __table_args__ = (
        UniqueConstraint("from_kp", "to_kp", "relation_type", name="uq_cross_link"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_kp: Mapped[str] = mapped_column(String(64), nullable=False)
    to_kp: Mapped[str] = mapped_column(String(64), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(32), default="concept_shared")
    strength: Mapped[float] = mapped_column(Float, default=0.5)
    note: Mapped[str | None] = mapped_column(Text, default=None)


class KpMastery(Base):
    __tablename__ = "kp_mastery"
    __table_args__ = (
        UniqueConstraint("user_id", "subject_key", "kp_code", name="uq_mastery"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(32), nullable=False)
    kp_code: Mapped[str] = mapped_column(String(64), nullable=False)
    mastery: Mapped[float] = mapped_column(Float, default=0.5)
    score_rate: Mapped[float] = mapped_column(Float, default=0.5)
    error_rate: Mapped[float] = mapped_column(Float, default=0.0)
    mention_rate: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class ReviewState(Base):
    """⭐ SM-2 复习状态。"""

    __tablename__ = "review_state"
    __table_args__ = (
        UniqueConstraint("user_id", "kp_code", name="uq_review_user_kp"),
        Index("idx_review_due", "user_id", "next_review"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(32), nullable=False)
    kp_code: Mapped[str] = mapped_column(String(64), nullable=False)
    # SM-2 三参数
    ef: Mapped[float] = mapped_column(Float, default=2.5)
    interval: Mapped[int] = mapped_column(Integer, default=1)
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    next_review: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_review: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    source: Mapped[str | None] = mapped_column(String(16), default=None)
    source_id: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ReviewLog(Base):
    __tablename__ = "review_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    kp_code: Mapped[str] = mapped_column(String(64), nullable=False)
    quality: Mapped[int] = mapped_column(Integer, nullable=False)
    ef_before: Mapped[float] = mapped_column(Float, default=2.5)
    ef_after: Mapped[float] = mapped_column(Float, default=2.5)
    interval_before: Mapped[int] = mapped_column(Integer, default=0)
    interval_after: Mapped[int] = mapped_column(Integer, default=1)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Mistake(Base):
    __tablename__ = "mistakes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(32), nullable=False)
    kp_code: Mapped[str | None] = mapped_column(String(64), default=None)
    content: Mapped[str] = mapped_column(Text, default="")
    # 六类错因：concept/calculation/careless/method/transfer/timeout
    error_type: Mapped[str | None] = mapped_column(String(16), default=None)
    tier: Mapped[str | None] = mapped_column(String(16), default=None)  # basic/medium/hard
    difficulty: Mapped[int] = mapped_column(Integer, default=3)
    image_id: Mapped[int | None] = mapped_column(Integer, default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Memory(Base):
    """长期记忆库（第八章）。

    分两层：
      scope='global'  → 跨科目的、关于"这个人"的长期特征（身份/目标/习惯/偏好/情绪基调）
      scope='subject' → 单个科目的学科记忆（薄弱点/理解误区/易错题型）

    可核查：每条都带 evidence（触发它的原话片段）和 accuracy（用户判定）。
    """

    __tablename__ = "memories"
    __table_args__ = (Index("idx_mem_user", "user_id", "scope", "subject_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    scope: Mapped[str] = mapped_column(String(16), default="subject")  # global / subject
    subject_key: Mapped[str | None] = mapped_column(String(32), default=None)
    mtype: Mapped[str] = mapped_column(String(24), default="observation")
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # 可核查性：这句话是从哪来的
    evidence: Mapped[str | None] = mapped_column(Text, default=None)
    source: Mapped[str] = mapped_column(String(16), default="chat")  # chat/manual/exam/mistake
    source_message_id: Mapped[int | None] = mapped_column(Integer, default=None)

    # 模型自评置信度（0~1），前端要如实展示，不能当成事实
    confidence: Mapped[float] = mapped_column(Float, default=0.6)

    keywords: Mapped[str] = mapped_column(String(256), default="")
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    hits: Mapped[int] = mapped_column(Integer, default=0)

    # 用户判定：unverified / correct / wrong
    accuracy: Mapped[str] = mapped_column(String(16), default="unverified")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    # 被新事实取代（归档但不删，便于回溯）
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)
    superseded_by: Mapped[int | None] = mapped_column(Integer, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class MemoryDoc(Base):
    """记忆档案（综述层）——按主题合成的大段文本，用户可直接编辑。

    和 Memory 的关系：
      Memory     = 原子事实（一条条，用于召回、带依据、可核查）
      MemoryDoc  = 整理后的综述（分节长文，给人看的、也给模型当高层背景）

    为什么要两层：截图那种「工作背景」一大段，没法逐条核查；而纯卡片又读不出全貌。
    两层各司其职：卡片负责准确，综述负责整体理解。
    """

    __tablename__ = "memory_docs"
    __table_args__ = (Index("idx_doc_user", "user_id", "order_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    section: Mapped[str] = mapped_column(String(64), default="学习背景")
    content: Mapped[str] = mapped_column(Text, default="")
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    auto_generated: Mapped[bool] = mapped_column(Boolean, default=True)
    # 用户手动编辑过的，自动整理不再覆盖（避免把用户改的字冲掉）
    user_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class MemoryMeta(Base):
    """记忆系统的用户级设置与状态。"""

    __tablename__ = "memory_meta"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    # 对话记忆：是否自动从对话里提取
    auto_extract: Mapped[bool] = mapped_column(Boolean, default=True)
    # 自动整理：每晚合并/更新记忆并重写综述
    auto_consolidate: Mapped[bool] = mapped_column(Boolean, default=True)
    last_consolidated_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    consolidate_count: Mapped[int] = mapped_column(Integer, default=0)
    last_summary: Mapped[str | None] = mapped_column(Text, default=None)


class PatternInsight(Base):
    __tablename__ = "pattern_insights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    subject_key: Mapped[str | None] = mapped_column(String(32), default=None)
    pattern_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    title: Mapped[str] = mapped_column(String(128), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    action: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[str | None] = mapped_column(Text, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(32), nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, default=1)  # 1~7
    start_time: Mapped[str] = mapped_column(String(8), default="08:00")
    end_time: Mapped[str] = mapped_column(String(8), default="09:00")


class UserRegion(Base):
    """⭐ 教材通路：地区（高德定位结果）。"""

    __tablename__ = "user_region"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    province: Mapped[str | None] = mapped_column(String(64), default=None)
    city: Mapped[str | None] = mapped_column(String(64), default=None)
    district: Mapped[str | None] = mapped_column(String(64), default=None)
    adcode: Mapped[str | None] = mapped_column(String(16), default=None)
    lng: Mapped[float | None] = mapped_column(Float, default=None)
    lat: Mapped[float | None] = mapped_column(Float, default=None)
    source: Mapped[str] = mapped_column(String(16), default="manual")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class UserTextbook(Base):
    """⭐ 教材通路：各科教材版本（用户可手动覆盖）。"""

    __tablename__ = "user_textbook"
    __table_args__ = (UniqueConstraint("user_id", "subject_key", name="uq_textbook"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(32), nullable=False)
    textbook_code: Mapped[str] = mapped_column(String(16), default="rj")
    source: Mapped[str] = mapped_column(String(16), default="auto")
    synced_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    kb_version: Mapped[str | None] = mapped_column(String(32), default=None)


class Textbook(Base):
    """教材（结构库）。

    ⚠️ 版权边界：
      · 只入库**教材结构**（章、节、知识点顺序、难度）—— 这是公开信息
      · 教材**正文**只在用户自己导入正版文件时存本地，绝不外传、不随仓库分发
      · bundled=1 的是内置公开目录（只有结构，没有正文）
    """

    __tablename__ = "textbooks"
    __table_args__ = (Index("idx_tb_lookup", "subject_key", "stage", "grade"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)

    code: Mapped[str] = mapped_column(String(32), nullable=False)      # rj_a_math_bx1
    # 版本（出版社 + 修订年）——「选教材版本」靠这两个字段区分
    edition_code: Mapped[str] = mapped_column(String(16), default="")
    edition_name: Mapped[str] = mapped_column(String(64), default="")
    edition_year: Mapped[int | None] = mapped_column(Integer, default=None)

    title: Mapped[str] = mapped_column(String(128), default="")
    subject_key: Mapped[str] = mapped_column(String(32), nullable=False)
    stage: Mapped[str] = mapped_column(String(16), default="senior")
    grade: Mapped[str] = mapped_column(String(16), default="senior_1")
    volume: Mapped[str] = mapped_column(String(32), default="")         # 必修第一册
    publisher: Mapped[str] = mapped_column(String(32), default="人教A版")
    year: Mapped[int | None] = mapped_column(Integer, default=None)

    bundled: Mapped[bool] = mapped_column(Boolean, default=False)
    file_path: Mapped[str | None] = mapped_column(String(512), default=None)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    parse_status: Mapped[str] = mapped_column(String(24), default="outline")  # outline/parsed/failed
    parse_note: Mapped[str | None] = mapped_column(Text, default=None)

    # 「确保最新」：只能靠联网核查 + 用户确认，不能靠猜
    latest_check_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    latest_verdict: Mapped[str | None] = mapped_column(Text, default=None)
    latest_sources: Mapped[str | None] = mapped_column(Text, default=None)  # JSON

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class TextbookSection(Base):
    """教材章节结构。"""

    __tablename__ = "textbook_sections"
    __table_args__ = (Index("idx_tbs_tb", "textbook_id", "order_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    textbook_id: Mapped[int] = mapped_column(ForeignKey("textbooks.id"), nullable=False)
    chapter: Mapped[str] = mapped_column(String(128), default="")
    section: Mapped[str] = mapped_column(String(128), default="")
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    # 本节覆盖的知识点（JSON 数组，必须是知识点库里已有的 kp_code）
    kp_codes: Mapped[str | None] = mapped_column(Text, default=None)
    keywords: Mapped[str] = mapped_column(String(256), default="")
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    # 仅供本地检索用的片段摘录（不对外分发）
    excerpt: Mapped[str | None] = mapped_column(Text, default=None)


class AppSetting(Base):
    """本地运行时配置（星辰 AppKey / model 等，不提交仓库）。"""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
