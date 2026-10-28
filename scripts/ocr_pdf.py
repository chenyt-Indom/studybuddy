"""把扫描版 PDF 整本 OCR 成 txt，之后就能走普通导入（切章节、可读、可检索）。

为什么要单独一个脚本：一页 OCR 约 1.5~2 秒，200 页就是 6 分钟 ——
放在 Web 请求里必然超时，只能离线跑。

用法：
    # 转一本，输出到同目录（xxx.pdf → xxx.txt）
    python scripts/ocr_pdf.py "D:/书/数学必修一.pdf"

    # 批量：转一个目录下所有 pdf，直接落进收件箱，再跑 import_inbox.py
    python scripts/ocr_pdf.py "D:/书/" --to-inbox

    # 只转前 30 页，先试试效果
    python scripts/ocr_pdf.py "D:/书/书.pdf" --pages 30
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import UPLOAD_DIR  # noqa: E402
from backend.services import ocr  # noqa: E402


def convert(pdf: Path, out: Path, pages: int | None) -> bool:
    t0 = time.time()
    print(f"\n>>> {pdf.name}")

    def progress(done, total, preview):
        pct = done / max(total, 1) * 100
        eta = (time.time() - t0) / done * (total - done) if done else 0
        print(f"\r    第 {done}/{total} 页（{pct:.0f}%）剩余约 {eta / 60:.1f} 分钟  ",
              end="", flush=True)

    text, done, err = ocr.ocr_pdf(pdf, max_pages=pages, progress=progress)
    print()
    if not text.strip():
        print(f"    ✗ 没识别出内容：{err}")
        return False
    out.write_text(text, encoding="utf-8")
    print(f"    ✓ {done} 页 → {len(text)} 字 → {out}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="扫描版 PDF 整本 OCR")
    ap.add_argument("src", help="PDF 文件，或包含 PDF 的目录")
    ap.add_argument("--pages", type=int, default=None, help="只转前 N 页（试效果用）")
    ap.add_argument("--to-inbox", action="store_true",
                    help="输出到 data/textbooks/inbox/，方便接着跑 import_inbox.py")
    ap.add_argument("--out", default="", help="指定输出文件（单文件模式）")
    args = ap.parse_args()

    if not ocr.available():
        print("[x] OCR 依赖没装：pip install rapidocr-onnxruntime pymupdf pillow")
        return 1

    src = Path(args.src)
    if not src.exists():
        print(f"[x] 找不到：{src}")
        return 1

    inbox = UPLOAD_DIR.parent / "textbooks" / "inbox"
    if args.to_inbox:
        inbox.mkdir(parents=True, exist_ok=True)

    if src.is_dir():
        pdfs = sorted(p for p in src.iterdir() if p.suffix.lower() == ".pdf")
    else:
        pdfs = [src]
    if not pdfs:
        print(f"[!] {src} 里没有 PDF")
        return 0

    print(f"待处理 {len(pdfs)} 个 PDF；OCR 引擎就绪。")
    # 先跑一张图把模型加载进内存，后面每页会快不少
    t0 = time.time()
    ok = 0
    for pdf in pdfs:
        out_dir = inbox if args.to_inbox else pdf.parent
        out = Path(args.out) if (args.out and len(pdfs) == 1) else out_dir / (pdf.stem + ".txt")
        if convert(pdf, out, args.pages):
            ok += 1

    print(f"\n完成 {ok}/{len(pdfs)} 本，总耗时 {(time.time() - t0) / 60:.1f} 分钟")
    if args.to_inbox and ok:
        print("下一步：")
        print(f"  python scripts/import_inbox.py --user demo --subject math")
    return 0 if ok == len(pdfs) else 2


if __name__ == "__main__":
    raise SystemExit(main())
