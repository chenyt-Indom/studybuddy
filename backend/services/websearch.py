"""联网搜索（DeepSeek 官方 Search / Fetch 接口）。

接口规格（官方文档）：
  POST https://api.deepseek.com/v1/tools/search
    body: {query, count(1~50,默认10), ori_question, localization, need_content}
    resp: {results: [{rerank_score,title,url,snippet,summary,content,
                      site_name,site_icon,date,authority}]}
  POST https://api.deepseek.com/v1/tools/fetch   body: {url} -> {title, content(Markdown)}

计费：5 元 / 1000 次，只有 HTTP 200 且 results 非空才计费；失败/无结果不计费。
限速：Search 100 QPS（账号级）。
支持搜索语法：site: / -site: / "精确" / lang: / after: / before:
"""
from __future__ import annotations

import re

import httpx

from ..config import (
    PROVIDERS,
    WEB_SEARCH_COUNT,
    WEB_SEARCH_MAX_CONTEXT,
    WEB_SEARCH_NEED_CONTENT,
    WEB_SEARCH_TIMEOUT,
    now_context,
    settings,
)
from .secrets_store import scrub

# 触发联网的线索词：出现这些，说明答案随时间变化，必须查最新
TIME_SENSITIVE_PATTERNS = [
    r"最新", r"最近", r"现在", r"目前", r"当前", r"今年", r"去年", r"本月", r"本周",
    r"今天", r"昨天", r"新闻", r"实时", r"政策", r"法规", r"新规", r"发布",
    r"考试时间", r"报名时间", r"截止", r"分数线", r"招生", r"大纲", r"考纲",
    r"版本", r"更新", r"趋势", r"发展", r"前景", r"就业", r"薪资", r"岗位",
    r"20\d\d",  # 出现年份基本都在问时效性内容
]
_TS_RE = re.compile("|".join(TIME_SENSITIVE_PATTERNS))


def should_search(text: str) -> bool:
    """启发式判断：这条问题要不要联网。

    宁可多查一点 —— 一次搜索 0.005 元，比给出过时信息便宜得多。
    纯公式推导、纯定义类问题不查。
    """
    if not text:
        return False
    t = text.strip()
    if len(t) < 4:
        return False
    return bool(_TS_RE.search(t))


class WebSearchClient:
    """只有 DeepSeek 有 /tools/search；其它供应商返回不可用。"""

    def __init__(self, provider: str | None = None) -> None:
        self.provider = provider or settings.provider
        self.api_key = settings.key_of(self.provider)

    @property
    def available(self) -> bool:
        return (
            self.provider == "deepseek"
            and bool(self.api_key)
            and settings.search_enabled
        )

    def _base(self) -> str:
        base = (
            settings._slot(self.provider).get("base_url")
            or PROVIDERS[self.provider]["base_url"]
        )
        # 统一到站点根：/tools/search 挂在 https://api.deepseek.com/v1 下
        base = base.rstrip("/")
        if base.endswith("/v1"):
            return base
        return base + "/v1"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "StudyBuddy/0.1",
        }

    async def search(
        self,
        query: str,
        count: int = WEB_SEARCH_COUNT,
        ori_question: str | None = None,
    ) -> dict:
        """返回 {ok, results, message}。失败不抛，交给调用方降级。"""
        if not self.available:
            if not settings.search_enabled:
                reason = "联网搜索已关闭"
            elif self.provider != "deepseek":
                reason = f"{PROVIDERS[self.provider]['label']} 不支持 /tools/search"
            else:
                reason = "未配置 API Key"
            return {"ok": False, "results": [], "message": reason}

        # query 限 1~128 字符
        q = (query or "").strip()[:128]
        if not q:
            return {"ok": False, "results": [], "message": "搜索词为空"}

        body = {
            "query": q,
            "count": max(1, min(50, count)),
            "need_content": WEB_SEARCH_NEED_CONTENT,
        }
        if ori_question:
            body["ori_question"] = ori_question[:128]

        try:
            async with httpx.AsyncClient(timeout=WEB_SEARCH_TIMEOUT) as client:
                r = await client.post(
                    f"{self._base()}/tools/search", headers=self._headers(), json=body
                )
                raw = r.text
                if r.status_code == 402:
                    return {"ok": False, "results": [], "message": "账户余额不足，搜索不可用"}
                if r.status_code == 429:
                    return {"ok": False, "results": [], "message": "搜索请求过于频繁（限 100 QPS）"}
                if r.status_code >= 400:
                    return {
                        "ok": False,
                        "results": [],
                        "message": f"搜索失败 HTTP {r.status_code}: "
                                   f"{scrub(raw, self.api_key)[:200]}",
                    }
                data = r.json()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "results": [],
                    "message": scrub(str(exc), self.api_key)[:200]}

        rows = data.get("results") or []
        results = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("url"):
                continue
            results.append(
                {
                    "title": (row.get("title") or "").strip(),
                    "url": row.get("url"),
                    "snippet": (row.get("snippet") or "").strip(),
                    "summary": (row.get("summary") or row.get("snippet") or "").strip(),
                    "site_name": row.get("site_name"),
                    "date": row.get("date"),
                    "authority": row.get("authority"),
                    "score": row.get("rerank_score"),
                }
            )
        # 权威性 + 相关度排序，取前几条注入
        results.sort(
            key=lambda x: ((x.get("authority") or 0) * 0.3 + (x.get("score") or 0)),
            reverse=True,
        )
        return {"ok": True, "results": results, "query": q}


def build_search_query(user_text: str, subject_cn: str = "") -> str:
    """把口语问题整理成搜索词。

    不做 LLM 二次改写（多一次调用、多一次失败点、还慢）。
    只做轻量清洗：去语气词、拼接科目语境、限长。
    """
    t = re.sub(r"[\s]+", " ", user_text or "").strip()
    t = re.sub(r"^(请问|老师|你好|那个|我想问一下|能不能|可以|帮我)[，,、\s]*", "", t)
    t = t[:96]
    if subject_cn and subject_cn not in t:
        t = f"{t} {subject_cn}"
    return t[:128]


def format_context(results: list[dict], max_chars: int = WEB_SEARCH_MAX_CONTEXT) -> str:
    """把搜索结果拼成给模型阅读的上下文，带编号方便引用。"""
    if not results:
        return ""
    parts = []
    used = 0
    for i, r in enumerate(results, 1):
        date = (r.get("date") or "")[:10]
        head = f"[{i}] {r.get('title') or '无标题'}"
        meta = " · ".join(x for x in [r.get("site_name"), date] if x)
        body = (r.get("summary") or r.get("snippet") or "").strip()
        block = f"{head}\n{('来源：' + meta) if meta else ''}\n链接：{r.get('url')}\n{body}"
        if used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts)


def sources_public(results: list[dict]) -> list[dict]:
    """给前端展示的来源列表（不含正文，省流量）。"""
    return [
        {
            "title": r.get("title") or "",
            "url": r.get("url") or "",
            "site": r.get("site_name") or "",
            "date": (r.get("date") or "")[:10],
            "snippet": r.get("snippet") or "",
        }
        for r in results
    ]


def today_line() -> str:
    """时间感知用的系统提示行。"""
    c = now_context()
    return (
        f"【当前时间】现在是 {c['display']}（北京时间，{c['date']}）。"
        f"当用户问「最新/今年/现在」这类问题时，以此时间为准；"
        f"如需超出你知识截止时间的信息，应说明需要联网检索或提示用户开启联网搜索。"
    )
