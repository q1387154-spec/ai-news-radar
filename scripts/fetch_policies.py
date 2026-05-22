"""
ai-news-radar: fetch_policies.py
Fetches policy opportunities from three parallel channels for 上海中通吉网络技术有限公司.
Run at 2026-05-22 14:50 GMT+8
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

import requests
from bs4 import BeautifulSoup

# ── Project root ──────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "data", "raw")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── Time zone ──────────────────────────────────────────────────────────────────
CST = timezone(timedelta(hours=8))
NOW = datetime.now(CST)
DATE_STR = NOW.strftime("%Y-%m-%d")
RUN_ID = str(uuid.uuid4())[:12]

# ── Logging ───────────────────────────────────────────────────────────────────
def log(msg: str) -> None:
    print(f"[{NOW:%H:%M:%S}] {msg}", flush=True)


# ── Shared helpers ─────────────────────────────────────────────────────────────

def item_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


def cn_date_to_iso(text: str) -> str | None:
    """Extract Chinese date (YYYY-MM-DD) from arbitrary text using multiple patterns."""
    patterns = [
        r"(\d{4})[年](\d{1,2})[月](\d{1,2})[日]?",
        r"(\d{4})-(\d{1,2})-(\d{1,2})",
        r"(\d{4})/(\d{1,2})/(\d{1,2})",
        r"(\d{4})\.(\d{1,2})\.(\d{1,2})",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            y, mo, d = m.group(1), m.group(2), m.group(3)
            try:
                return f"{y}-{int(mo):02d}-{int(d):02d}"
            except ValueError:
                continue
    return None


def make_item(
    title: str,
    url: str,
    source: str,
    source_name: str,
    published_at: str | None,
    snippet: str,
) -> dict[str, Any]:
    return {
        "id": item_id(url),
        "title": title.strip(),
        "url": url.strip(),
        "source": source,
        "source_name": source_name,
        "published_at": published_at or "",
        "snippet": snippet.strip(),
        "fetched_at": NOW.isoformat(),
    }


def dedup(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate by URL, preserving first-seen order."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for it in items:
        if it["url"] not in seen:
            seen.add(it["url"])
            out.append(it)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# CHANNEL 1: Tavily Search
# ─────────────────────────────────────────────────────────────────────────────

def fetch_tavily() -> list[dict[str, Any]]:
    """Search via Tavily AI Search using enterprise keywords."""
    items: list[dict[str, Any]] = []

    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        log("[Tavily] TAVILY_API_KEY not set – skipping.")
        return items

    try:
        from tavily import TavilyClient
    except ImportError:
        log("[Tavily] tavily-python not installed – skipping.")
        return items

    client = TavilyClient(api_key=api_key)

    # Keyword groups (high → medium priority)
    keywords = [
        # High priority
        "低空经济 无人机 政策 补贴 上海 2026",
        "eVTOL 无人配送 政策 上海 补贴 2026",
        "智慧物流 数字化转型 政策 上海 2026",
        "物流大模型 AI调度 政策 补贴 上海 2026",
        "超长期国债 两重两新 上海 补贴 政策",
        "设备更新 技改 上海 物流 补贴 2026",
        "快递 物流 新能源 配送 政策 上海 2026",
        # Medium priority
        "专精特新 小巨人 上海 物流 政策 补贴",
        "高企 研发费用加计扣除 上海 政策",
        "数字化转型 数据要素 上海 补贴 政策",
        # HR
        "稳岗返还 技能补贴 上海 快递 物流",
        "就业见习 培训 上海 快递员 政策",
    ]

    log("Fetching Tavily... (advanced search, max_results=10 each)")
    for kw in keywords:
        try:
            resp = client.search(query=kw, search_depth="advanced", max_results=10)
            results = resp.get("results", []) if isinstance(resp, dict) else []
            for r in results:
                raw_url = r.get("url", "")
                if not raw_url:
                    continue
                items.append(
                    make_item(
                        title=r.get("title", ""),
                        url=raw_url,
                        source="tavily",
                        source_name="Tavily Search",
                        published_at=cn_date_to_iso(r.get("published_date", "") or r.get("rawl_content", "")),
                        snippet=r.get("description", "") or r.get("content", ""),
                    )
                )
        except Exception as e:
            log(f"[Tavily] Error on keyword '{kw[:40]}': {e}")

    return items


# ─────────────────────────────────────────────────────────────────────────────
# CHANNEL 2: cn-web-search (Sogou WeChat + Baidu)
# ─────────────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

TIMEOUT = 15


def decode_sogou_redirect(text: str) -> str | None:
    """Extract real URL from Sogou WeChat redirect page content."""
    # Sogou uses: window.location.href = "..."
    m = re.search(r'window\.location\.href\s*=\s*["\']([^"\']+)["\']', text)
    if m:
        return m.group(1)
    # Sometimes: url = "..."
    m = re.search(r'url\s*=\s*["\']([^"\']+)["\']', text)
    if m:
        return m.group(1)
    # Raw URL pattern
    m = re.search(r"(https?://[^\s\"\'<>]+)", text)
    if m:
        return m.group(1)
    return None


def sogou_wechat(keyword: str) -> list[dict[str, Any]]:
    """Search Sogou WeChat for a keyword."""
    items: list[dict[str, Any]] = []
    url = f"https://weixin.sogou.com/weixin?type=2&query={requests.utils.quote(keyword)}&page=1"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        for art in soup.select("div.txt-box"):
            title_el = art.select_one("p.tit a")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            href = title_el.get("href", "")
            # Sogou redirect links need resolving
            if href.startswith("/"):
                href = "https://weixin.sogou.com" + href
            snippet_el = art.select_one("p.txt-info")
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
            # Date is usually in the txt-box footer
            date_el = art.select_one("span.s2")
            date_text = date_el.get_text(strip=True) if date_el else ""
            pub_date = cn_date_to_iso(date_text)
            items.append(
                make_item(
                    title=title,
                    url=href,
                    source="sogou_wechat",
                    source_name="搜狗微信",
                    published_at=pub_date,
                    snippet=snippet[:300],
                )
            )
    except Exception as e:
        log(f"[Sogou WeChat] Error on '{keyword[:30]}': {e}")
    return items


def baidu_gov(keyword: str) -> list[dict[str, Any]]:
    """Search Baidu for keyword + site:gov.cn."""
    items: list[dict[str, Any]] = []
    query = f"{keyword} site:gov.cn"
    url = f"https://www.baidu.com/s?wd={requests.utils.quote(query)}&rn=10"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        for result in soup.select("div.result"):
            title_el = result.select_one("h3.t a")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            href = title_el.get("href", "")
            # Baidu redirect URL – resolve via 百度隐私保护
            if "www.baidu.com/link" in href:
                try:
                    r = requests.head(href, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
                    href = r.url
                except Exception:
                    pass
            snippet_el = result.select_one("span.new")
            if not snippet_el:
                snippet_el = result.select_one("div.c-abstract")
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
            # Try to extract date from snippet
            pub_date = cn_date_to_iso(snippet)
            items.append(
                make_item(
                    title=title,
                    url=href,
                    source="baidu",
                    source_name=f"百度: {keyword[:20]}",
                    published_at=pub_date,
                    snippet=snippet[:300],
                )
            )
    except Exception as e:
        log(f"[Baidu] Error on '{keyword[:30]}': {e}")
    return items


def fetch_cn_search() -> list[dict[str, Any]]:
    """Run Sogou WeChat and Baidu searches in parallel for all keywords."""
    keywords = [
        "低空经济 政策 上海 补贴 2026",
        "无人机配送 政策 上海 青浦",
        "智慧物流 数字化转型 上海 政策",
        "超长期国债 两重两新 上海",
        "设备更新 技改 补贴 上海 物流",
        "专精特新 小巨人 上海 物流",
        "高企 研发费用加计扣除 上海",
        "稳岗返还 技能培训 上海 快递",
    ]

    items: list[dict[str, Any]] = []
    log("Fetching cn-search... (Sogou WeChat + Baidu)")

    def wrapper(keyword: str) -> list[dict[str, Any]]:
        return sogou_wechat(keyword) + baidu_gov(keyword)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(wrapper, kw): kw for kw in keywords}
        for fut in concurrent.futures.as_completed(futures):
            try:
                items.extend(fut.result())
            except Exception as e:
                log(f"[cn-search] Thread error for '{futures[fut][:30]}': {e}")

    return items


# ─────────────────────────────────────────────────────────────────────────────
# CHANNEL 3: Direct government HTML
# ─────────────────────────────────────────────────────────────────────────────

KNOWN_GOV_PAGES = [
    {
        "name": "上海经信委通知公告",
        "url": "https://www.sheitc.gov.cn/zcwj/index.html",
    },
    {
        "name": "上海发改委政策",
        "url": "https://fgw.sh.gov.cn/col/col846/index.html",
    },
    {
        "name": "上海交通委通知",
        "url": "https://jtw.sh.gov.cn/wjtz/index.html",
    },
    {
        "name": "青浦经委",
        "url": "https://www.qingpu.gov.cn/qpgg/",
    },
]


def fetch_gov_page(name: str, url: str) -> list[dict[str, Any]]:
    """Extract policy items from a government list page."""
    items: list[dict[str, Any]] = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        # Try common list selectors (多种可能的列表选择器)
        links: list[tuple[str, str | None]] = []

        # Pattern A: <ul><li><a href="...">标题</a>日期</li></ul>
        for a in soup.select("ul li a, ul.list li a, div.list li a"):
            href = a.get("href", "")
            text = a.get_text(strip=True)
            if href and text and len(text) > 4:
                links.append((text, href))

        # Pattern B: <table><tr> links
        if not links:
            for a in soup.select("table a, div.article-list a, div.news-list a"):
                href = a.get("href", "")
                text = a.get_text(strip=True)
                if href and text and len(text) > 4:
                    links.append((text, href))

        # Pattern C: generic article links
        if not links:
            for a in soup.select("a"):
                href = a.get("href", "")
                text = a.get_text(strip=True)
                if href and ("通知" in text or "公告" in text or "政策" in text or "办法" in text or "意见" in text):
                    links.append((text, href))

        for title, href in links:
            # Resolve relative URLs
            if href.startswith("/"):
                # extract base origin
                base = "/".join(url.split("/")[:3])
                full_url = base + href
            elif not href.startswith("http"):
                full_url = url.rsplit("/", 1)[0] + "/" + href
            else:
                full_url = href

            pub_date = cn_date_to_iso(title + " " + resp.text[:2000])
            items.append(
                make_item(
                    title=title,
                    url=full_url,
                    source="gov_html",
                    source_name=name,
                    published_at=pub_date,
                    snippet="",
                )
            )
    except Exception as e:
        log(f"[Gov HTML] Error fetching '{name}': {e}")

    return items


def fetch_gov_html() -> list[dict[str, Any]]:
    """Fetch all known government pages in parallel."""
    items: list[dict[str, Any]] = []
    log("Fetching gov HTML... (4 known pages)")

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(fetch_gov_page, p["name"], p["url"]): p["name"] for p in KNOWN_GOV_PAGES}
        for fut in concurrent.futures.as_completed(futures):
            try:
                items.extend(fut.result())
            except Exception as e:
                log(f"[Gov HTML] Thread error for '{futures[fut]}': {e}")

    return items


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    log("=== Policy Radar Fetch Started ===")
    log(f"Run ID : {RUN_ID}")
    log(f"Date   : {DATE_STR}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        f_tavily   = ex.submit(fetch_tavily)
        f_cn       = ex.submit(fetch_cn_search)
        f_gov      = ex.submit(fetch_gov_html)

        tavily_items = f_tavily.result()
        log(f"Fetching Tavily... Found {len(tavily_items)}")

        cn_items = f_cn.result()
        log(f"Fetching cn-search... Found {len(cn_items)}")

        gov_items = f_gov.result()
        log(f"Fetching gov HTML... Found {len(gov_items)}")

    # Deduplicate within each channel
    tavily_deduped = dedup(tavily_items)
    cn_deduped     = dedup(cn_items)
    gov_deduped    = dedup(gov_items)

    log(f"[Dedup] Tavily: {len(tavily_items)} → {len(tavily_deduped)}")
    log(f"[Dedup] cn-search: {len(cn_items)} → {len(cn_deduped)}")
    log(f"[Dedup] gov HTML: {len(gov_items)} → {len(gov_deduped)}")

    total = len(tavily_deduped) + len(cn_deduped) + len(gov_deduped)
    log(f"Total raw items: {total} (Tavily: {len(tavily_deduped)}, cn-search: {len(cn_deduped)}, gov: {len(gov_deduped)})")

    output = {
        "run_at": NOW.isoformat(),
        "run_id": RUN_ID,
        "channels": {
            "tavily":    tavily_deduped,
            "cn_search": cn_deduped,
            "gov_html":  gov_deduped,
        },
        "total_raw": total,
    }

    out_path = os.path.join(OUTPUT_DIR, f"{DATE_STR}_{RUN_ID}.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(output, fh, ensure_ascii=False, indent=2)

    log(f"Saved → {out_path}")
    log("=== Policy Radar Fetch Complete ===")


if __name__ == "__main__":
    main()
