#!/usr/bin/env python3
"""
fetch_wechat_free.py — 微信公众号抓取（全免费方案）

免费组合：
1. 搜狗微信搜索 → 获取文章 URL + 摘要（免费，无需登录）
2. Jina Reader → 将微信文章转为 markdown（免费 tier，5000次/月）
   注册: https://jina.ai/reader (免费注册获取 API Key)

用法:
    python scripts/fetch_wechat_free.py --output-dir data --window-hours 72
    JINA_API_KEY=xxx python scripts/fetch_wechat_free.py ...
"""

import argparse
import json
import os
import sys
import time
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import urlopen
from urllib.error import URLError


# 搜索关键词
SOGOU_KEYWORDS = [
    "上海 物流 补贴 申报 site:mp.weixin.qq.com",
    "青浦 仓储 数字化 补贴 申报",
    "低空经济 无人机 物流 补贴 2026",
    "上海 专精特新 高企 认定 申报",
    "上海 快递 智慧物流 专项资金",
    "上海 就业见习 补贴 申报 通知",
    "上海 数字化转型 补贴 产业互联网",
]

MAX_ARTICLES = 20
MAX_PAGES_PER_KW = 2


# ─── 第一步：搜狗微信搜索（免费）──────────────────────────────

def search_sogou(keyword: str, max_pages: int = 2) -> list:
    """搜狗微信搜索获取文章 URL（免费，无需登录）"""
    import requests
    from bs4 import BeautifulSoup

    articles = []
    for page in range(1, max_pages + 1):
        try:
            resp = requests.get(
                "https://weixin.sogou.com/weixin",
                params={"type": "2", "query": keyword, "page": page, "ie": "utf8"},
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                  "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                },
                timeout=15,
            )
            resp.encoding = "utf-8"
            soup = BeautifulSoup(resp.text, "lxml")

            for li in soup.select("ul.news-list > li"):
                h3 = li.select_one("h3")
                a = h3.select_one("a") if h3 else li.select_one("a[href*='link']")
                if not a:
                    continue
                title = a.get_text(strip=True)
                url = a.get("href", "")
                if not url:
                    continue
                account = li.select_one(".account")
                date_el = li.select_one(".s2")
                date_str = date_el.get_text(strip=True) if date_el else ""

                articles.append({
                    "title": title,
                    "url": _extract_wechat_url(url),  # 修复坏链：从Sogou跳转提取真实微信URL
                    "account": account.get_text(strip=True) if account else "",
                    "date": date_str,
                    "keyword": keyword,
                })
            time.sleep(2)

        except Exception as e:
            print(f"  ⚠️ 搜狗搜索失败 [{keyword}] p{page}: {e}")

    return articles


def _extract_wechat_url(sogou_url: str) -> str:
    """
    修复Sogou跳转链接。
    Sogou返回格式: /link?url=https%3A%2F%2Fmp.weixin.qq.com%2Fs%2F...
    从url参数解码出真实微信文章URL。
    """
    if not sogou_url:
        return sogou_url
    if sogou_url.startswith("http"):
        return sogou_url
    if "/link?url=" in sogou_url:
        parsed = urlparse(sogou_url)
        params = parse_qs(parsed.query)
        if "url" in params and params["url"]:
            from urllib.parse import unquote
            real_url = unquote(params["url"][0])
            return real_url
    return sogou_url


# ─── 第二步：Jina Reader（免费 tier）────────────────────────

def fetch_with_jina(url: str, api_key: str = "") -> dict:
    """
    Jina Reader: 将任意 URL 转为 markdown（免费 5000次/月）
    注册 https://jina.ai/reader 获取免费 API Key
    """
    if not api_key:
        return None

    try:
        resp = requests.get(
            f"https://r.jina.ai/{url}",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "text/plain",
                "X-Return-Format": "markdown",
            },
            timeout=20,
        )
        if resp.status_code == 200:
            return {"markdown": resp.text, "source": "jina"}
        # 免费 tier 超限后返回 429
        if resp.status_code == 429:
            print(f"  ⚠️ Jina 免费额度用尽（429），跳过正文抓取")
    except Exception as e:
        print(f"  ⚠️ Jina 请求失败: {e}")
    return None


# ─── 第三步：降级方案（无 API Key 时）────────────────────────

def get_wechat_content_fallback(url: str) -> str:
    """
    降级方案：直接请求微信文章页（尝试提取正文）
    注意：微信有反爬，部分文章可能失败
    """
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                "Accept": "text/html",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
            timeout=12,
        )
        # 微信会重定向或返回特殊内容
        if "window.__RENDER_DATA__" in resp.text or "var round_url" in resp.text:
            # 微信 JS 渲染页面，降级失败
            return ""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "lxml")
        # 尝试提取文章正文
        for sel in ["#js_content", ".rich_media_content", "#img-content"]:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(separator="\n", strip=True)
                if len(text) > 100:
                    return text[:3000]
    except Exception:
        pass
    return ""


# ─── 工具函数 ────────────────────────────────────────────────

def parse_date(date_str: str) -> str:
    if not date_str:
        return ""
    m = re.search(r"(\d{4})[年\-\/](\d{1,2})[月\-\/](\d{1,2})", date_str)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""


def clean_markdown(text: str) -> str:
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\(.*?\)", r"\1", text)
    text = re.sub(r"#{1,6}\s*", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:500]


def extract_tags(title: str, content: str) -> list:
    text = (title + " " + content).lower()
    tags = []
    if any(k in text for k in ["低空", "无人机", "eVTOL", "飞行汽车", "空域"]): tags.append("低空经济")
    if any(k in text for k in ["补贴", "扶持", "资助", "奖励", "专项", "减负"]): tags.append("财税补贴")
    if any(k in text for k in ["物流", "快递", "货运", "仓储", "供应链", "配送"]): tags.append("物流快递")
    if any(k in text for k in ["数字化", "数智化", "信息化", "数字经济"]): tags.append("数字化")
    if any(k in text for k in ["高企", "高新", "科小", "研发费用", "加计扣除", "专精特新", "小巨人"]): tags.append("高企认定")
    if any(k in text for k in ["申报", "认定", "备案", "项目", "通知"]): tags.append("政策申报")
    if any(k in text for k in ["稳岗", "技能补贴", "创业", "就业", "培训"]): tags.append("职业培训")
    if any(k in text for k in ["青浦"]): tags.append("青浦")
    if not tags: tags.append("政策申报")
    return list(set(tags))


# ─── 主函数 ──────────────────────────────────────────────────

def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="微信公众号抓取（全免费）")
    parser.add_argument("--output-dir", default="data")
    parser.add_argument("--window-hours", type=int, default=72)
    parser.add_argument("--max-articles", type=int, default=MAX_ARTICLES)
    args = parser.parse_args()

    print(f"{'='*60}")
    print(f"微信公众号抓取（全免费：搜狗 + Jina Reader）")
    print(f"{'='*60}")

    # 获取 Jina API Key（优先环境变量）
    jina_key = os.environ.get("JINA_API_KEY", "")

    if jina_key:
        print(f"\n✅ Jina API Key 已配置（免费 5000次/月）")
        print(f"   注册: https://jina.ai/reader")
    else:
        print(f"\n⚠️  未配置 JINA_API_KEY（可选）")
        print(f"   免费注册获取: https://jina.ai/reader")
        print(f"   降级方案：搜狗搜索摘要（仍可正常运行）")

    # Step 1: 搜狗搜索收集 URL
    print(f"\n[Step 1] 搜狗微信搜索 ({len(SOGOU_KEYWORDS)} 个关键词)...")
    all_articles = []
    for kw in SOGOU_KEYWORDS:
        print(f"  搜索: {kw[:40]}...")
        articles = search_sogou(kw, max_pages=MAX_PAGES_PER_KW)
        print(f"    -> {len(articles)} 条")
        all_articles.extend(articles)
        time.sleep(1.5)

    # 去重
    seen_urls = set()
    unique = []
    for art in all_articles:
        if art["url"] not in seen_urls:
            seen_urls.add(art["url"])
            unique.append(art)
    print(f"\n去重后: {len(unique)} 条")

    # 限制数量
    recent = unique[:args.max_articles]
    print(f"限制前 {args.max_articles} 条")

    # Step 2: 抓取正文
    print(f"\n[Step 2] 抓取正文...")
    results = []

    for i, art in enumerate(recent, 1):
        print(f"  [{i}/{len(recent)}] {art['title'][:35]}...", end=" ", flush=True)

        content = ""
        source_used = "sogou"  # 默认用搜狗摘要

        # 优先用 Jina（如果有 Key）
        if jina_key:
            jina_result = fetch_with_jina(art["url"], jina_key)
            if jina_result:
                content = clean_markdown(jina_result["markdown"])
                source_used = "jina"
                print(f"(Jina markdown, {len(content)}字)")
            else:
                # Jina 失败，降级到直接请求
                content = get_wechat_content_fallback(art["url"])
                if content:
                    source_used = "direct"
                    print(f"(direct, {len(content)}字)")
                else:
                    print("(无正文)")
        else:
            # 无 Jina Key，只用搜狗摘要
            content = art.get("abstract", "")
            print("(sogou摘要)")

        results.append({
            "id": f"wechat_{abs(hash(art['url'])) % 10**8}",
            "title": art["title"],
            "url": art["url"],
            "account": art["account"],
            "published_date": parse_date(art["date"]),
            "content": content[:3000] if content else art.get("abstract", ""),
            "content_source": source_used,
            "tags": extract_tags(art["title"], content),
            "regions": ["上海"] if "上海" in art["title"] else ["国家"],
            "type": "wechat",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": art["account"] or "微信公众号",
        })

        time.sleep(1)

    # Step 3: 保存
    out_path = Path(args.output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    out_file = out_path / "wechat.json"

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "content_source": "Jina Reader (免费) + 搜狗搜索（免费）",
        "items": results,
    }

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n保存: {out_file} ({len(results)} 条)")
    print(f"Jina Reader 免费注册: https://jina.ai/reader")


if __name__ == "__main__":
    main()
