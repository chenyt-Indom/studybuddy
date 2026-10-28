"""OCR 链路测试：造中文页 → 识别 → 校验关键词；再造扫描版 PDF → 整页识别。

单独一个文件而不是塞进 smoke_test：OCR 首次调用要加载模型（约 3~4 秒），
放进日常回归会把测试拖长；这里单独跑，出问题再定位。

跑法：
    python tests/ocr_test.py
依赖：pip install -r requirements-ocr.txt
"""
from __future__ import annotations

import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services import ocr  # noqa: E402

FONT = r"C:\Windows\Fonts\msyh.ttc"     # Windows 自带微软雅黑；Linux 换 Noto Sans CJK
KEYWORDS = ("集合", "元素", "列举法", "子集", "空集")

passed = 0
failed: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    global passed
    if cond:
        passed += 1
        print(f"  [PASS] {name} {extra}")
    else:
        failed.append(name)
        print(f"  [FAIL] {name} {extra}")


def make_page(title: str, lines: list[str]):
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (1240, 900), "white")
    d = ImageDraw.Draw(img)
    y = 70
    d.text((80, y), title, font=ImageFont.truetype(FONT, 42), fill="black")
    y += 90
    for ln in lines:
        d.text((80, y), ln, font=ImageFont.truetype(FONT, 27), fill="black")
        y += 52
    return img


print("=" * 64)
print("OCR 链路测试（RapidOCR + PyMuPDF）")

if not ocr.available():
    print("  [SKIP] OCR 依赖未安装：pip install -r requirements-ocr.txt")
    sys.exit(0)

check("OCR 引擎可用", ocr.available())

tmp = Path(__file__).resolve().parent / "_ocr_tmp"
tmp.mkdir(exist_ok=True)

# ---------- 1. 单张图片 ----------
img = make_page("1.1 集合的概念", [
    "把一些确定的、彼此不同的对象看成一个整体，这个整体就叫集合。",
    "元素与集合的关系只有两种：属于或不属于。",
    "集合的表示常用列举法和描述法两种。",
])
img_path = tmp / "page1.png"
img.save(img_path)

t0 = time.time()
text, err = ocr.ocr_image(img_path)
cost = time.time() - t0
check("图片能识别出文字", bool(text.strip()), f"{len(text)} 字 / {cost:.1f}s（含首次加载模型）")
check("识别结果含关键术语", all(k in text for k in ("集合", "元素", "列举法")),
      "｜".join(k for k in ("集合", "元素", "列举法") if k not in text) or "全部命中")
check("识别出章节编号", "1.1" in text)

# ---------- 2. 扫描版 PDF（无文字层） ----------
import pymupdf  # noqa: E402

pdf_path = tmp / "scan.pdf"
doc = pymupdf.open()
for title, lines in [
    ("第一章 集合与常用逻辑用语", ["把一些确定的、彼此不同的对象看成一个整体，这个整体就叫集合。",
                                "元素与集合的关系只有两种：属于或不属于。"]),
    ("1.2 集合间的基本关系", ["如果集合 A 的每个元素都在集合 B 里，就说 A 是 B 的子集。",
                            "空集是任何集合的子集，这一点初学者最容易漏。"]),
]:
    buf = io.BytesIO()
    make_page(title, lines).save(buf, format="PNG")
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=buf.getvalue())
doc.save(pdf_path)
doc.close()

from pypdf import PdfReader  # noqa: E402

raw = sum(len(p.extract_text() or "") for p in PdfReader(str(pdf_path)).pages)
check("测试 PDF 确实没有文字层", raw == 0, f"pypdf 抽出 {raw} 字")

t0 = time.time()
ptext, pages, perr = ocr.ocr_pdf(pdf_path)
check("扫描版 PDF 能整页识别", bool(ptext.strip()), f"{pages} 页 / {len(ptext)} 字 / {time.time() - t0:.1f}s")
check("两页内容都识别到了", "子集" in ptext and "列举法" not in ptext,
      perr or "第 2 页关键词命中")

# ---------- 3. 接进入库流程 ----------
from backend.services.textbook import _extract_text  # noqa: E402

etext, epages, enote = _extract_text(pdf_path)
check("导入流程会自动走 OCR 兜底", len(etext.strip()) > 40, enote or "")
check("兜底提示写明是扫描版", "扫描版" in (enote or ""), enote or "")

# 清理
for p in tmp.glob("*"):
    p.unlink(missing_ok=True)
tmp.rmdir()

print("=" * 64)
print(f"通过 {passed} 项，失败 {len(failed)} 项")
if failed:
    print("失败项:", failed)
    sys.exit(1)
print("全部通过")
