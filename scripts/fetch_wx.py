#!/usr/bin/env python3
"""
fetch_wx.py — 微信公众号政策情报抓取
通过 RSSHub 将微信公众号转为标准 RSS 再抓取

用法:
    python scripts/fetch_wx.py --output-dir data --window-hours 48
    # 需要先启动 RSSHub: docker run -d -p 1200:1200 diygod/rsshub
"""

import argparse
import json
import time
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import feedparser
import requests

# RSSHub 实例（需要私有部署）
RSSHUB_BASE = "http://localhost:1200"

# 微信公众号 RSS 路由
WX_SOURCES = [
    # (name, wx_id, route, region, tags)
    ("上海发布", "wechat_mp", "wx16a0981d82ea9ed8", "上海", "政策,补贴,公告"),
    ("上海经信委", "wechat_mp", "wx7d4d3c0a70cd9a5e", "上海", "数字化,补贴,产业"),
    ("上海科委", "wechat_mp", "wx7dae0e0d0e0b", "上海", "高企,科小,科技"),
    ("上海人社", "wechat_mp", "wx1b8aef80d4da8e2a", "上海", "职业,补贴,人才"),
    ("青浦发布", "wechat_mp", "wx9c60f0e3e9a0e1b", "青浦", "补贴,政策,公告"),
    ("国家邮政局", "wechat_mp", "wx4a9d3c5e8f0e1234", "国家", "快递,监管"),
    ("交通运输部", "wechat_mp", "wx5e0a1b2c3d4f5e6a", "国家", "交通,物流"),
    ("物流沙龙", "wechat_mp", "wx6a7b8c9d0e1f2a3b", "全国", "物流,行业,分析"),
]

# 政策关键词（用于过滤）
POLICY_KEYWORDS = [
    "补贴", "申报", "认定", "资助", "扶持", "通知", "公告", "办法",
    "细则", "政策", "项目", "资金", "奖励", "减负", "优惠",
    "物流", "快递", "仓储", "运输", "低空", "无人机", "数字",
    "职业", "技能", "培训", "就业", "人才", "高企", "科小",
]


def fetch_rss(source_name: str, route: str, wx_id: str, timeout: int = 30) -> Optional[dict]:
    """
    通过 RSSHub 获取微信公众号 RSS
    """
    rss_url = f"{RSSHUB_BASE}/{route}/{wx_id}"
    try:
        resp = requests.get(rss_url, timeout=timeout)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        return {"feed": feed, "url": rss_url}
    except requests.exceptions.Timeout:
        print(f"  [TIMEOUT] {source_name}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  [ERROR] {source_name}: {e}", file=sys.stderr)
        return None


def is_policy_related(title: str, summary: str) -> bool:
    """判断是否与政策相关"""
    text = (title + " " + summary).lower()
    return any(k in text for k in POLICY_KEYWORDS)


def classify_item(title: str, content: str, region: str) -> dict:
    """打标签"""
    text = (title + " " + content).lower()
    tags = []
    regions = [region]

    if "青浦" in text:
        regions.append("青浦")
    if any(k in text for k in ["上海", "沪"]):
        regions.append("上海")
    if any(k in text for k in ["长三角", "一体化", "示范区"]):
        regions.append("长三角")
    if any(k in text for k in ["国务院", "国家", "部"]):
        regions.append("国家")

    if any(k in text for k in ["低空", "无人机", "eVTOL", "无人配送"]):
        tags.append("低空经济")
    if any(k in text for k in ["补贴", "扶持", "资助", "专项资金", "减负"]):
        tags.append("财税补贴")
    if any(k in text for k in ["物流", "快递", "仓储", "运输"]):
        tags.append("物流科技")
    if any(k in text for k in ["申报", "认定", "备案", "项目", "通知", "公告"]):
        tags.append("政策申报")
    if any(k in text for k in ["职业", "培训", "技能", "人才"]):
        tags.append("职业培训")
    if any(k in text for k in ["招聘", "求职", "公务员", "事业单位"]):
        tags.append("招聘求职")
    if any(k in text for k in ["监管", "合规", "处罚", "违法"]):
        tags.append("监管合规")
    if any(k in text for k in ["高企", "高新", "科小", "成果转化"]):
        tags.append("高企认定")

    if not tags:
        tags.append("政策申报")

    return {
        "tags": list(set(tags)),
        "regions": list(set(regions)),
    }


def fetch_all_sources(window_hours: int = 48, delay: float = 1.0) -> list:
    """批量抓取所有微信公众号"""
    items = []
    cutoff = datetime.now(timezone.utc).timestamp() - window_hours * 3600

    for i, (name, route, wx_id, region, _) in enumerate(WX_SOURCES):
        print(f"[{i+1}/{len(WX_SOURCES)}] 抓取: {name}")

        result = fetch_rss(name, route, wx_id)
        if not result:
            print(f"  -> 失败")
            time.sleep(delay)
            continue

        feed = result["feed"]
        count = 0
        for entry in feed.entries[:20]:  # 最多取20条
            published_ts = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    from time import mktime
                    published_ts = mktime(entry.published_parsed)
                except Exception:
                    pass

            # 过滤时间窗口
            if published_ts and published_ts < cutoff:
                continue

            title = getattr(entry, "title", "")
            link = getattr(entry, "link", "")
            summary = getattr(entry, "summary", "")[:500]
            if not title:
                continue

            # 政策过滤
            if not is_policy_related(title, summary):
                continue

            tags_info = classify_item(title, summary, region)

            item = {
                "id": f"wx_{hash(link) % 10**8}",
                "title": title,
                "url": link,
                "source": name,
                "region": region,
                "summary": summary,
                "content": summary,
                "published_at": getattr(entry, "published", datetime.now(timezone.utc).isoformat()),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "type": "wechat",
                **tags_info,
            }
            items.append(item)
            count += 1

        print(f"  -> OK: {count} 条政策相关")
        time.sleep(delay)

    return items


def save_output(items: list, output_dir: str):
    """保存为 JSON"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    output = {
        "generated_at": now.isoformat(),
        "total": len(items),
        "sources": list(set(it["source"] for it in items)),
        "items": items,
    }

    out_file = output_path / "latest-wechat.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n输出: {out_file} ({len(items)} 条)")


def main():
    parser = argparse.ArgumentParser(description="微信公众号政策情报抓取")
    parser.add_argument("--output-dir", default="data", help="输出目录")
    parser.add_argument("--window-hours", type=int, default=48, help="时间窗口（小时）")
    parser.add_argument("--delay", type=float, default=1.0, help="请求间隔（秒）")
    args = parser.parse_args()

    print(f"=" * 60)
    print(f"微信公众号政策情报抓取")
    print(f"信源数: {len(WX_SOURCES)} | 时间窗口: {args.window_hours}h")
    print(f"RSSHub: {RSSHUB_BASE}")
    print(f"=" * 60)

    items = fetch_all_sources(window_hours=args.window_hours, delay=args.delay)
    save_output(items, args.output_dir)


if __name__ == "__main__":
    main()
