"""教材通路（方案第十章）：导入教材 → 本地解析 → 结构入库 → 讲解时对齐课本。

⚠️ 版权边界（代码里也守着）：
  · 教材**正文全文**只在用户自己导入时存本地 data/textbooks/，不对外传输、不进 Git
  · 内置的 bundled 教材只有章节结构（公开目录），没有正文
  · 讲解时只用「章节定位 + 知识点顺序」，不会整段复述教材原文

为什么要这个：不合课本的最大问题不是知识点错，而是**顺序和符号约定对不上**。
学生翻书找不到，就会觉得"老师不是这么教的"。
"""
from __future__ import annotations

import json
import re
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import UPLOAD_DIR
from ..models import Textbook, TextbookSection, UserTextbook
from .kp import candidates

TEXTBOOK_DIR = UPLOAD_DIR.parent / "textbooks"
TEXTBOOK_DIR.mkdir(parents=True, exist_ok=True)

# 第X章 / 第X节 / 1.2 标题
CHAPTER_RE = re.compile(r"^\s*第\s*([一二三四五六七八九十百零〇\d]+)\s*章[、.\s]*(.*)$")
SECTION_CN_RE = re.compile(r"^\s*第\s*([一二三四五六七八九十百零〇\d]+)\s*节[、.\s]*(.*)$")
SECTION_NUM_RE = re.compile(r"^\s*(\d{1,2}[.．]\d{1,2})\s*[、.\s]*(.+)$")

MAX_TEXT_CHARS = 2_000_000  # 单本教材解析上限，防止超大 PDF 卡死


# ---------------------------------------------------------------- 文本抽取
def _extract_pdf(path: Path) -> tuple[str, int, str]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return "", 0, "缺少 pypdf，无法解析 PDF（pip install pypdf）"
    try:
        reader = PdfReader(str(path))
        chunks = []
        total = 0
        for page in reader.pages:
            t = page.extract_text() or ""
            chunks.append(t)
            total += len(t)
            if total > MAX_TEXT_CHARS:
                break
        return _normalize("\n".join(chunks)), len(reader.pages), ""
    except Exception as exc:  # noqa: BLE001
        return "", 0, f"PDF 解析失败：{exc}"


def _normalize(text: str) -> str:
    """NFKC 归一化。

    很多 PDF（WPS/Word 导出）会把汉字写成康熙部首，比如「第⼀章」的「⼀」
    是 U+2F00 而不是「一」。不归一化就识别不出章节标题（踩过）。
    """
    return unicodedata.normalize("NFKC", text or "")


def _chapter_key(name: str) -> str:
    """章节分组键：去掉序号前缀与装饰符号，避免同一章被拆成两个。"""
    k = re.sub(r"[\s\u2600-\u27BF\uFE0F\u2B00-\u2BFF]", "", name or "")
    return k or "（未分章）"


# 扫描版 PDF 走 OCR 的页数上限。
#   一次请求里 OCR 一页约 1.5~2 秒，20 页 ≈ 40 秒 —— 再往上就该用
#   scripts/ocr_pdf.py 离线整本转换了，否则前端会等到超时。
OCR_INLINE_MAX_PAGES = 20


def _extract_text(path: Path, allow_ocr: bool = True) -> tuple[str, int, str]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text, pages, err = _extract_pdf(path)
        # 文字层几乎抽不出东西 → 多半是扫描版/拍照转的 PDF，尝试 OCR 兜底
        if allow_ocr and len(text.strip()) < 200 and pages > 0:
            from . import ocr as ocr_svc
            if ocr_svc.available():
                if pages <= OCR_INLINE_MAX_PAGES:
                    ot, done, oerr = ocr_svc.ocr_pdf(path)
                    if ot.strip():
                        return _normalize(ot), pages, f"扫描版，已 OCR 前 {done} 页"
                    return "", pages, f"扫描版且 OCR 失败：{oerr}"
                return "", pages, (
                    f"扫描版 PDF 共 {pages} 页，超出一键导入上限（{OCR_INLINE_MAX_PAGES} 页）。"
                    "请用 scripts/ocr_pdf.py 先转成 txt 再导入（命令见 README）"
                )
        return text, pages, err
    if suffix in (".txt", ".md"):
        try:
            raw = path.read_text(encoding="utf-8", errors="ignore")[:MAX_TEXT_CHARS]
            return _normalize(raw), 0, ""
        except Exception as exc:  # noqa: BLE001
            return "", 0, str(exc)
    return "", 0, f"不支持的文件类型：{suffix}（支持 .pdf / .txt / .md）"


# ---------------------------------------------------------------- 结构切分
def split_structure(text: str) -> list[dict]:
    """按「第X章 / 第X节 / 1.2 标题」切分。切不出来就整本当一节。"""
    lines = text.splitlines()
    sections: list[dict] = []
    cur_chapter = ""
    cur_section = ""
    buf: list[str] = []

    def flush() -> None:
        if not (cur_chapter or cur_section):
            return
        body = "\n".join(buf).strip()
        if not body and not cur_section:
            return
        sections.append(
            {
                "chapter": cur_chapter,
                "section": cur_section or cur_chapter or "全文",
                "text": body,
            }
        )
        buf.clear()

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        m_ch = CHAPTER_RE.match(line)
        if m_ch:
            flush()
            cur_chapter = line[:120]
            cur_section = ""
            continue
        m_sec = SECTION_CN_RE.match(line) or SECTION_NUM_RE.match(line)
        if m_sec:
            flush()
            cur_section = line[:120]
            continue
        buf.append(line)

    flush()

    if not sections:
        body = text.strip()
        if body:
            sections = [{"chapter": "全文", "section": "全文", "text": body}]
    return sections


def _guess_kps(db: Session, subject_key: str, title: str, body: str) -> list[str]:
    """把章节映射到知识点。只用知识点库里已有的 code，禁止编造。"""
    probe = f"{title} {body[:400]}"
    cands = candidates(db, subject_key, probe, limit=8)
    out = []
    for c in cands:
        name = c.get("name") or ""
        if name and (name in title or name in body[:400]):
            out.append(c["kp_code"])
    return out[:4]


# ---------------------------------------------------------------- 导入
def import_file(
    db: Session,
    user_id: int,
    filename: str,
    data: bytes,
    subject_key: str,
    stage: str = "senior",
    grade: str = "senior_1",
    volume: str = "",
    publisher: str = "用户导入",
    edition_name: str = "",
    edition_year: int | None = None,
    edition_code: str = "custom",
) -> dict:
    if not data:
        return {"ok": False, "message": "文件为空"}
    if len(data) > 200 * 1024 * 1024:
        return {"ok": False, "message": "文件超过 200MB"}

    suffix = Path(filename).suffix.lower() or ".pdf"
    stored = TEXTBOOK_DIR / f"u{user_id}_{uuid.uuid4().hex[:10]}{suffix}"
    stored.write_bytes(data)

    text, pages, err = _extract_text(stored)

    code = f"user_{user_id}_{uuid.uuid4().hex[:8]}"
    title = Path(filename).stem[:100]
    tb = Textbook(
        user_id=user_id, code=code, title=title, subject_key=subject_key,
        stage=stage, grade=grade, volume=volume or "用户导入",
        publisher=publisher, bundled=False, file_path=str(stored),
        edition_code=(edition_code or "custom")[:16], edition_name=edition_name or publisher,
        edition_year=edition_year,
        page_count=pages, char_count=len(text),
        parse_status="parsed" if text else "failed",
        parse_note=err or None,
    )
    db.add(tb)
    db.flush()

    sections = split_structure(text) if text else []
    for i, sec in enumerate(sections):
        body = sec["text"]
        kps = _guess_kps(db, subject_key, sec["section"], body)
        db.add(
            TextbookSection(
                textbook_id=tb.id,
                chapter=sec["chapter"][:128],
                section=sec["section"][:128],
                order_index=i,
                kp_codes=json.dumps(kps, ensure_ascii=False),
                keywords="",
                char_count=len(body),
                # content 存全文：离线阅读和模型引用都靠它
                content=body or None,
                excerpt=body[:300] or None,
            )
        )
    db.flush()

    return {
        "ok": bool(text),
        "id": tb.id,
        "code": code,
        "title": title,
        "pages": pages,
        "chars": len(text),
        "sections": len(sections),
        "message": (
            f"已解析 {len(sections)} 节 / {len(text)} 字"
            if text else f"解析失败：{err or '未抽取到文本（可能是扫描版 PDF）'}"
        ),
    }


def import_pasted_text(db: Session, user_id: int, title: str, text: str,
                       subject_key: str, stage: str = "senior",
                       grade: str = "senior_1", volume: str = "",
                       publisher: str = "手动粘贴") -> dict:
    """粘贴正文导入：把从别处（IMA / 电子书 / 笔记）复制的**正文**切章节入库。

    为什么单独做这条路：API 拿不到内容时，用户手上其实是有内容的（能看能复制），
    卡住的只是"怎么送进来"。复制一段粘进来，30 秒就能变成可读、可检索的课本。
    """
    text = (text or "").strip()
    if len(text) < 80:
        return {"ok": False, "message": "内容太短（至少 80 字），粘贴完整一点"}

    code = f"user_{user_id}_{uuid.uuid4().hex[:8]}"
    tb = Textbook(
        user_id=user_id, code=code, title=(title or "粘贴的教材")[:100],
        subject_key=subject_key, stage=stage, grade=grade,
        volume=volume or "粘贴导入", publisher=publisher,
        bundled=False, file_path=None,
        edition_code="paste", edition_name=publisher,
        page_count=0, char_count=len(text),
        parse_status="parsed", parse_note="由粘贴正文导入",
    )
    db.add(tb)
    db.flush()

    secs = split_structure(text)
    for i, sec in enumerate(secs):
        body = sec["text"]
        kps = _guess_kps(db, subject_key, sec["section"], body)
        db.add(TextbookSection(
            textbook_id=tb.id,
            chapter=sec["chapter"][:128], section=sec["section"][:128],
            order_index=i, kp_codes=json.dumps(kps, ensure_ascii=False),
            keywords="", char_count=len(body),
            content=body or None, excerpt=body[:300] or None,
        ))
    db.flush()
    return {"ok": True, "id": tb.id, "title": tb.title,
            "sections": len(secs), "chars": len(text),
            "message": f"已切出 {len(secs)} 节 / {len(text)} 字"}


def import_outline_text(
    db: Session, user_id: int, raw: str, subject_key: str,
    stage: str = "senior", grade: str = "senior_1",
    volume: str = "手抄目录", publisher: str = "用户录入",
    title: str = "自定义教材目录", edition_code: str = "custom",
) -> dict:
    """粘贴目录文本导入。每行一条：`第一章 集合 | 1.1 集合的概念 | 集合,元素`"""
    lines = [l.strip() for l in (raw or "").splitlines() if l.strip()]
    if not lines:
        return {"ok": False, "message": "目录为空"}

    code = f"user_{user_id}_{uuid.uuid4().hex[:8]}"
    tb = Textbook(
        user_id=user_id, code=code, title=title[:100], subject_key=subject_key,
        stage=stage, grade=grade, volume=volume, publisher=publisher,
        bundled=False, parse_status="outline",
        edition_code=(edition_code or "custom")[:16],
        parse_note="用户粘贴的目录（仅结构）",
    )
    db.add(tb)
    db.flush()

    n = 0
    for i, line in enumerate(lines):
        parts = [p.strip() for p in re.split(r"[|｜\t]", line)]
        chapter = parts[0] if parts else line
        section = parts[1] if len(parts) > 1 else ""
        kw = parts[2] if len(parts) > 2 else ""
        kps = _guess_kps(db, subject_key, f"{chapter} {section}", kw)
        db.add(
            TextbookSection(
                textbook_id=tb.id, chapter=chapter[:128], section=section[:128],
                order_index=i, kp_codes=json.dumps(kps, ensure_ascii=False),
                keywords=kw, char_count=0,
            )
        )
        n += 1
    db.flush()
    return {"ok": True, "id": tb.id, "code": code, "sections": n,
            "message": f"已导入 {n} 条目录"}


# ---------------------------------------------------------------- 查询
# ---------------------------------------------------------------- 正文：阅读 / 检索 / 补全
def section_detail(db: Session, section_id: int, user_id: int) -> dict | None:
    """单节正文 + 上下节导航。只允许读自己导入的教材。"""
    from ..models import TextbookSection

    sec = db.get(TextbookSection, section_id)
    if not sec:
        return None
    tb = db.get(Textbook, sec.textbook_id)
    if not tb or (tb.user_id not in (None, user_id)):
        return None

    sibs = db.scalars(
        select(TextbookSection)
        .where(TextbookSection.textbook_id == sec.textbook_id)
        .order_by(TextbookSection.order_index)
    ).all()
    idx = next((i for i, x in enumerate(sibs) if x.id == sec.id), -1)

    def _brief(o):
        return {"id": o.id, "section": o.section} if o else None

    return {
        "id": sec.id,
        "textbook": tb.title,
        "chapter": sec.chapter,
        "section": sec.section,
        "content": sec.content or sec.excerpt or "",
        "chars": sec.char_count,
        "has_full_text": bool(sec.content),
        "prev": _brief(sibs[idx - 1]) if idx > 0 else None,
        "next": _brief(sibs[idx + 1]) if 0 <= idx < len(sibs) - 1 else None,
    }


def _bigrams(s: str) -> set[str]:
    t = "".join((s or "").split())
    return {t[i:i + 2] for i in range(len(t) - 1)}


def search_sections(db: Session, user_id: int, query: str, *,
                    subject: str = "", limit: int = 4) -> list[dict]:
    """在**自己导入的教材正文**里检索（char bigram 打分，零依赖）。

    为什么要这个而不是只靠向量库：课本原文是最硬的依据，
    用户问「课本上怎么说的」时必须能原样摘出来。
    """
    from ..models import TextbookSection

    q = (query or "").strip()
    if not q:
        return []
    qb = _bigrams(q)
    if not qb:
        return []

    rows = db.execute(
        select(TextbookSection, Textbook)
        .join(Textbook, Textbook.id == TextbookSection.textbook_id)
        .where(Textbook.user_id == user_id)
    ).all()

    scored = []
    for sec, tb in rows:
        if subject and tb.subject_key != subject:
            continue
        body = sec.content or sec.excerpt or ""
        if not body:
            continue
        hay = (sec.chapter or "") + (sec.section or "") + body
        tb_set = _bigrams(hay)
        hit = len(qb & tb_set)
        if not hit:
            continue
        # 标题命中加权：问「等比数列」时，标题就带这词的节更有价值
        title_hit = len(qb & _bigrams((sec.chapter or "") + (sec.section or "")))
        score = hit / (len(qb) ** 0.5) + title_hit * 1.5
        scored.append((score, sec, tb, body))

    scored.sort(key=lambda x: -x[0])
    out = []
    for score, sec, tb, body in scored[:limit]:
        out.append({
            "id": sec.id,
            "textbook": tb.title,
            "chapter": sec.chapter,
            "section": sec.section,
            "snippet": _best_window(body, qb, 260),
            "score": round(score, 2),
            "has_full_text": bool(sec.content),
        })
    return out


def _best_window(body: str, qb: set[str], size: int = 260) -> str:
    """挑命中密度最高的一段，别总返回开头 260 字。"""
    flat = " ".join(body.split())
    if len(flat) <= size:
        return flat
    best, best_hit = flat[:size], -1
    step = max(40, size // 4)
    for i in range(0, max(1, len(flat) - size), step):
        win = flat[i:i + size]
        h = len(qb & _bigrams(win))
        if h > best_hit:
            best, best_hit = win, h
    return best


def textbook_context(db: Session, user_id: int, subject_key: str, query: str,
                     limit: int = 3) -> dict | None:
    """给对话用的课本原文上下文。没导入过正文就返回 None（不占 prompt）。"""
    hits = search_sections(db, user_id, query, subject=subject_key, limit=limit)
    if not hits:
        return None
    return {"items": hits, "from": "local_textbook"}


def refill_contents(db: Session, tb_id: int) -> dict:
    """给「之前只导入了结构」的教材补正文：重新解析原文件，按顺序回填。"""
    from ..models import TextbookSection

    tb = db.get(Textbook, tb_id)
    if not tb:
        return {"ok": False, "message": "教材不存在"}
    if not tb.file_path or not Path(tb.file_path).exists():
        return {"ok": False, "message": "原始文件已不在，请重新上传"}

    text, pages, err = _extract_text(Path(tb.file_path))
    if not text:
        return {"ok": False, "message": err or "解析不出文本（可能是扫描版）"}

    secs = split_structure(text)
    rows = db.scalars(
        select(TextbookSection)
        .where(TextbookSection.textbook_id == tb_id)
        .order_by(TextbookSection.order_index)
    ).all()
    filled = 0
    for i, row in enumerate(rows):
        if row.content:
            continue
        body = secs[i]["text"] if i < len(secs) else ""
        if body:
            row.content = body
            row.char_count = len(body)
            row.excerpt = body[:300]
            filled += 1
    db.commit()
    return {"ok": True, "filled": filled, "total": len(rows),
            "message": f"已回填 {filled}/{len(rows)} 节正文"}


def list_textbooks(db: Session, user_id: int, subject_key: str | None = None) -> list[dict]:
    q = select(Textbook).where(
        (Textbook.bundled == True) | (Textbook.user_id == user_id)  # noqa: E712
    )
    if subject_key:
        q = q.where(Textbook.subject_key == subject_key)
    rows = db.scalars(q.order_by(Textbook.bundled.desc(), Textbook.subject_key, Textbook.grade)).all()
    return [
        {
            "id": t.id,
            "code": t.code,
            "title": t.title,
            "subject": t.subject_key,
            "stage": t.stage,
            "grade": t.grade,
            "volume": t.volume,
            "publisher": t.publisher,
            "bundled": t.bundled,
            "pages": t.page_count,
            "chars": t.char_count,
            "status": t.parse_status,
            "note": t.parse_note,
        }
        for t in rows
    ]


def outline(db: Session, textbook_id: int, user_id: int) -> dict | None:
    tb = db.get(Textbook, textbook_id)
    if not tb or (not tb.bundled and tb.user_id != user_id):
        return None
    secs = db.scalars(
        select(TextbookSection)
        .where(TextbookSection.textbook_id == textbook_id)
        .order_by(TextbookSection.order_index)
    ).all()

    # 丢掉只有一个标题、没有正文的空壳节（PDF 目录页常产生这种）
    secs = [x for x in secs if (x.char_count or 0) >= 20 or (x.section and x.section != x.chapter)]
    chapters: dict[str, list[dict]] = {}
    for s in secs:
        chapters.setdefault(_chapter_key(s.chapter), []).append(
            {
                "id": s.id,
                "section": s.section,
                "order": s.order_index,
                "kp_codes": json.loads(s.kp_codes) if s.kp_codes else [],
                "chars": s.char_count,
                "has_text": bool(s.content),
                "excerpt": (s.excerpt or "")[:120],
            }
        )
    # 按章节在文档里的真实位置排序 —— dict 插入序会受目录页干扰
    ordered = sorted(
        chapters.items(),
        key=lambda kv: min(x["order"] for x in kv[1]),
    )
    return {
        "id": tb.id,
        "title": tb.title,
        "subject": tb.subject_key,
        "volume": tb.volume,
        "publisher": tb.publisher,
        "bundled": tb.bundled,
        "status": tb.parse_status,
        "chapters": [{"chapter": k, "sections": v} for k, v in ordered],
    }


def set_user_textbook(db: Session, user_id: int, subject_key: str, code: str) -> None:
    row = db.scalar(
        select(UserTextbook).where(
            UserTextbook.user_id == user_id, UserTextbook.subject_key == subject_key
        )
    )
    if row:
        row.textbook_code = code
        row.source = "manual"
        row.synced_at = datetime.now()
    else:
        db.add(
            UserTextbook(
                user_id=user_id, subject_key=subject_key, textbook_code=code,
                source="manual", synced_at=datetime.now(),
            )
        )
    db.flush()


def get_user_textbook(db: Session, user_id: int, subject_key: str) -> Textbook | None:
    row = db.scalar(
        select(UserTextbook).where(
            UserTextbook.user_id == user_id, UserTextbook.subject_key == subject_key
        )
    )
    if row:
        tb = db.scalar(select(Textbook).where(Textbook.code == row.textbook_code))
        if tb and (tb.bundled or tb.user_id == user_id):
            return tb
    # 没选过就用内置的第一本
    return db.scalar(
        select(Textbook).where(
            Textbook.subject_key == subject_key, Textbook.bundled == True  # noqa: E712
        ).order_by(Textbook.id)
    )


# ---------------------------------------------------------------- 讲解注入
def textbook_label(tb: Textbook) -> str:
    """出版社 + 书名。书名里已经带了出版社就别再拼一遍（"人教版 人教版 …"）。"""
    pub = (tb.publisher or "").strip()
    title = (tb.title or "").strip()
    if pub and title.startswith(pub):
        return title
    return f"{pub} {title}".strip()


def _core_tokens(title: str) -> list[str]:
    """从章节标题里抠出核心词：去掉编号，按标点/连词切开。"""
    t = re.sub(r"^\s*\d{1,2}[.．]\d{1,2}\s*", "", title or "")
    t = re.sub(r"^\s*第[一二三四五六七八九十百零〇\d]+[章节]\s*", "", t)
    parts = re.split(r"[、，,。;；:：/（）()\s]+|与|和|及|的|之", t)
    return [p for p in (x.strip() for x in parts) if len(p) >= 2][:6]


def textbooks_for_subject(db: Session, user_id: int, subject_key: str) -> list[Textbook]:
    """取该科目可用的全部教材（内置 + 自己导入的），同版本优先。"""
    rows = db.scalars(
        select(Textbook).where(
            Textbook.subject_key == subject_key,
            (Textbook.bundled == True) | (Textbook.user_id == user_id),  # noqa: E712
        ).order_by(Textbook.bundled.desc(), Textbook.id)
    ).all()
    if not rows:
        return []
    chosen = get_user_textbook(db, user_id, subject_key)
    if chosen and chosen.edition_code:
        # 同一版本的不同册次一起参与定位 —— 只在一册里找会漏掉"在别的册"的情况
        same = [t for t in rows if t.edition_code == chosen.edition_code]
        if same:
            return same
    return rows


def build_textbook_context(
    db: Session, user_id: int, subject_key: str, user_text: str,
    kp_hints: list[str] | None = None, limit: int = 4,
) -> dict | None:
    """跨册定位：找到课本里对应的章节，生成【教材定位】。

    为什么跨册：学生常常同时有必修一/二，如果只在"当前这一册"里找，
    问"平抛运动"就会匹配不到（它在必修二），然后退化成"给前几节"这种废话。
    """
    tbs = textbooks_for_subject(db, user_id, subject_key)
    if not tbs:
        return None

    probe = user_text or ""
    hints = set(kp_hints or [])

    pool: list[tuple[float, int, Textbook, TextbookSection]] = []
    for tb in tbs:
        secs = db.scalars(
            select(TextbookSection)
            .where(TextbookSection.textbook_id == tb.id)
            .order_by(TextbookSection.order_index)
        ).all()
        for s in secs:
            score = 0.0
            kps = set(json.loads(s.kp_codes)) if s.kp_codes else set()
            # 1) 知识点命中（最可靠）
            if hints & kps:
                score += 6.0 * len(hints & kps)
            # 2) 关键词命中
            for kw in (s.keywords or "").split(","):
                kw = kw.strip()
                if len(kw) >= 2 and kw in probe:
                    score += 3.0
            # 3) 小节核心词，按词长加权（"二次函数" 比 "函数" 具体）
            for tok in _core_tokens(s.section):
                if tok in probe:
                    score += 1.2 * min(4, len(tok))
            if score > 0:
                pool.append((score, -s.order_index, tb, s))

    if not pool:
        return {
            "textbook": textbook_label(tbs[0]),
            "volume": tbs[0].volume,
            "edition": tbs[0].edition_name,
            "edition_year": tbs[0].edition_year,
            "sections": [],
            "text": "",
            "matched": False,
            "message": "没有在课本目录里找到对应章节，本次不注入教材定位。",
        }

    pool.sort(key=lambda x: (x[0], x[1]), reverse=True)
    picked = pool[:limit]

    lines, volumes = [], []
    for _, _, tb, s in picked:
        vol = tb.volume or tb.title
        if vol not in volumes:
            volumes.append(vol)
        lines.append(f"- 《{vol}》{s.chapter} / {s.section}")

    main_tb = picked[0][2]
    return {
        "textbook": textbook_label(main_tb),
        "volume": main_tb.volume,
        "edition": main_tb.edition_name,
        "edition_year": main_tb.edition_year,
        "verified_at": main_tb.latest_check_at.isoformat() if main_tb.latest_check_at else None,
        "sections": lines,
        "volumes": volumes,
        "text": "\n".join(lines),
        "matched": True,
    }


# ---------------------------------------------------------------- 检查是否最新
SUBJECT_CN = {
    "math": "数学", "physics": "物理", "chemistry": "化学",
    "biology": "生物", "chinese": "语文", "english": "英语",
}
STAGE_CN = {"primary": "小学", "junior": "初中", "senior": "高中"}


async def check_latest(db: Session, tb: Textbook) -> dict:
    """联网核查该教材的最新修订版本。

    ⚠️ 刻意不做「内置一张最新年份表」—— 教材会改版，硬编码迟早过期，
       过期了还告诉用户"这是最新"比不检查更糟。所以改成实时联网核查 + 给出来源链接，
       结论由用户自己确认。
    """
    from .websearch import WebSearchClient
    from .llm import get_provider, MockProvider

    client = WebSearchClient()
    if not client.available:
        return {
            "ok": False,
            "message": "联网搜索不可用：需要配置 DeepSeek API Key 且开启联网搜索。",
        }

    subject_cn = SUBJECT_CN.get(tb.subject_key, tb.subject_key)
    stage_cn = STAGE_CN.get(tb.stage, "")
    edition = tb.edition_name or tb.publisher or ""
    query = f"{stage_cn}{subject_cn} {edition}教材 最新版本 修订 年份 教育部审定"

    res = await client.search(query, count=8, ori_question=f"{edition}最新教材版本")
    if not res.get("ok") or not res.get("results"):
        return {"ok": False, "message": res.get("message") or "没有检索到相关结果"}

    results = res["results"][:6]
    from .websearch import format_context, sources_public

    ctx = format_context(results)

    llm = get_provider()
    verdict = ""
    if not isinstance(llm, MockProvider):
        try:
            from ..config import TEMPERATURE_MAP

            verdict = await llm.chat(
                [
                    {"role": "system", "content": "你只根据给定资料回答，不确定就说不确定。"},
                    {
                        "role": "user",
                        "content": (
                            f"我正在用《{edition}》{stage_cn}{subject_cn}教材"
                            f"（我记录的版本是 {tb.edition_year or '未知'} 年版）。\n"
                            "请根据下面的检索结果回答：\n"
                            "1. 目前最新的版本/修订是哪一年？\n"
                            "2. 我手上的版本是否已是最新？\n"
                            "3. 如果不是，主要变化是什么？\n"
                            "资料不足以判断时，明确说「无法确认」，不要猜。\n\n"
                            f"{ctx}"
                        ),
                    },
                ],
                temperature=TEMPERATURE_MAP["diagnose"],
                max_tokens=800,
                scene="diagnose",
            )
        except Exception:
            verdict = ""

    if not verdict:
        # 没模型时至少把检索到的标题与日期给出来
        tops = "\n".join(
            f"- {r.get('title', '')}（{(r.get('date') or '')[:10]}）" for r in results[:4]
        )
        verdict = "（未配置模型，仅展示检索结果，请自行判断）\n" + tops

    tb.latest_check_at = datetime.now()
    tb.latest_verdict = verdict[:2000]
    tb.latest_sources = json.dumps(sources_public(results), ensure_ascii=False)
    db.flush()

    return {
        "ok": True,
        "textbook": textbook_label(tb),
        "recorded_edition": f"{tb.edition_name or ''} {tb.edition_year or ''} 年版".strip(),
        "verdict": verdict,
        "sources": sources_public(results),
        "checked_at": tb.latest_check_at.isoformat(),
        "query": query,
    }


def latest_progress(db: Session, user_id: int, subject_key: str) -> str | None:
    """粗略估计"学到哪"：取该科目最近一次复习/错题涉及的知识点，映射到章节。"""
    from ..models import ReviewState

    st = db.scalar(
        select(ReviewState)
        .where(ReviewState.user_id == user_id, ReviewState.subject_key == subject_key)
        .order_by(ReviewState.last_review.desc())
        .limit(1)
    )
    if not st:
        return None
    tb = get_user_textbook(db, user_id, subject_key)
    if not tb:
        return None
    secs = db.scalars(
        select(TextbookSection).where(TextbookSection.textbook_id == tb.id)
    ).all()
    for s in secs:
        kps = json.loads(s.kp_codes) if s.kp_codes else []
        if st.kp_code in kps:
            return f"{s.chapter} / {s.section}"
    return None
