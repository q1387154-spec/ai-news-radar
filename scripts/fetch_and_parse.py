#!/usr/bin/env python3
"""
带LLM解析的政府政策抓取管道

流程:
1. 抓取政府网站列表
2. 获取政策全文 (Jina Reader)
3. LLM结构化提取
4. 企业匹配 + 评分

用法:
    python scripts/fetch_and_parse.py --limit 5
"""

from __future__ import annotations

import argparse
import json
import sys
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.parse_policy import parse_single, load_policy, save_parsed_policy, OUTPUT_DIR as POLICIES_DIR
from scripts.match_policy import PolicyMatcher, load_enterprise_profile
from scripts.score_policy import PolicyScorer
from scripts.risk_filter import PolicyRiskFilter
from scripts.fetch_gov_policies import fetch_all, SOURCES

UTC = timezone.utc
DATA_DIR = Path(__file__).parent.parent / "data"
FETCHED_FILE = DATA_DIR / "gov-fetched.json"
OUTPUT_FILE = DATA_DIR / "policy-opportunities.json"


def fetch_gov():
    """抓取政府网站（60分钟内用缓存）"""
    if FETCHED_FILE.exists():
        age = time.time() - FETCHED_FILE.stat().st_mtime
        if age < 3600:
            with open(FETCHED_FILE, encoding='utf-8') as f:
                cached = json.load(f)
            items = cached.get('items', [])
            print(f"抓取完成(缓存): {len(items)} 条")
            seen_urls = set()
            unique = []
            for item in items:
                if item["url"] not in seen_urls:
                    seen_urls.add(item["url"])
                    unique.append(item)
            return unique

    items = fetch_all(limit_per_source=30)

    FETCHED_FILE.parent.mkdir(parents=True, exist_ok=True)
    FETCHED_FILE.write_text(
        json.dumps({"fetched_at": datetime.now(UTC).isoformat(), "items": items}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"抓取完成: {len(items)} 条")

    seen_urls = set()
    unique = []
    for item in items:
        if item["url"] not in seen_urls:
            seen_urls.add(item["url"])
            unique.append(item)

    return unique


def parse_with_llm(items: list, limit: int = 10) -> list:
    """使用LLM解析政策全文"""
    api_key = os.environ.get("MINIMAX_API_KEY", "sk-d0127b5dd6cff018ed0a0075eab22efe")

    parsed = []
    for i, item in enumerate(items[:limit]):
        print(f"\n[{i+1}/{min(len(items), limit)}] 解析: {item['title'][:40]}...")

        try:
            result = parse_single(
                url=item["url"],
                title=item["title"],
                source=item["source"],
                source_level="国家级" if "国家" in item.get("source", "") else "市级"
            )

            if result and not result.parse_error:
                print(f"  ✅ 成功 (置信度: {result.confidence:.0%})")
                if result.parsed.支持方向:
                    print(f"     方向: {', '.join(result.parsed.支持方向[:3])}")
                if result.parsed.支持金额:
                    amt = result.parsed.支持金额.get("金额", 0)
                    print(f"     金额: {amt}万" if amt else "")
                parsed.append(result)
            else:
                print(f"  ❌ 失败: {result.parse_error if result else '未知错误'}")

        except Exception as e:
            print(f"  ❌ 异常: {e}")

        time.sleep(1)  # 避免Jina Reader限流

    return parsed


def process_opportunities(parsed_policies: list, profile) -> list:
    """处理政策机会"""
    matcher = PolicyMatcher(profile)
    scorer = PolicyScorer()
    risk_filter = PolicyRiskFilter()

    opportunities = []

    for p in parsed_policies:
        policy_dict = p.to_dict()

        # 匹配
        match_result = matcher.match(policy_dict)

        # 评分
        score_result = scorer.score(
            policy_dict,
            match_result.total_score,
            match_result.matched_tags,
            match_result.missing_tags
        )

        # 风险
        risk_result = risk_filter.filter(policy_dict, profile.__dict__)

        # 申报建议
        project_name = _get_project_name(policy_dict, profile)
        keywords = _get_keywords(policy_dict)

        opp = {
            "id": p.id,
            "title": p.title,
            "url": p.url,
            "source": p.source,
            "source_level": p.source_level,
            "published_at": p.published_at,
            "deadline": p.parsed.申报截止时间 or "",
            "days_left": _calc_days_left(p.parsed.申报截止时间),
            "parsed": policy_dict,
            "match_score": match_result.total_score,
            "matched_tags": match_result.matched_tags,
            "missing_tags": match_result.missing_tags,
            "score": score_result.final,
            "level": score_result.level,
            "priority": score_result.priority,
            "dimensions": score_result.dimensions,
            "is_pre_subsidy": score_result.is_pre_subsidy,
            "risk_level": risk_result.risk_level,
            "risk_score": risk_result.risk_score,
            "risk_advice": risk_result.advice,
            "is_worth_applying": risk_result.is_worth_applying and score_result.final >= 40,
            "roi": score_result.roi,
            "recommended_project": project_name,
            "packaging_keywords": keywords,
            "reasons": score_result.reasons,
            "warnings": [r["risk_point"] for r in risk_result.detailed_risks]
        }
        opportunities.append(opp)

    # 过滤+排序
    opportunities = [o for o in opportunities if o["is_worth_applying"]]
    opportunities.sort(key=lambda x: (x["score"], x["match_score"]), reverse=True)

    return opportunities


def _calc_days_left(deadline_str: str) -> int:
    """计算剩余天数"""
    if not deadline_str:
        return 0
    try:
        deadline = datetime.fromisoformat(deadline_str.replace("Z", "+00:00"))
        return (deadline.replace(tzinfo=None) - datetime.now()).days
    except Exception:
        return 0


def _get_project_name(policy: dict, profile) -> str:
    """获取建议项目名"""
    directions = policy.get("支持方向", [])
    keywords = policy.get("政策原文关键词", [])
    all_text = " ".join(directions + keywords)

    for project in profile.key_projects:
        for kw in project.get("keywords", []):
            if kw in all_text:
                return project["name"]

    return f"{directions[0]}示范项目" if directions else "智慧物流建设项目"


def _get_keywords(policy: dict) -> list:
    """获取包装关键词"""
    keywords = list(policy.get("支持方向", []))
    for kw in ["新质生产力", "补链强链", "数字化转型", "智慧物流"]:
        if kw not in keywords:
            keywords.append(kw)
    return keywords[:8]


def save_output(opportunities: list):
    """保存最终输出"""
    output = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "gov-fetch + llm-parse",
        "total": len(opportunities),
        "high_priority": len([o for o in opportunities if o["priority"] in ["P0", "P1"]]),
        "by_level": {
            "S": len([o for o in opportunities if o["level"] == "S"]),
            "A": len([o for o in opportunities if o["level"] == "A"]),
            "B": len([o for o in opportunities if o["level"] == "B"]),
            "C": len([o for o in opportunities if o["level"] == "C"]),
        },
        "opportunities": opportunities
    }

    OUTPUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n保存到: {OUTPUT_FILE}")


def main():
    parser = argparse.ArgumentParser(description="政府政策抓取+LLM解析管道")
    parser.add_argument("--limit", "-n", type=int, default=10, help="LLM解析数量限制")
    parser.add_argument("--skip-parse", action="store_true", help="跳过LLM解析（仅抓取）")

    args = parser.parse_args()

    print("=" * 60)
    print("政府政策抓取 + LLM解析管道")
    print("=" * 60)

    # 1. 抓取
    print("\n[1/3] 抓取政府网站...")
    items = fetch_gov()

    if not items:
        print("抓取失败，退出")
        return

    # 2. LLM解析（可选）
    if args.skip_parse:
        print("\n[2/3] 跳过LLM解析")
        print("\n⚠️ 警告: 无LLM解析，评分将不准确")
        parsed = []
    else:
        print(f"\n[2/3] LLM解析 (限制 {args.limit} 条)...")
        parsed = parse_with_llm(items, args.limit)

    # 3. 处理机会
    print("\n[3/3] 处理政策机会...")

    if parsed:
        profile = load_enterprise_profile("ztj")
        opportunities = process_opportunities(parsed, profile)
    else:
        # 无LLM解析，使用简化处理
        print("使用简化处理（无完整政策数据）")
        opportunities = _simple_process(items)

    if opportunities:
        save_output(opportunities)
        print(f"\n✅ 生成 {len(opportunities)} 条政策机会")
    else:
        print("\n⚠️ 未生成有效机会")


def _simple_process(items: list) -> list:
    """简化处理（无LLM解析时）"""
    profile = load_enterprise_profile("ztj")
    matcher = PolicyMatcher(profile)
    scorer = PolicyScorer()

    opportunities = []

    for item in items:
        # 构建简化政策
        policy = {
            "id": f"gov_{hash(item['url']) % 100000:05d}",
            "title": item["title"],
            "url": item["url"],
            "source": item.get("source", ""),
            "source_level": "国家级",
            "支持方向": _extract_directions(item["title"]),
            "政策原文关键词": [],
            "申报条件": {},
            "支持金额": {},
            "地区": ["上海"] if "上海" in item["title"] else ["全国"],
            "级别": "国家级"
        }

        match_result = matcher.match(policy)
        score_result = scorer.score(policy, match_result.total_score * 0.7, [], [])

        opp = {
            "id": policy["id"],
            "title": policy["title"],
            "url": policy["url"],
            "source": policy["source"],
            "source_level": policy["source_level"],
            "published_at": "",
            "deadline": "",
            "days_left": 0,
            "parsed": policy,
            "match_score": match_result.total_score,
            "matched_tags": match_result.matched_tags,
            "missing_tags": match_result.missing_tags,
            "score": score_result.final,
            "level": score_result.level,
            "priority": score_result.priority,
            "dimensions": score_result.dimensions,
            "is_pre_subsidy": score_result.is_pre_subsidy,
            "risk_level": "低",
            "risk_score": 0,
            "risk_advice": "需LLM解析获取完整信息",
            "is_worth_applying": score_result.final >= 40,
            "roi": {"subsidy": 0, "roi_label": "?"},
            "recommended_project": _get_project_name(policy, profile),
            "packaging_keywords": _get_keywords(policy),
            "reasons": [],
            "warnings": ["⚠️ 数据不完整，需补充"]
        }
        opportunities.append(opp)

    opportunities = [o for o in opportunities if o["is_worth_applying"]]
    opportunities.sort(key=lambda x: (x["score"], x["match_score"]), reverse=True)
    return opportunities


def _extract_directions(title: str) -> list:
    """从标题提取方向"""
    directions = []
    if any(kw in title for kw in ["物流", "运输", "配送"]):
        directions.append("智慧物流")
    if any(kw in title for kw in ["低空", "无人机", "航空"]):
        directions.append("低空经济")
    if any(kw in title for kw in ["人工智能", "AI", "数字化", "智能"]):
        directions.append("数字化转型")
    if any(kw in title for kw in ["招标", "采购"]):
        directions.append("政府采购")
    return directions


if __name__ == "__main__":
    main()
