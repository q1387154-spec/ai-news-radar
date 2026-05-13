#!/usr/bin/env python3
"""
merge.py — 合并政府官网 + 微信公众号数据
输出 latest.json 供前端使用

用法:
    python scripts/merge.py --output-dir data
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


def load_json(path: Path) -> dict:
    """安全加载 JSON 文件"""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def merge_items(gov_items: list, wx_items: list, window_hours: int = 72) -> list:
    """
    合并并去重，按时间排序
    """
    cutoff = datetime.now(timezone.utc).timestamp() - window_hours * 3600

    all_items = []
    seen_urls = set()

    for item in gov_items + wx_items:
        url = item.get("url", "")
        if not url or url in seen_urls:
            continue
        # 时间过滤
        published = item.get("published_at", "")
        if published:
            try:
                dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                if dt.timestamp() < cutoff:
                    continue
            except Exception:
                pass
        seen_urls.add(url)
        all_items.append(item)

    # 按时间倒序
    all_items.sort(
        key=lambda x: x.get("published_at", ""),
        reverse=True
    )
    return all_items


def classify_region(item: dict) -> dict:
    """确保有地域标签"""
    if item.get("regions"):
        return item
    return {**item, "regions": ["上海"]}


def build_output(gov_data: dict, wx_data: dict, window_hours: int) -> dict:
    """构建最终输出"""
    gov_items = gov_data.get("items", [])
    wx_items = wx_data.get("items", [])

    merged = merge_items(gov_items, wx_items, window_hours)
    merged = [classify_region(it) for it in merged]

    # 统计
    all_tags = {}
    all_regions = {}
    for item in merged:
        for tag in item.get("tags", []):
            all_tags[tag] = all_tags.get(tag, 0) + 1
        for region in item.get("regions", []):
            all_regions[region] = all_regions.get(region, 0) + 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": window_hours,
        "total": len(merged),
        "gov_total": len(gov_items),
        "wechat_total": len(wx_items),
        "tags": all_tags,
        "regions": all_regions,
        "items": merged,
    }


def main():
    parser = argparse.ArgumentParser(description="合并政策情报数据")
    parser.add_argument("--output-dir", default="data", help="输出目录")
    parser.add_argument("--window-hours", type=int, default=72, help="时间窗口")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)

    gov_data = load_json(output_dir / "latest-gov.json")
    wx_data = load_json(output_dir / "latest-wechat.json")

    print(f"政府官网: {gov_data.get('total', 0)} 条")
    print(f"微信公众号: {wx_data.get('total', 0)} 条")

    output = build_output(gov_data, wx_data, args.window_hours)

    out_file = output_dir / "latest.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n最终输出: {out_file} ({output['total']} 条)")
    print(f"地域分布: {output['regions']}")
    print(f"标签分布: {output['tags']}")


if __name__ == "__main__":
    main()
