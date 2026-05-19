#!/usr/bin/env python3
"""
fetch_gov_static.py — 政府 HTML 页面抓取（requests + bs4，纯静态）

完全不使用 Playwright / 浏览器。
使用 requests 并发抓取 + bs4 解析正文。

用法:
    python scripts/fetch_gov_static.py --output-dir data --limit 80
"""

import argparse
import json
import sys
import re
import time
import random
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
}

# 政府页面特征（高政策密度栏目）
SEED_SECTIONS = {
    "上海市经信委": [
        "https://www.sheitc.sh.gov.cn/zxzjtzgg/",   # 资金补贴通知（最关键）
        "https://sheitc.sh.gov.cn/gg/",              # 公示公告
        "https://www.sheitc.sh.gov.cn/zxgkxx/",      # 最新公开信息
        "https://www.sheitc.sh.gov.cn/zxzjtzgg/",    # 最新资金补贴（备用）
    ],
    "上海市发改委": [
        "https://fgw.sh.gov.cn/fgw_jggl/",           # 价格管理
        "https://fgw.sh.gov.cn/fgw_zcjd/",           # 政策解读
        "https://fgw.sh.gov.cn/fgw_tzgg/",           # 通知公告
    ],
    "上海市科委": [
        "https://stcsm.sh.gov.cn/zwgk/kyjhxm/zxjz/",  # 科技创新项目
        "https://stcsm.sh.gov.cn/zwgk/kyjzjzcx/",    # 科技创新支持
    ],
    "上海市交通委": [
        "https://www.jtw.sh.gov.cn/jtw_zfxxgk/",     # 政策文件
        "https://www.jtw.sh.gov.cn/jtw_tzgg/",       # 通知公告
    ],
    "上海市商务委": [
        "https://sww.sh.gov.cn/zwgk_zdgw/",          # 政策公告
    ],
    "青浦区政府": [
        "https://www.shqp.gov.cn/shqp/gsgg/",        # 公示公告
        "https://www.shqp.gov.cn/shqp/zwgk/index.html",  # 政务公开
        "https://www.shqp.gov.cn/shqp_ztz/",         # 投资政策
    ],
    "工信部": [
        "https://www.miit.gov.cn/zwgk/zcwj/",
        "https://www.miit.gov.cn/zwgk/zcjd/",
    ],
    "国家邮政局": [
        "http://www.spb.gov.cn/zwgk/tz/",
    ],
    "民航局": [
        "https://www.caac.gov.cn/zwgk/zcwj/",
    ],
    "上海人社局": [
        "https://rsj.sh.gov.cn/tgsgg_17341/index.html",
    ],
    "国家发改委": [
        "https://www.ndrc.gov.cn/fggg/",
    ],
    "交通运输部": [
        "https://www.mot.gov.cn/zcfb/",
    ],
    "国家数据局": [
        "https://www.ndrc.gov.cn/fggz/",
    ],
}

# 政策类关键词（标题必须含）
POLICY_KW = ["通知", "公告", "意见", "办法", "指南", "公示",
             "决定", "方案", "政策", "解读", "批复", "纲要", "规划", "条例",
             "申报", "认定", "补贴", "扶持", "资助", "项目", "征集"]

# 排除词
EXCLUDE_KW = [
    "404", "找不到", "error", "索  引", "索引号", "页面",
    "录用", "公务员", "事业单位招聘",   # 人事类
    "课题", "研究课题",                 # 课题类
    "药品", "医疗器械", "医院",         # 医疗类
    "电价", "水价", "气价",             # 公用事业
    "购房", "保障房",                    # 房产
    "核酸", "疫苗", "防控",              # 防疫
    "铁路规划", "高速公路规划",          # 基础设施规划（非补贴）
]


def is_policy_article(title: str) -> bool:
    """判断标题是否为政策文章"""
    if not title or len(title) < 8:
        return False
    if any(kw in title for kw in EXCLUDE_KW):
        return False
    return any(kw in title for kw in POLICY_KW)


def guess_source_name(url: str) -> str:
    """根据 URL 猜测来源名称"""
    url_lower = url.lower()
    if "shqp.gov.cn" in url_lower: return "青浦区人民政府"
    if "rsj.sh.gov.cn" in url_lower: return "上海市人社局"
    if "sheitc.sh.gov.cn" in url_lower: return "上海市经信委"
    if "fgw.sh.gov.cn" in url_lower: return "上海市发改委"
    if "stcsm.sh.gov.cn" in url_lower: return "上海市科委"
    if "jtw.sh.gov.cn" in url_lower: return "上海市交通委"
    if "sww.sh.gov.cn" in url_lower: return "上海市商务委"
    if "mot.gov.cn" in url_lower: return "交通运输部"
    if "miit.gov.cn" in url_lower: return "工信部"
    if "ndrc.gov.cn" in url_lower: return "国家发改委"
    if "spb.gov.cn" in url_lower: return "国家邮政局"
    if "caac.gov.cn" in url_lower: return "民航局"
    if "gov.cn" in url_lower: return "政府官网"
    return "政府网站"


def guess_region(text: str) -> list:
    """从文本中提取地域"""
    regions = []
    if "青浦" in text: regions.append("青浦")
    if any(k in text for k in ["上海", "沪"]): regions.append("上海")
    if any(k in text for k in ["国家", "国务院"]): regions.append("国家")
    if not regions: regions.append("上海")
    return regions


def extract_article_links(html: str, base_url: str) -> list:
    """从列表页提取文章链接"""
    soup = BeautifulSoup(html, "lxml")
    links = []

    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        if not is_policy_article(title):
            continue
        href = a["href"]
        full_url = urljoin(base_url, href)
        if not full_url.startswith("http"):
            continue
        links.append({
            "title": title,
            "url": full_url,
        })
    return links


def fetch_article_content(url: str, timeout: int = 12) -> dict:
    """抓取单篇文章，返回结构化内容"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code >= 400:
            return None

        # 检测编码
        resp.encoding = resp.apparent_encoding or "utf-8"
        html = resp.text

        soup = BeautifulSoup(html, "lxml")

        # 移除脚本和样式
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        # 提取标题
        title = ""
        for sel in ["h1", ".article-title", ".title", "#title", "[class*='title']"]:
            el = soup.select_one(sel)
            if el:
                title = el.get_text(strip=True)
                break
        if not title:
            title_tag = soup.find("title")
            if title_tag:
                title = title_tag.get_text(strip=True)

        # 提取正文（常见政府正文区域选择器）
        content = ""
        for sel in ["#zoom", ".article-content", ".article-detail", ".TRS_Editor",
                    ".content", ".news-content", "[class*='content']",
                    "[class*='article']"]:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(separator="\n", strip=True)
                if len(text) > 200:
                    content = text[:3000]
                    break

        if not content:
            # 兜底：取所有段落
            paras = [p.get_text(strip=True) for p in soup.find_all("p") if p.get_text(strip=True)]
            if paras:
                content = "\n".join(paras)[:3000]

        # 提取日期
        date_text = ""
        for sel in [".date", ".time", ".info-date", ".article-date",
                    "[class*='date']", "[class*='time']"]:
            el = soup.select_one(sel)
            if el:
                date_text = el.get_text(strip=True)
                break

        # 标准化日期
        date_match = re.search(r"(\d{4})[年\-\/](\d{1,2})[月\-\/](\d{1,2})", date_text)
        if date_match:
            published = f"{date_match.group(1)}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"
        else:
            published = ""

        return {
            "title": title[:300] if title else "",
            "content": content,
            "published": published,
            "url": url,
        }

    except Exception as e:
        return None


def guess_level(url: str) -> str:
    url_lower = url.lower()
    if "shqp.gov.cn" in url_lower: return "district"
    if any(k in url_lower for k in ["sh.gov.cn", "sheitc", "fgw.sh", "rsj.sh"]): return "municipal"
    return "national"


def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="政府 HTML 页面抓取（requests+bs4 静态）")
    parser.add_argument("--output-dir", default="data", help="输出目录")
    parser.add_argument("--limit", type=int, default=80, help="最大抓取文章数")
    args = parser.parse_args()

    print(f"{'='*60}")
    print(f"政府 HTML 抓取（纯静态 requests+bs4）")
    print(f"{'='*60}")

    # Step 1: 收集所有文章链接
    print("\n[Step 1] 扫描列表页...")
    all_links = []
    for source_name, urls in SEED_SECTIONS.items():
        for url in urls:
            print(f"  扫描 {source_name}: {url[-50:]}")
            try:
                resp = requests.get(url, headers=HEADERS, timeout=12)
                resp.raise_for_status()
                resp.encoding = resp.apparent_encoding or "utf-8"
                links = extract_article_links(resp.text, url)
                print(f"    -> {len(links)} 篇政策文章")
                for link in links[:20]:  # 每源最多20条（增加）
                    all_links.append({
                        **link,
                        "source": source_name,
                        "list_url": url,
                    })
                time.sleep(random.uniform(1.0, 2.0))
            except Exception as e:
                print(f"    ⚠️ {e}")
                continue

    print(f"\n共发现 {len(all_links)} 篇待抓取")

    # Step 2: 并发抓取正文
    print(f"\n[Step 2] 抓取正文（并发 {min(8, len(all_links))} 个线程）...")

    articles = []

    def fetch_one(link):
        time.sleep(random.uniform(0.5, 1.5))
        result = fetch_article_content(link["url"])
        if result:
            result["source"] = link["source"]
            result["list_url"] = link["list_url"]
            result["level"] = guess_level(link["url"])
        return result

    max_workers = min(8, len(all_links))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_one, link): link for link in all_links[:args.limit]}
        for i, future in enumerate(as_completed(futures), 1):
            link = futures[future]
            try:
                result = future.result()
                if result and result.get("content"):
                    print(f"  [{i}/{len(futures)}] ✅ {result.get('title', '')[:40]}")
                    articles.append(result)
                else:
                    print(f"  [{i}/{len(futures)}] ❌ {link['url'][-60:]}")
            except Exception as e:
                print(f"  [{i}/{len(futures)}] ⚠️ {e}")

    print(f"\n成功抓取 {len(articles)} 篇")

    # Step 3: 提取标签和地域
    for art in articles:
        text = (art.get("title", "") + " " + art.get("content", "")[:500]).lower()
        tags = []
        if any(k in text for k in ["低空", "无人机", "eVTOL", "空域"]): tags.append("低空经济")
        if any(k in text for k in ["补贴", "扶持", "资助", "奖励", "专项"]): tags.append("财税补贴")
        if any(k in text for k in ["物流", "快递", "货运", "仓储", "供应链"]): tags.append("物流快递")
        if any(k in text for k in ["数字化", "数智化", "信息化"]): tags.append("数字化")
        if any(k in text for k in ["高企", "高新", "科小", "研发"]): tags.append("高企认定")
        if any(k in text for k in ["申报", "认定", "备案", "项目"]): tags.append("政策申报")
        if not tags: tags.append("政策申报")
        art["tags"] = list(set(tags))
        art["regions"] = guess_region(text)
        art["type"] = "static"
        art["fetched_at"] = datetime.now(timezone.utc).isoformat()
        art["id"] = f"static_{abs(hash(art['url'])) % 10**8}"

    # Step 4: 保存
    out_path = Path(args.output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    output_file = out_path / "gov-pages.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total": len(articles),
            "items": articles,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n保存: {output_file} ({len(articles)} 篇)")


if __name__ == "__main__":
    main()
