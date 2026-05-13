#!/usr/bin/env python3
"""
fetch_gov.py — 政府官网政策情报抓取
使用 Jina Reader API 抓取政府网站（无需RSS）

用法:
    python scripts/fetch_gov.py --output-dir data --window-hours 48
"""

import argparse
import json
import time
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

# Jina Reader API（免费，无需Key）
# 注意：Government sites with https:// prefix - strip it before passing to Jina
JINA_READER = "https://r.jina.ai/{}"


def make_jina_url(url: str) -> str:
    """构造 Jina Reader URL，去掉重复的 https://"""
    # 去掉 https:// 或 http:// 前缀
    clean = url.replace("https://", "").replace("http://", "")
    return JINA_READER.format(clean)

# P0 信源列表（青浦/上海市级 - 最高优先级）
SOURCES_P0 = [
    # (name, url, region, tags)
    ("青浦区人民政府", "https://www.shqp.gov.cn", "青浦", "补贴,物流,职业"),
    ("上海市人社局", "https://rsj.sh.gov.cn", "上海", "补贴,职业,高企"),
    ("上海市商务委", "https://sww.sh.gov.cn", "上海", "物流,补贴,流通"),
    ("上海市交通委", "https://jtw.sh.gov.cn", "上海", "物流,交通,降本"),
    ("上海市科委", "https://stcsm.sh.gov.cn", "上海", "高企,科小,数字化"),
]

# P1 信源
SOURCES_P1 = [
    ("上海市经信委", "https://sheitc.sh.gov.cn", "上海", "数字化,补贴,AI"),
    ("上海市税务局", "https://shanghai.chinatax.gov.cn", "上海", "财税,补贴,税收"),
    ("上海市发改委", "https://fgw.sh.gov.cn", "上海", "物流,仓储,投资"),
    ("上海市邮政管理局", "https://sh.spb.gov.cn", "上海", "快递,低空,监管"),
]

# P2 信源（国家层面）
SOURCES_P2 = [
    ("国务院", "https://www.gov.cn", "国家", "政策,交通,物流"),
    ("国家邮政局", "https://www.spb.gov.cn", "国家", "快递,监管"),
    ("交通运输部", "https://www.mot.gov.cn", "国家", "交通,物流"),
    ("工信部", "https://www.miit.gov.cn", "国家", "数字化,AI,新基建"),
    ("国家发改委", "https://www.ndrc.gov.cn", "国家", "投资,物流"),
    ("国家税务总局", "https://www.chinatax.gov.cn", "国家", "财税,税收"),
]

ALL_SOURCES = SOURCES_P0 + SOURCES_P1 + SOURCES_P2

# 低空经济专项关键词（命中后打标）
LOW_ALT_KEYWORDS = ["低空", "无人机", "eVTOL", "飞行汽车", "空域", "低空经济", "无人配送"]
# 物流补贴专项关键词
SUBSIDY_KEYWORDS = ["补贴", "扶持", "资助", "奖励", "专项资金", "减负", "减免"]
# 申报关键词
APPLY_KEYWORDS = ["申报", "认定", "备案", "申请", "截止", "通知"]


def fetch_url(url: str, timeout: int = 30) -> Optional[dict]:
    """
    使用 Jina Reader 抓取 URL，返回结构化内容
    """
    try:
        reader_url = make_jina_url(url)
        headers = {
            "Accept": "text/plain",
        }
        resp = requests.get(reader_url, headers=headers, timeout=timeout + 5)
        resp.raise_for_status()

        # Jina Reader 返回格式：
        # Title: xxx\nURL Source: xxx\nPublished Time: xxx\nMarkdown Content:\n# xxx\n...\n
        text = resp.text
        lines = text.split("\n")
        title = ""
        url_src = url
        published_at = ""
        content_start = 0

        for i, line in enumerate(lines):
            if line.startswith("Title:"):
                title = line[6:].strip()
            elif line.startswith("URL Source:"):
                url_src = line[11:].strip()
            elif line.startswith("Published Time:"):
                published_at = line[15:].strip()
            elif line.startswith("Markdown Content:"):
                content_start = i + 1
                break

        content = "\n".join(lines[content_start:])

        return {
            "url": url_src,
            "title": title or name,
            "content": content,
            "published_at": published_at,
        }
    except requests.exceptions.Timeout:
        print(f"  [TIMEOUT] {url}", file=sys.stderr)
        return None
    except requests.exceptions.HTTPError as e:
        print(f"  [HTTP {e.response.status_code}] {url}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  [ERROR] {url}: {e}", file=sys.stderr)
        return None


def classify_item(item: dict) -> dict:
    """
    根据标题+内容关键词打标签
    """
    text = (item.get("title", "") + " " + item.get("content", "")[:500]).lower()
    tags = []
    regions = []

    # 地域标签
    if "青浦" in text:
        regions.append("青浦")
    if any(k in text for k in ["上海", "沪"]):
        regions.append("上海")
    if any(k in text for k in ["长三角", "一体化", "示范区"]):
        regions.append("长三角")
    if any(k in text for k in ["国务院", "国家", "部", "总局"]):
        regions.append("国家")

    # 内容标签
    if any(k in text for k in LOW_ALT_KEYWORDS):
        tags.append("低空经济")
    if any(k in text for k in SUBSIDY_KEYWORDS):
        tags.append("财税补贴")
    if any(k in text for k in ["物流", "快递", "运输", "仓储"]):
        tags.append("物流科技")
    if any(k in text for k in ["申报", "认定", "备案", "项目", "通知"]):
        tags.append("政策申报")
    if any(k in text for k in ["职业", "培训", "技能", "人才", "就业"]):
        tags.append("职业培训")
    if any(k in text for k in ["招聘", "求职", "招录", "公务员", "事业单位"]):
        tags.append("招聘求职")
    if any(k in text for k in ["监管", "合规", "处罚", "违法", "安全"]):
        tags.append("监管合规")
    if any(k in text for k in ["高企", "高新", "科小", "成果转化", "研发"]):
        tags.append("高企认定")

    # 默认标签
    if not tags:
        tags.append("政策申报")

    return {
        **item,
        "tags": list(set(tags)),
        "regions": list(set(regions)) if regions else ["上海"],
        "is_policy_related": bool(tags),
    }


def fetch_all_sources(
    sources: list,
    window_hours: int = 48,
    delay: float = 1.0,
) -> list:
    """
    批量抓取所有信源，返回结构化items
    """
    items = []
    cutoff = datetime.now(timezone.utc).timestamp() - window_hours * 3600

    for i, (name, url, region, _) in enumerate(sources):
        print(f"[{i+1}/{len(sources)}] 抓取: {name} ({url})")
        result = fetch_url(url)

        if not result or not result.get("content"):
            print(f"  -> 失败或内容为空")
            time.sleep(delay)
            continue

        # 简单解析：政府网站内容通常在 <p> 或特定容器中
        # Jina Reader 已经提取了纯文本，尝试找到正文段落
        content = result.get("content_raw") or result.get("content", "")
        if len(content) < 200:
            print(f"  -> 内容过短，跳过")
            time.sleep(delay)
            continue

        # 取前3个政策相关段落作为摘要
        paragraphs = [p.strip() for p in content.split("\n") if len(p.strip()) > 50][:5]

        item = {
            "id": f"gov_{hash(url) % 10**8}",
            "title": result.get("title", name),
            "url": url,
            "source": name,
            "region": region,
            "summary": " ".join(paragraphs[:3]),
            "content": content[:2000],  # 保留前2000字符
            "published_at": result.get("published_at") or datetime.now(timezone.utc).isoformat(),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "type": "gov",
        }

        item = classify_item(item)
        items.append(item)
        print(f"  -> OK: {item['title'][:50]} | 标签: {item['tags']}")
        time.sleep(delay)

    return items


def save_output(items: list, output_dir: str, window_hours: int):
    """保存为 JSON 文件"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    output = {
        "generated_at": now.isoformat(),
        "window_hours": window_hours,
        "total": len(items),
        "sources": list(set(it["source"] for it in items)),
        "items": items,
    }

    out_file = output_path / "latest-gov.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # 也输出 source-status
    source_status = {}
    for it in items:
        src = it["source"]
        if src not in source_status:
            source_status[src] = {"ok": 0, "fail": 0, "url": it["url"]}
        source_status[src]["ok"] += 1

    status_file = output_path / "source-status-gov.json"
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(source_status, f, ensure_ascii=False, indent=2)

    print(f"\n输出: {out_file} ({len(items)} 条)")
    print(f"信源状态: {status_file}")


def main():
    parser = argparse.ArgumentParser(description="政府官网政策情报抓取")
    parser.add_argument("--output-dir", default="data", help="输出目录")
    parser.add_argument("--window-hours", type=int, default=48, help="时间窗口（小时）")
    parser.add_argument("--priority", choices=["p0", "p1", "p2", "all"], default="all", help="抓取优先级")
    parser.add_argument("--delay", type=float, default=1.0, help="请求间隔（秒）")
    args = parser.parse_args()

    # 选择信源
    if args.priority == "p0":
        sources = SOURCES_P0
    elif args.priority == "p1":
        sources = SOURCES_P1
    elif args.priority == "p2":
        sources = SOURCES_P2
    else:
        sources = ALL_SOURCES

    print(f"=" * 60)
    print(f"政府官网政策情报抓取")
    print(f"信源数: {len(sources)} | 时间窗口: {args.window_hours}h")
    print(f"=" * 60)

    items = fetch_all_sources(sources, window_hours=args.window_hours, delay=args.delay)
    save_output(items, args.output_dir, args.window_hours)


if __name__ == "__main__":
    main()
