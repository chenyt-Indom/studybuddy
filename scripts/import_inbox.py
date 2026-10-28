"""批量导入教材：把一堆 PDF / TXT / MD 一次全部切章节入库。

为什么要有这个：教材通常是一册一个文件，十几本一个个点上传太累。
把文件丢进 data/textbooks/inbox/，跑一次命令，全部入库并可离线阅读。

用法（在项目根目录）：
    python scripts/import_inbox.py --user demo --subject math
    python scripts/import_inbox.py --user demo --subject physics --stage senior --grade senior_1
    python scripts/import_inbox.py --user demo --subject math --inbox D:/tBooks   # 临时指定目录
    python scripts/import_inbox.py --user demo --subject math --dry-run           # 只列出会导什么

约定：
  · 文件名即教材名（去掉扩展名）
  · 支持 .pdf / .txt / .md（.pdf 需要文字层；扫描版要靠 OCR，暂不支持）
  · 已导入过的同名教材会跳过（--force 可强制再导一份）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from backend.config import UPLOAD_DIR  # noqa: E402
from backend.db import SessionLocal, init_db  # noqa: E402
from backend.models import Textbook, User  # noqa: E402
from backend.services.textbook import import_file  # noqa: E402

SUFFIXES = {".pdf", ".txt", ".md"}


def main() -> int:
    ap = argparse.ArgumentParser(description="批量导入教材")
    ap.add_argument("--user", required=True, help="用户名（导入到哪个账号下）")
    ap.add_argument("--subject", default="math",
                    choices=["math", "physics", "chemistry", "biology", "chinese", "english"])
    ap.add_argument("--stage", default="senior", choices=["primary", "junior", "senior"])
    ap.add_argument("--grade", default="senior_1")
    ap.add_argument("--inbox", default=str(UPLOAD_DIR.parent / "textbooks" / "inbox"))
    ap.add_argument("--force", action="store_true", help="同名教材已存在也再导一份")
    ap.add_argument("--dry-run", action="store_true", help="只列出将要导入的文件")
    args = ap.parse_args()

    inbox = Path(args.inbox)
    if not inbox.is_dir():
        inbox.mkdir(parents=True, exist_ok=True)
        print(f"[!] 收件目录不存在，已创建：{inbox}")
        print("    把教材文件放进去，再跑一次这条命令。")
        return 0

    files = sorted(p for p in inbox.iterdir() if p.suffix.lower() in SUFFIXES)
    if not files:
        print(f"[!] {inbox} 里没有可导入的文件（支持 {'/'.join(sorted(SUFFIXES))}）")
        return 0

    print(f"收件目录：{inbox}")
    print(f"发现 {len(files)} 个文件：")
    for p in files:
        print(f"  · {p.name}  ({p.stat().st_size / 1024 / 1024:.1f} MB)")

    if args.dry_run:
        print("\n--dry-run：不实际导入。")
        return 0

    init_db()
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.username == args.user))
        if not user:
            print(f"[x] 找不到用户 {args.user}")
            return 1

        have = {
            (t.title or "").strip()
            for t in db.scalars(select(Textbook).where(Textbook.user_id == user.id))
        }

        ok = skipped = failed = 0
        total_chars = 0
        for p in files:
            name = p.stem[:100]
            if name in have and not args.force:
                print(f"  = 跳过（已导入过）：{p.name}")
                skipped += 1
                continue
            try:
                r = import_file(
                    db, user.id, p.name, p.read_bytes(), args.subject,
                    stage=args.stage, grade=args.grade, volume="批量导入",
                )
            except Exception as exc:  # noqa: BLE001
                print(f"  x {p.name} 失败：{type(exc).__name__}: {exc}")
                failed += 1
                continue

            if r.get("ok"):
                db.commit()
                have.add(name)
                total_chars += r.get("chars", 0)
                ok += 1
                print(f"  ✓ {p.name} → {r['sections']} 节 / {r['chars']} 字")
            else:
                db.rollback()
                failed += 1
                print(f"  x {p.name}：{r.get('message')}")

        print("\n" + "=" * 48)
        print(f"成功 {ok} 本 · 跳过 {skipped} 本 · 失败 {failed} 本 · 共 {total_chars} 字")
        if failed:
            print("失败的多半是扫描版 PDF（没有文字层），需要 OCR 才能读。")
        print("导入后打开「教材」页即可离线阅读，讲解也会引用课本原文。")
        return 0 if failed == 0 else 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
