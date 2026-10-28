"""扫描版 PDF / 拍照课本的 OCR。

为什么选 RapidOCR（而不是 PaddleOCR）：
  · 体积差一个量级：rapidocr-onnxruntime 约 100MB（含模型），PaddleOCR 光依赖就 300MB+、
    还要编译环境；这台机器没必要为识别印刷体付那个代价
  · 纯 onnxruntime，Windows 上装完即用，不用碰 CUDA
  · 课本是**印刷体**，RapidOCR 的中文识别足够；手写和公式才是它的弱项

三条使用路径：
  1. 上传扫描版 PDF（页数少）→ 导入时自动 OCR 兜底（见 textbook._extract_text）
  2. 整本书（几十上百页）→ 用 scripts/ocr_pdf.py 先转成 .txt，再走普通导入
     （一次请求里跑 200 页 OCR 会超时，必须放到后台脚本里）
  3. 单张照片 → ocr_image()

已知取舍：
  · 不保留版式（分栏、表格会串行），但课本正文段落基本可用
  · 公式识别不出来，会变成乱码/漏识 —— 遇到公式多的页，OCR 价值有限
"""
from __future__ import annotations

import re
from pathlib import Path

_engine = None
_engine_err = ""


def available() -> bool:
    """依赖装没装（没装就安静降级，不抛异常）。"""
    try:
        import onnxruntime  # noqa: F401
        import rapidocr_onnxruntime  # noqa: F401
        import pymupdf  # noqa: F401
        return True
    except Exception:
        return False


def _get_engine():
    global _engine, _engine_err
    if _engine is not None:
        return _engine
    try:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    except Exception as exc:  # noqa: BLE001
        _engine_err = f"{type(exc).__name__}: {exc}"
        _engine = None
    return _engine


def _clean(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text or "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _pick_lines(result) -> list[str]:
    """从 RapidOCR 的结果里挑文字行。

    ⚠️ 它的返回是 [[box, text, score], ...]，而 **score 有时是字符串**（'0.93'），
    直接 `score > 0.4` 会 TypeError —— 必须转 float 再比。
    """
    out: list[str] = []
    for item in result or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        text = item[1]
        if not isinstance(text, str) or not text.strip():
            continue
        try:
            score = float(item[2]) if len(item) > 2 and item[2] is not None else 1.0
        except (TypeError, ValueError):
            score = 1.0
        if score >= 0.4:
            out.append(text)
    return out


def ocr_image(path: str | Path) -> tuple[str, str]:
    """识别一张图片。返回 (text, err)。"""
    eng = _get_engine()
    if eng is None:
        return "", _engine_err or "OCR 引擎不可用"
    try:
        result, _elapse = eng(str(path))
    except Exception as exc:  # noqa: BLE001
        return "", f"OCR 失败：{type(exc).__name__}: {exc}"
    if not result:
        return "", "没识别出文字"
    return _clean("\n".join(_pick_lines(result))), ""


def ocr_pdf(path: str | Path, max_pages: int | None = None, dpi: int = 200,
            progress=None) -> tuple[str, int, str]:
    """把 PDF 逐页渲染后 OCR。返回 (text, pages_done, err)。

    dpi=200 是精度/速度的平衡点：150 会丢小字，300 速度慢一倍收益不大。
    """
    try:
        import pymupdf
    except Exception as exc:  # noqa: BLE001
        return "", 0, f"缺 pymupdf：{exc}"

    eng = _get_engine()
    if eng is None:
        return "", 0, _engine_err or "OCR 引擎不可用"

    try:
        doc = pymupdf.open(str(path))
    except Exception as exc:  # noqa: BLE001
        return "", 0, f"打不开 PDF：{exc}"

    total = len(doc)
    pages = total if max_pages is None else min(total, max_pages)
    out: list[str] = []
    for i in range(pages):
        try:
            pix = doc[i].get_pixmap(dpi=dpi)
            img_bytes = pix.tobytes("png")
            import numpy as np
            from io import BytesIO
            from PIL import Image

            img = np.array(Image.open(BytesIO(img_bytes)).convert("RGB"))
            result, _ = eng(img)
            page_text = _clean("\n".join(_pick_lines(result)))
        except Exception as exc:  # noqa: BLE001
            page_text = ""
            if progress:
                progress(i + 1, pages, f"第 {i + 1} 页失败：{exc}")
        out.append(page_text)
        if progress:
            progress(i + 1, pages, page_text[:40])
    doc.close()

    text = "\n\n".join(t for t in out if t)
    return text, pages, "" if text else "整本都没识别出文字"
