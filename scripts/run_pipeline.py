#!/usr/bin/env python3
"""
政策处理主管道 (Policy Pipeline)

功能:
1. 抓取政策RSS
2. 解析政策全文 (LLM)
3. 企业匹配
4. 政策评分
5. 风险过滤
6. 生成申报建议

用法:
    python scripts/run_pipeline.py --fetch-only
    python scripts/run_pipeline.py --parse-only
    python scripts/run_pipeline.py --full
    python scripts/run_pipeline.py --test
"""

from __future__ import annotations

import argparse
import json
import sys
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 导入各模块
from scripts.parse_policy import (
    parse_single, load_policy,
    save_parsed_policy, OUTPUT_DIR as POLICIES_DIR
)
from scripts.match_policy import (
    PolicyMatcher, load_enterprise_profile, MATCH_HISTORY_FILE
)
from scripts.score_policy import PolicyScorer, SCORE_HISTORY_FILE
from scripts.risk_filter import PolicyRiskFilter, RISK_HISTORY_FILE

UTC = timezone.utc

# 数据目录
DATA_DIR = Path(__file__).parent.parent / "data"
RSS_DIR = DATA_DIR / "rss_cache"
FINAL_OUTPUT = DATA_DIR / "policy-opportunities.json"


@dataclass
class PolicyOpportunity:
    """政策机会最终输出"""
    id: str
    title: str
    url: str
    source: str
    source_level: str
    published_at: str
    deadline: str
    days_left: int

    # 解析结果
    parsed: dict

    # 匹配结果
    match_score: float
    matched_tags: list
    missing_tags: list

    # 评分结果
    score: float
    level: str
    priority: str
    dimensions: dict
    is_pre_subsidy: bool

    # 风险结果
    risk_level: str
    risk_score: float
    risk_advice: str
    is_worth_applying: bool

    # ROI
    roi: dict

    # 申报建议
    recommended_project: str
    packaging_keywords: list
    reasons: list
    warnings: list

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "source_level": self.source_level,
            "published_at": self.published_at,
            "deadline": self.deadline,
            "days_left": self.days_left,
            "match_score": self.match_score,
            "matched_tags": self.matched_tags,
            "missing_tags": self.missing_tags,
            "score": self.score,
            "level": self.level,
            "priority": self.priority,
            "is_pre_subsidy": self.is_pre_subsidy,
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "risk_advice": self.risk_advice,
            "is_worth_applying": self.is_worth_applying,
            "roi": self.roi,
            "recommended_project": self.recommended_project,
            "packaging_keywords": self.packaging_keywords,
            "reasons": self.reasons,
            "warnings": self.warnings
        }


def parse_rss_feeds(opml_file: str = None, limit: int = 50) -> list:
    """抓取RSS源"""
    try:
        import feedparser
    except ImportError:
        print("需要安装 feedparser: pip install feedparser")
        return []

    if opml_file is None:
        opml_file = Path(__file__).parent.parent / "feeds" / "policy.example.opml"

    opml_path = Path(opml_file)
    if not opml_path.exists():
        print(f"OPML文件不存在: {opml_file}")
        return []

    # 解析OPML
    import xml.etree.ElementTree as ET
    tree = ET.parse(opml_path)
    root = tree.getroot()

    items = []
    for outline in root.iter("outline"):
        xml_url = outline.get("xmlUrl") or outline.get("xml_url")
        title = outline.get("title", "")
        html_url = outline.get("htmlUrl", "")
        category = outline.get("category", "")
        priority = outline.get("priority", "P1")

        if not xml_url:
            continue

        try:
            feed = feedparser.parse(xml_url)
            for entry in feed.entries[:limit]:
                item = {
                    "title": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "source": title,
                    "category": category,
                    "priority": priority,
                    "published": entry.get("published", "")
                }
                items.append(item)
        except Exception as e:
            print(f"  ⚠️ 抓取失败 {title}: {e}")
            continue

    return items


def process_policy(item: dict, profile) -> Optional[PolicyOpportunity]:
    """处理单个政策"""

    url = item.get("url", "")
    title = item.get("title", "")
    source = item.get("source", "")

    if not url or not title:
        return None

    print(f"\n[处理] {title[:50]}...")

    # 1. 解析政策
    parsed = parse_single(
        url=url,
        title=title,
        source=source,
        source_level=item.get("priority", ""),
        published_at=item.get("published", "")
    )

    if parsed.parse_error:
        print(f"  ❌ 解析失败，跳过")
        return None

    # 2. 企业匹配
    matcher = PolicyMatcher(profile)
    match_result = matcher.match(parsed.to_dict())

    # 3. 政策评分
    scorer = PolicyScorer()
    score_result = scorer.score(
        parsed.to_dict(),
        match_result.total_score,
        match_result.matched_tags,
        match_result.missing_tags
    )

    # 4. 风险过滤
    risk_filter = PolicyRiskFilter()
    risk_result = risk_filter.filter(parsed.to_dict(), profile.__dict__)

    # 5. 生成申报建议
    project_name = _generate_project_name(parsed, profile)
    keywords = _generate_packaging_keywords(parsed, profile)

    # 计算剩余天数
    days_left = 0
    deadline = parsed.parsed.申报截止时间
    if deadline:
        try:
            from datetime import datetime
            deadline_dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
            days_left = (deadline_dt - datetime.now(UTC)).days
        except Exception:
            pass

    return PolicyOpportunity(
        id=parsed.id,
        title=parsed.title,
        url=url,
        source=source,
        source_level=parsed.source_level or parsed.parsed.级别,
        published_at=parsed.published_at,
        deadline=deadline or "",
        days_left=days_left,
        parsed=parsed.parsed.to_dict(),
        match_score=match_result.total_score,
        matched_tags=match_result.matched_tags,
        missing_tags=match_result.missing_tags,
        score=score_result.final,
        level=score_result.level,
        priority=score_result.priority,
        dimensions=score_result.dimensions,
        is_pre_subsidy=score_result.is_pre_subsidy,
        risk_level=risk_result.risk_level,
        risk_score=risk_result.risk_score,
        risk_advice=risk_result.advice,
        is_worth_applying=risk_result.is_worth_applying and score_result.final >= 50,
        roi=score_result.roi,
        recommended_project=project_name,
        packaging_keywords=keywords,
        reasons=score_result.reasons,
        warnings=score_result.warnings + [r["risk_point"] for r in risk_result.detailed_risks]
    )


def _generate_project_name(parsed, profile) -> str:
    """生成建议项目名称"""
    # 优先使用企业已有项目匹配
    for project in profile.key_projects:
        project_keywords = project.get("keywords", [])
        for kw in project_keywords:
            if kw in str(parsed.支持方向) or kw in str(parsed.政策原文关键词):
                return project["name"]

    # 默认包装
    directions = parsed.支持方向[:2] if parsed.支持方向 else []
    if directions:
        return f"{directions[0]}示范项目"
    return "智慧物流建设项目"


def _generate_packaging_keywords(parsed, profile) -> list:
    """生成包装关键词"""
    keywords = []

    # 从政策支持方向提取
    for kw in parsed.支持方向:
        keywords.append(kw)

    # 添加热点关键词
    hot_keywords = ["新质生产力", "补链强链", "数字化转型", "智慧物流"]
    for kw in hot_keywords:
        if kw not in keywords:
            keywords.append(kw)

    return keywords[:8]


def run_pipeline(limit: int = 20, only_new: bool = True):
    """运行完整管道"""

    print("=" * 60)
    print("政策处理管道启动")
    print("=" * 60)

    # 1. 加载企业画像
    print("\n[1/5] 加载企业画像...")
    profile = load_enterprise_profile("ztj")
    print(f"  企业: {profile.name}")

    # 2. 抓取RSS
    print("\n[2/5] 抓取政策RSS...")
    items = parse_rss_feeds(limit=limit)
    print(f"  获取 {len(items)} 条政策")

    if not items:
        print("  ⚠️ 未获取到政策，请检查RSS源配置")
        return

    # 3. 解析+匹配+评分+过滤
    print("\n[3/5] 处理政策...")
    opportunities = []
    for i, item in enumerate(items):
        print(f"\n[{i+1}/{len(items)}]")
        opp = process_policy(item, profile)
        if opp:
            opportunities.append(opp)
            print(f"  ✅ {opp.level}级 {opp.score:.1f}分 P{opp.priority[-1]}")

    if not opportunities:
        print("\n⚠️ 没有生成有效政策机会")
        return

    # 4. 过滤不值得申报的
    print("\n[4/5] 过滤风险...")
    before_count = len(opportunities)
    opportunities = [o for o in opportunities if o.is_worth_applying]
    print(f"  过滤后: {len(opportunities)}/{before_count} 条值得申报")

    # 5. 排序+输出
    print("\n[5/5] 生成最终报告...")
    opportunities.sort(key=lambda x: (x.score, x.match_score), reverse=True)

    output = {
        "generated_at": datetime.now(UTC).isoformat(),
        "total": len(opportunities),
        "high_priority": len([o for o in opportunities if o.priority in ["P0", "P1"]]),
        "by_level": {
            "S": len([o for o in opportunities if o.level == "S"]),
            "A": len([o for o in opportunities if o.level == "A"]),
            "B": len([o for o in opportunities if o.level == "B"]),
        },
        "opportunities": [o.to_dict() for o in opportunities]
    }

    FINAL_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    FINAL_OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  保存到: {FINAL_OUTPUT}")

    # 打印摘要
    print("\n" + "=" * 60)
    print("政策机会摘要")
    print("=" * 60)

    level_emoji = {"S": "🔥", "A": "⭐", "B": "📋", "C": "📁"}
    for o in opportunities[:10]:
        emoji = level_emoji.get(o.level, "📁")
        worth = "✅" if o.is_worth_applying else "❌"
        print(f"\n{emoji}{o.level} {o.score:.1f}分 {o.priority} {worth}")
        print(f"  {o.title[:60]}")
        print(f"  💰 {o.roi.get('subsidy', 0)}万 | "
              f"📈 ROI: {o.roi.get('roi_label', '?')} | "
              f"⏰ {o.days_left}天")
        if o.recommended_project:
            print(f"  📦 建议项目: {o.recommended_project}")


def main():
    parser = argparse.ArgumentParser(description="政策处理管道")
    parser.add_argument("--fetch-only", action="store_true", help="仅抓取RSS")
    parser.add_argument("--parse-only", action="store_true", help="仅解析政策")
    parser.add_argument("--full", action="store_true", help="完整流程")
    parser.add_argument("--test", action="store_true", help="测试模式")
    parser.add_argument("--limit", type=int, default=20, help="处理数量限制")

    args = parser.parse_args()

    if args.test or args.full:
        run_pipeline(limit=args.limit)
    elif args.fetch_only:
        items = parse_rss_feeds(limit=args.limit)
        print(f"获取 {len(items)} 条政策")
        for item in items[:5]:
            print(f"  - {item['title'][:50]}")
    else:
        parser.print_help()


if __name__ == "__main__":
    from dataclasses import dataclass
    main()
