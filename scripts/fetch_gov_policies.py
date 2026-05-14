#!/usr/bin/env python3
"""
政府网站政策抓取器 v2 (Gov Policy Fetcher)

支持:
- 发改委 (www.ndrc.gov.cn)
- 工信部 (www.miit.gov.cn)
- 上海经信委 (www.sheitc.sh.gov.cn)
- 青浦区政府 (www.shqp.gov.cn)

用法:
    python scripts/fetch_gov_policies.py --source ndrc --limit 20
    python scripts/fetch_gov_policies.py --all --limit 30
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent))

UTC = timezone.utc

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
}


# 政府网站配置
SOURCES = {
    # 综合性政策 (发改委)
    "ndrc": {
        "name": "国家发改委",
        "base_url": "https://www.ndrc.gov.cn",
        "list_url": "https://www.ndrc.gov.cn/xxgk/zcfb/tz/",
        "encoding": "utf-8"
    },
    # 工信部
    "miit": {
        "name": "工信部",
        "base_url": "https://www.miit.gov.cn",
        "list_url": "https://www.miit.gov.cn/zwgk/zcwj/",
        "encoding": "utf-8"
    },
    # 交通运输部 (物流/快递/车辆相关)
    "mot": {
        "name": "交通运输部",
        "base_url": "https://www.mot.gov.cn",
        "list_url": "https://www.mot.gov.cn/zhengcejiedu/",
        "encoding": "utf-8"
    },
    # 商务部 (流通/物流/供应链)
    "mofcom": {
        "name": "商务部",
        "base_url": "http://www.mofcom.gov.cn",
        "list_url": "http://www.mofcom.gov.cn/article/zcfb/",
        "encoding": "utf-8"
    },
    # 国家邮政局 (快递相关)
    "spb": {
        "name": "国家邮政局",
        "base_url": "https://www.spb.gov.cn",
        "list_url": "https://www.spb.gov.cn/xxgk/",
        "encoding": "utf-8"
    },
    # 上海经信委 (上海AI/物流政策)
    "sheitc": {
        "name": "上海经信委",
        "base_url": "https://www.sheitc.sh.gov.cn",
        "list_url": "https://www.sheitc.sh.gov.cn/zwgk/tz/",
        "encoding": "utf-8"
    },
    # 上海科委 (上海科技创新政策)
    "stcsm": {
        "name": "上海科委",
        "base_url": "https://stcsm.sh.gov.cn",
        "list_url": "https://stcsm.sh.gov.cn/zwgk/tz/",
        "encoding": "utf-8"
    },
    # 青浦区政府 (地方政策)
    "qingpu": {
        "name": "青浦区政府",
        "base_url": "http://www.shqp.gov.cn",
        "list_url": "http://www.shqp.gov.cn/zwgk/tzgg/",
        "encoding": "utf-8"
    }
}


def fetch_page(url: str, encoding: str = "utf-8") -> Optional[str]:
    """抓取页面"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.encoding = encoding
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  抓取失败: {e}")
        return None


def parse_ndrc(html: str, base_url: str) -> list:
    """解析发改委页面"""
    soup = BeautifulSoup(html, "html.parser")
    items = []

    # 发改委用 li > a 结构
    for li in soup.select("li"):
        a = li.select_one("a")
        if not a:
            continue

        title = a.get("title") or a.get_text(strip=True)
        href = a.get("href", "")

        # 跳过无关链接
        if not title or len(title) < 10:
            continue
        if any(kw in title for kw in ["更多", "展开", "收起", "关于本", "当前位置"]):
            continue

        # 只保留通知类
        if not any(kw in title for kw in ["通知", "公告", "意见", "办法", "指南", "公示"]):
            continue

        # 补全URL
        if href.startswith("./"):
            href = base_url + "/xxgk/zcfb/tz/" + href[2:]
        elif href.startswith("../"):
            href = base_url + "/xxgk/" + href.replace("../", "")
        elif not href.startswith("http"):
            href = base_url + href

        items.append({
            "title": title,
            "url": href,
            "source": "国家发改委"
        })

    return items


def parse_miit(html: str, base_url: str) -> list:
    """解析工信部页面"""
    soup = BeautifulSoup(html, "html.parser")
    items = []

    for li in soup.select("li"):
        a = li.select_one("a")
        if not a:
            continue

        title = a.get("title") or a.get_text(strip=True)
        href = a.get("href", "")

        if not title or len(title) < 10:
            continue
        if any(kw in title for kw in ["更多", "搜索", "网", "邮箱"]):
            continue

        if not any(kw in title for kw in ["通知", "公告", "意见", "办法", "指南", "公示"]):
            continue

        if href.startswith("./"):
            href = base_url + "/zwgk/zcwj/" + href[2:]
        elif not href.startswith("http"):
            href = base_url + href

        items.append({
            "title": title,
            "url": href,
            "source": "工信部"
        })

    return items


def parse_sheitc(html: str, base_url: str) -> list:
    """解析上海经信委页面"""
    soup = BeautifulSoup(html, "html.parser")
    items = []

    for li in soup.select("li"):
        a = li.select_one("a")
        if not a:
            continue

        title = a.get("title") or a.get_text(strip=True)
        href = a.get("href", "")

        if not title or len(title) < 8:
            continue

        # 补全URL
        if href.startswith("./"):
            href = base_url + "/zwgk/tz/" + href[2:]
        elif href.startswith("/"):
            href = base_url + href
        elif not href.startswith("http"):
            href = base_url + "/" + href

        items.append({
            "title": title,
            "url": href,
            "source": "上海经信委"
        })

    return items


def parse_qingpu(html: str, base_url: str) -> list:
    """解析青浦区政府页面"""
    soup = BeautifulSoup(html, "html.parser")
    items = []

    for li in soup.select("li"):
        a = li.select_one("a")
        if not a:
            continue

        title = a.get("title") or a.get_text(strip=True)
        href = a.get("href", "")

        if not title or len(title) < 8:
            continue

        # 补全URL
        if href.startswith("./"):
            href = base_url + "/zwgk/tzgg/" + href[2:]
        elif not href.startswith("http"):
            href = base_url + href

        items.append({
            "title": title,
            "url": href,
            "source": "青浦区政府"
        })

    return items


PARSERS = {
    "ndrc": parse_ndrc,
    "miit": parse_miit,
    "sheitc": parse_sheitc,
    "stcsm": parse_sheitc,  # 同结构
    "qingpu": parse_qingpu
}


def fetch_source(source_id: str, limit: int = 20) -> list:
    """抓取指定源"""
    if source_id not in SOURCES:
        print(f"未知源: {source_id}")
        return []

    config = SOURCES[source_id]
    print(f"\n抓取 {config['name']}...")

    html = fetch_page(config["list_url"], config["encoding"])
    if not html:
        return []

    parser = PARSERS.get(source_id, parse_ndrc)
    items = parser(html, config["base_url"])

    print(f"  获取 {len(items)} 条")

    return items[:limit]


def fetch_all(limit_per_source: int = 30) -> list:
    """抓取所有源"""
    all_items = []

    for source_id in SOURCES:
        items = fetch_source(source_id, limit_per_source)
        all_items.extend(items)

    # 去重
    seen = set()
    unique = []
    for item in all_items:
        key = item["title"].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(item)

    return unique


def save_items(items: list, output_file: str = None):
    """保存结果"""
    if output_file is None:
        output_file = Path(__file__).parent.parent / "data" / "gov-fetched.json"

    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    output = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "total": len(items),
        "items": items
    }

    output_file.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\n保存到: {output_file}")
    return output_file


def main():
    parser = argparse.ArgumentParser(description="政府政策抓取器")
    parser.add_argument("--source", "-s", help="源: ndrc/miit/sheitc/stcsm/qingpu")
    parser.add_argument("--all", "-a", action="store_true", help="抓取所有源")
    parser.add_argument("--limit", "-n", type=int, default=30, help="每源数量")
    parser.add_argument("--output", "-o", help="输出文件")

    args = parser.parse_args()

    if args.source:
        items = fetch_source(args.source, args.limit)
    else:
        items = fetch_all(args.limit)

    if items:
        save_items(items, args.output)
        print("\n结果:")
        for item in items[:8]:
            print(f"  - {item['title'][:45]} ({item['source']})")
    else:
        print("\n未获取到数据")


if __name__ == "__main__":
    main()
