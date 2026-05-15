#!/usr/bin/env python3
"""
fetch_gov.py — 政府政策情报抓取（百度搜索版）
百度对中国网络更友好，在 GitHub Actions Linux runner 上更容易访问。

用法:
    python scripts/fetch_gov.py --output-dir data --window-hours 72
"""

import argparse
import json
import re
import sys
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

# ── 搜索关键词（六大赛道）─────────────────────────────────────
SEARCH_KEYWORDS = [
    "上海物流补贴申报 site:gov.cn",
    "青浦仓储补贴申报",
    "上海数字化转型补贴申报",
    "低空经济补贴 上海 申报",
    "上海高企认定 申报通知",
    "上海就业见习补贴",
    "上海冷链物流补贴 申报",
    "快递扶持政策 上海",
    "仓储专项资金 青浦",
    "供应链数字化 上海 补贴",
]

MAX_RESULTS_PER_KEYWORD = 8
REQUEST_DELAY = 2.0

# 百度搜索（对中国网络友好）
BAIDU_SEARCH = "https://www.baidu.com/s?wd={}&rn=10&tn=baidu"

LOW_ALT_KEYWORDS = ["低空", "无人机", "eVTOL", "飞行汽车", "空域", "无人配送"]
SUBSIDY_KEYWORDS = ["补贴", "扶持", "资助", "奖励", "专项资金", "减负", "减免", "财政支持"]


def search_keyword(keyword: str) -> list:
    """用百度搜索关键词"""
    url = BAIDU_SEARCH.format(quote(keyword))
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "DNT": "1",
            },
            timeout=15,
        )
        resp.raise_for_status()
        resp.encoding = "utf-8"
        first_500 = resp.text[:500].lower()
        if any(x in first_500 for x in ["验证", "captcha", "403", "blocked", "denied"]):
            print(f"  [WARN] 百度验证/blocked，响应前200字符: {resp.text[:200]}", file=sys.stderr)
            return []
        return parse_baidu_results(resp.text, keyword)
    except Exception as e:
        print(f"  [WARN] 搜索失败: {keyword}: {e}", file=sys.stderr)
        return []


def parse_baidu_results(html: str, keyword: str) -> list:
    """解析百度搜索结果"""
    items = []
    # 百度结果格式：<h3 class="c-title"><a href="URL" ...>标题</a></h3>
    # 后面跟 <span class="c-span-last">摘要</span>
    title_pattern = re.compile(r'<h3 class="c-title"[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
    snippet_pattern = re.compile(r'<span class="c-span-last[^"]*"[^>]*>(.*?)</span>', re.DOTALL)
    # 也匹配普通div中的摘要
    snippet_pattern2 = re.compile(r'<div class="c-abstract"[^>]*>(.*?)</div>', re.DOTALL)

    gov_suffixes = ["gov.cn", "shqp.gov.cn", "sh.gov.cn", "beijing.gov.cn",
                     "caac.gov.cn", "miit.gov.cn", "ndrc.gov.cn", "spb.gov.cn",
                     "chinatax.gov.cn", "mot.gov.cn"]

    seen_urls = set()

    for title_match in title_pattern.finditer(html):
        url = title_match.group(1).strip()
        title_html = title_match.group(2)
        title = re.sub(r'<[^>]+>', '', title_html).strip()

        if not any(s in url.lower() for s in gov_suffixes):
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)

        # 找摘要
        snippet = ""
        snippet_match = snippet_pattern.search(html[title_match.end():title_match.end()+500])
        if snippet_match:
            snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip()
        else:
            snippet_match2 = snippet_pattern2.search(html[title_match.end():title_match.end()+500])
            if snippet_match2:
                snippet = re.sub(r'<[^>]+>', '', snippet_match2.group(1)).strip()

        snippet = re.sub(r'\s+', ' ', snippet)[:500]
        tags_data = classify_article(title, snippet)
        items.append({
            "id": f"gov_{abs(hash(url)) % 10**8}",
            "title": title[:300],
            "url": url,
            "source": guess_source_name(url),
            "region": guess_region(title + snippet),
            "content": snippet[:2000],
            "published_at": "",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "type": "gov",
            "tags": tags_data["tags"],
            "regions": tags_data["regions"],
            "is_policy_related": True,
            "summary": snippet[:300],
            "search_keyword": keyword,
        })

    return items[:MAX_RESULTS_PER_KEYWORD]


def guess_source_name(url: str) -> str:
    url_lower = url.lower()
    if "shqp.gov.cn" in url_lower: return "青浦区人民政府"
    if "rsj.sh.gov.cn" in url_lower: return "上海市人社局"
    if "sww.sh.gov.cn" in url_lower: return "上海市商务委"
    if "jtw.sh.gov.cn" in url_lower: return "上海市交通委"
    if "stcsm.sh.gov.cn" in url_lower: return "上海市科委"
    if "sheitc.sh.gov.cn" in url_lower: return "上海市经信委"
    if "fgw.sh.gov.cn" in url_lower: return "上海市发改委"
    if "shanghai.chinatax.gov.cn" in url_lower: return "上海市税务局"
    if "mot.gov.cn" in url_lower: return "交通运输部"
    if "miit.gov.cn" in url_lower: return "工信部"
    if "ndrc.gov.cn" in url_lower: return "国家发改委"
    if "spb.gov.cn" in url_lower: return "国家邮政局"
    if "caac.gov.cn" in url_lower: return "民航局"
    if "gov.cn" in url_lower: return "政府官网"
    return "政策资讯"


def guess_region(text: str) -> str:
    if "青浦" in text: return "青浦"
    if "上海" in text or "沪" in text: return "上海"
    if "国家" in text or "国务院" in text: return "国家"
    return "上海"


def classify_article(title: str, content: str) -> dict:
    text = (title + " " + content[:500]).lower()
    tags, regions = [], []
    if "青浦" in text: regions.append("青浦")
    if any(k in text for k in ["上海", "沪"]): regions.append("上海")
    if any(k in text for k in ["国务院", "国家"]): regions.append("国家")
    if any(k in text for k in LOW_ALT_KEYWORDS): tags.append("低空经济")
    if any(k in text for k in SUBSIDY_KEYWORDS): tags.append("财税补贴")
    if any(k in text for k in ["物流", "快递", "货运", "仓储", "供应链"]): tags.append("物流快递")
    if any(k in text for k in ["数字化", "数智化", "信息化", "数字经济"]): tags.append("数字化")
    if any(k in text for k in ["申报", "认定", "备案", "项目", "通知"]): tags.append("政策申报")
    if any(k in text for k in ["职业", "培训", "技能", "人才", "就业"]): tags.append("职业培训")
    if any(k in text for k in ["高企", "高新", "科小", "研发"]): tags.append("高企认定")
    if any(k in text for k in ["冷链", "冷藏", "冷库"]): tags.append("冷链")
    if not tags: tags.append("政策申报")
    if not regions: regions.append("上海")
    return {"tags": list(set(tags)), "regions": list(set(regions))}


def main():
    if sys.platform == "win32":
        os.environ["PYTHONIOENCODING"] = "utf-8"
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="政府政策情报抓取（百度搜索版）")
    parser.add_argument("--output-dir", default="data")
    parser.add_argument("--window-hours", type=int, default=72)
    args = parser.parse_args()

    print(f"{'='*60}")
    print(f"政府政策抓取（百度搜索版）| 关键词: {len(SEARCH_KEYWORDS)} | 每词: ≤{MAX_RESULTS_PER_KEYWORD}条")
    print(f"{'='*60}")

    all_items = []
    seen_urls = set()

    for i, kw in enumerate(SEARCH_KEYWORDS, 1):
        print(f"\n[{i}/{len(SEARCH_KEYWORDS)}] 搜索: {kw}")
        items = search_keyword(kw)
        print(f"  -> 获得 {len(items)} 条")
        for item in items:
            if item["url"] not in seen_urls:
                seen_urls.add(item["url"])
                all_items.append(item)
        time.sleep(REQUEST_DELAY)

    print(f"\n合计: {len(all_items)} 条（去重后）")
    save_output(all_items, args.output_dir, args.window_hours)


def save_output(items: list, output_dir: str, window_hours: int):
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    output = {
        "generated_at": now.isoformat(),
        "window_hours": window_hours,
        "total": len(items),
        "sources": list(set(it["source"] for it in items)),
        "items": items,
    }
    out_file = Path(output_dir) / "latest-gov.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    source_status = {}
    for it in items:
        src = it["source"]
        if src not in source_status:
            source_status[src] = {"ok": 0, "fail": 0, "url": it["url"]}
        source_status[src]["ok"] += 1

    with open(Path(output_dir) / "source-status-gov.json", "w", encoding="utf-8") as f:
        json.dump(source_status, f, ensure_ascii=False, indent=2)

    print(f"\n输出: {out_file} ({len(items)} 条)")


if __name__ == "__main__":
    main()
