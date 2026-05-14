#!/usr/bin/env python3
"""
演示模式: 使用模拟数据运行完整管道

用法:
    python scripts/run_demo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.match_policy import PolicyMatcher, load_enterprise_profile
from scripts.score_policy import PolicyScorer
from scripts.risk_filter import PolicyRiskFilter
from datetime import datetime, timezone, timedelta

UTC = timezone.utc

DATA_DIR = Path(__file__).parent.parent / "data"
DEMO_FILE = DATA_DIR / "policies-demo.json"
OUTPUT_FILE = DATA_DIR / "policy-opportunities.json"


def run_demo():
    print("=" * 60)
    print("Policy OS 演示模式")
    print("=" * 60)

    # 加载企业画像
    print("\n[1/4] 加载企业画像...")
    profile = load_enterprise_profile("ztj")
    print(f"  ✅ 企业: {profile.name}")

    # 加载演示政策
    print("\n[2/4] 加载演示政策...")
    demo_data = json.loads(DEMO_FILE.read_text(encoding="utf-8"))
    policies = demo_data if isinstance(demo_data, list) else demo_data.get("items", [])
    print(f"  ✅ 演示政策: {len(policies)} 条")

    # 处理每条政策
    print("\n[3/4] 处理政策...")
    opportunities = []
    matcher = PolicyMatcher(profile)
    scorer = PolicyScorer()
    risk_filter = PolicyRiskFilter()

    for p in policies:
        print(f"\n  处理: {p['title'][:40]}...")

        # 扁平化政策数据 (把parsed字段提到顶层)
        policy = {
            **p.get("parsed", {}),
            **p,
            "parsed": p.get("parsed", p)
        }

        # 匹配
        match_result = matcher.match(policy)
        print(f"    匹配度: {match_result.total_score:.0%}")

        # 评分
        score_result = scorer.score(
            policy,
            match_result.total_score,
            match_result.matched_tags,
            match_result.missing_tags
        )
        print(f"    评分: {score_result.final:.1f}分 ({score_result.level}级)")

        # 风险
        risk_result = risk_filter.filter(policy, profile.__dict__)
        print(f"    风险: {risk_result.risk_level}级 ({risk_result.risk_score:.1f}/10)")

        # 生成申报建议
        project_name = _generate_project_name(policy, profile)
        keywords = _generate_packaging_keywords(policy, profile)

        # 计算剩余天数
        deadline = p.get("deadline") or policy.get("申报截止时间")
        days_left = 0
        if deadline:
            try:
                deadline_dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
                now_local = datetime.now(timezone(timedelta(hours=8)))  # 北京时间
                days_left = (deadline_dt.replace(tzinfo=None) - now_local.replace(tzinfo=None)).days
            except Exception:
                pass

        opp = {
            "id": p["id"],
            "title": p["title"],
            "url": p["url"],
            "source": p["source"],
            "source_level": p.get("source_level", ""),
            "published_at": p.get("published_at", ""),
            "deadline": deadline or "",
            "days_left": days_left,
            "parsed": p.get("parsed", p),
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
            "is_worth_applying": risk_result.is_worth_applying and score_result.final >= 50,
            "roi": score_result.roi,
            "recommended_project": project_name,
            "packaging_keywords": keywords,
            "reasons": score_result.reasons,
            "warnings": score_result.warnings
        }
        opportunities.append(opp)

    # 过滤+排序
    print("\n[4/4] 生成报告...")
    opportunities = [o for o in opportunities if o["is_worth_applying"]]
    opportunities.sort(key=lambda x: (x["score"], x["match_score"]), reverse=True)

    # 保存
    output = {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "demo",
        "total": len(opportunities),
        "high_priority": len([o for o in opportunities if o["priority"] in ["P0", "P1"]]),
        "by_level": {
            "S": len([o for o in opportunities if o["level"] == "S"]),
            "A": len([o for o in opportunities if o["level"] == "A"]),
            "B": len([o for o in opportunities if o["level"] == "B"]),
        },
        "opportunities": opportunities
    }

    OUTPUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✅ 保存到: {OUTPUT_FILE}")

    # 打印摘要
    print("\n" + "=" * 60)
    print("📊 政策机会摘要")
    print("=" * 60)

    level_emoji = {"S": "🔥", "A": "⭐", "B": "📋", "C": "📁"}
    for o in opportunities:
        emoji = level_emoji.get(o["level"], "📁")
        pre = "前补" if o["is_pre_subsidy"] else "后补"
        print(f"\n{emoji}{o['level']}级 {o['score']:.1f}分 {o['priority']} | {pre}")
        print(f"   {o['title']}")
        print(f"   💰 {o['roi'].get('subsidy', 0)}万 | 📈 ROI:{o['roi'].get('roi_label','?')} | ⏰ {o['days_left']}天")
        if o["recommended_project"]:
            print(f"   📦 项目: {o['recommended_project']}")
        if o["matched_tags"]:
            print(f"   ✅ 命中: {', '.join(o['matched_tags'][:4])}")
        if o["missing_tags"]:
            print(f"   ⚠️ 缺口: {', '.join(o['missing_tags'])}")


def _generate_project_name(policy: dict, profile) -> str:
    parsed = policy.get("parsed", policy)
    for project in profile.key_projects:
        project_keywords = project.get("keywords", [])
        directions = parsed.get("支持方向", [])
        keywords = parsed.get("政策原文关键词", [])
        all_text = " ".join(directions + keywords)
        for kw in project_keywords:
            if kw in all_text:
                return project["name"]
    directions = parsed.get("支持方向", [])
    if directions:
        return f"{directions[0]}示范项目"
    return "智慧物流建设项目"


def _generate_packaging_keywords(policy: dict, profile) -> list:
    parsed = policy.get("parsed", policy)
    keywords = list(parsed.get("支持方向", []))
    hot_keywords = ["新质生产力", "补链强链", "数字化转型", "智慧物流"]
    for kw in hot_keywords:
        if kw not in keywords:
            keywords.append(kw)
    return keywords[:8]


if __name__ == "__main__":
    run_demo()
