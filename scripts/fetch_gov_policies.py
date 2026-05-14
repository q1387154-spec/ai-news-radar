#!/usr/bin/env python3
"""
fetch_gov_policies.py — 政府网站政策抓取器 v3.1 (使用Jina Reader)

支持抓取的政府网站:
- 国家发改委 (ndrc.gov.cn) ✅
- 工信部 (miit.gov.cn) ✅ (支持纯文本格式解析)
- 交通运输部 (mot.gov.cn) ✅
- 商务部 (mofcom.gov.cn) ✅
- 国家邮政局 (spb.gov.cn) ✅
- 上海经信委 (sheitc.sh.gov.cn) ✅
- 上海科委 (stcsm.sh.gov.cn) ✅
- 青浦区政府 (shqp.gov.cn) ✅
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

UTC = timezone.utc

JINA_READER = "https://r.jina.ai/{}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/plain",
    "Accept-Language": "zh-CN,zh;q=0.9"
}

SOURCES = {
    "ndrc": {
        "name": "国家发改委",
        "base_url": "https://www.ndrc.gov.cn",
        "list_url": "https://www.ndrc.gov.cn/xxgk/zcfb/tz/",
    },
    "miit": {
        "name": "工信部",
        "base_url": "https://www.miit.gov.cn",
        "list_url": "https://www.miit.gov.cn/zwgk/zcwj/index.html",
    },
    "mot": {
        "name": "交通运输部",
        "base_url": "https://www.mot.gov.cn",
        "list_url": "https://www.mot.gov.cn/",
    },
    "mofcom": {
        "name": "商务部",
        "base_url": "http://www.mofcom.gov.cn",
        "list_url": "https://www.mofcom.gov.cn/zcfb/",
    },
    "spb": {
        "name": "国家邮政局",
        "base_url": "https://www.spb.gov.cn",
        "list_url": "https://www.spb.gov.cn/",
    },
    "sheitc": {
        "name": "上海经信委",
        "base_url": "https://www.sheitc.sh.gov.cn",
        "list_url": "https://www.sheitc.sh.gov.cn/",
    },
    "stcsm": {
        "name": "上海科委",
        "base_url": "https://stcsm.sh.gov.cn",
        "list_url": "https://stcsm.sh.gov.cn/",
    },
    "qingpu": {
        "name": "青浦区政府",
        "base_url": "https://www.shqp.gov.cn",
        "list_url": "https://www.shqp.gov.cn/",
    }
}

# 政策关键词（用于过滤）
POLICY_KEYWORDS = ["通知", "公告", "意见", "办法", "指南", "公示", "规定",
                   "决定", "方案", "政策", "解读", "批复", "纲要", "规划", "条例"]

IGNORE_KEYWORDS = ["更多", "展开", "收起", "关于本", "当前位置", "联系我们",
                  "网站地图", "无障碍", "繁體", "English", "邮箱", "电话"]


def make_jina_url(url: str) -> str:
    clean = url.replace("https://", "").replace("http://", "")
    return JINA_READER.format(clean)


def fetch_jina(url: str, timeout: int = 15) -> Optional[dict]:
    """使用Jina Reader抓取页面"""
    try:
        resp = requests.get(make_jina_url(url), headers=HEADERS, timeout=timeout)
        resp.raise_for_status()

        lines = resp.text.split("\n")
        result = {"url": url, "title": "", "content": "", "published_at": ""}
        content_start = 0

        for i, line in enumerate(lines):
            if line.startswith("Title:"):
                result["title"] = line[6:].strip()
            elif line.startswith("URL Source:"):
                result["url"] = line[11:].strip()
            elif line.startswith("Published Time:"):
                result["published_at"] = line[15:].strip()
            elif line.startswith("Markdown Content:"):
                content_start = i + 1
                break

        result["content"] = "\n".join(lines[content_start:])
        return result if result["content"] else None
    except Exception as e:
        print(f"  抓取失败: {e}")
        return None


def extract_miit_format(content: str, source_name: str) -> list:
    """解析工信部纯文本条目格式（无URL）"""
    items = []
    # 格式：**名 称：**政策标题**文 号：**工信厅xxx号
    pattern = r'\*\*名\s*称：\*\*([^\*]+)\*\*文\s*号：\*\*([^\n]+)'
    for match in re.finditer(pattern, content):
        title = match.group(1).strip()
        wenhao = match.group(2).strip()
        if len(title) > 10 and any(kw in title for kw in POLICY_KEYWORDS):
            search_url = f'https://www.miit.gov.cn/zwgk/zcwj/search.html?kw={requests.utils.quote(title[:15])}'
            items.append({
                "title": title,
                "url": search_url,
                "source": source_name,
                "wenhao": wenhao
            })
    return items


def extract_links(content: str, base_url: str, source_name: str) -> list:
    """从Jina Reader返回的内容中提取政策条目"""
    items = []

    # 1. Markdown链接格式 [标题](url)
    for title, url in re.findall(r'\[([^\]]{10,})\]\((https?://[^)]+)\)', content):
        title, url = title.strip(), url.strip()
        if any(kw in title for kw in IGNORE_KEYWORDS):
            continue
        if not any(kw in title for kw in POLICY_KEYWORDS):
            continue
        items.append({"title": title, "url": url, "source": source_name})

    # 2. 从text文本中提取URL及其前面的标题行
    for url in re.findall(r'(https?://[^\s<>"\')]\)]{20,})', content):
        if any(ext in url for ext in ['.jpg', '.png', '.pdf', '.doc', '.xls']):
            continue
        if any(nav in url for nav in ['/node', '/index', '/column', '/about', '/static/']):
            continue
        idx = content.find(url)
        before = content[max(0, idx-300):idx]
        # 取最后一行非空文本作为标题
        for line in reversed(before.split('\n')):
            line = line.strip().strip('[]（）【】""''""《》')
            if line and len(line) > 8 and not any(c in line for c in ['http', 'https', 'www']):
                if any(kw in line for kw in POLICY_KEYWORDS):
                    items.append({"title": line, "url": url, "source": source_name})
                    break

    # 3. 工信部纯文本格式（无URL）
    if not items and '名 称：' in content:
        items.extend(extract_miit_format(content, source_name))

    # 去重（按URL）
    seen, unique = set(), []
    for item in items:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)

    return unique


def fetch_source(key: str, limit: int = 20) -> list:
    """抓取单个源"""
    src = SOURCES.get(key)
    if not src:
        return []

    print(f"抓取 {src['name']}...", end=" ", flush=True)

    result = fetch_jina(src["list_url"])
    if not result or not result["content"]:
        print("失败")
        return []

    items = extract_links(result["content"], src["base_url"], src["name"])
    print(f"获取 {len(items)} 条")
    return items[:limit]


def fetch_all(limit_per_source: int = 20) -> list:
    """抓取所有源"""
    all_items = []
    for key in SOURCES:
        all_items.extend(fetch_source(key, limit_per_source))
    return all_items


def main():
    parser = argparse.ArgumentParser(description="政府政策抓取器 v3.1")
    parser.add_argument("--source", default="all")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output", default="data/gov-fetched.json")
    args = parser.parse_args()

    if args.source == "all":
        items = fetch_all(args.limit)
    else:
        items = fetch_source(args.source, args.limit)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    data = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "total": len(items),
        "items": items
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n保存到: {args.output}，共 {len(items)} 条")
    for item in items[:5]:
        print(f"  - {item['title'][:50]}")


if __name__ == "__main__":
    main()
