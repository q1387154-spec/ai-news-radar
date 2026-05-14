#!/usr/bin/env python3
"""
从政府抓取数据生成政策机会

用法:
    python scripts/process_gov.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.match_policy import PolicyMatcher, load_enterprise_profile
from scripts.score_policy import PolicyScorer
from scripts.risk_filter import PolicyRiskFilter

UTC = timezone.utc
DATA_DIR = Path(__file__).parent.parent / "data"
FETCHED_FILE = DATA_DIR / "gov-fetched.json"
OUTPUT_FILE = DATA_DIR / "policy-opportunities.json"


def _generate_project_name(policy: dict, profile) -> str:
    """生成建议项目名称"""
    directions = policy.get("支持方向", [])
    keywords = policy.get("政策原文关键词", [])
    all_text = " ".join(directions + keywords)

    for project in profile.key_projects:
        proj_kws = project.get("keywords", [])
        for kw in proj_kws:
            if kw in all_text:
                return project["name"]

    if directions:
        return f"{directions[0]}示范项目"
    return "智慧物流建设项目"


def _generate_packaging_keywords(policy: dict, profile) -> list:
    """生成包装关键词"""
    keywords = list(policy.get("支持方向", []))
    hot = ["新质生产力", "补链强链", "数字化转型", "智慧物流"]
    for kw in hot:
        if kw not in keywords:
            keywords.append(kw)
    return keywords[:8]


def process_gov_policies():
    """处理政府抓取的政策"""
    print("=" * 60)
    print("处理政府抓取政策")
    print("=" * 60)

    # 加载数据
    if not FETCHED_FILE.exists():
        print(f"文件不存在: {FETCHED_FILE}")
        print("请先运行: python scripts/fetch_gov_policies.py --all")
        return

    data = json.loads(FETCHED_FILE.read_text(encoding="utf-8"))
    items = data.get("items", [])
    print(f"\n加载 {len(items)} 条政策")

    if not items:
        return

    # 加载企业画像
    print("\n加载企业画像...")
    profile = load_enterprise_profile("ztj")

    # 初始化
    matcher = PolicyMatcher(profile)
    scorer = PolicyScorer()
    risk_filter = PolicyRiskFilter()

    opportunities = []

    # 处理每条政策
    # 注意：这里我们没有完整的parsed数据，需要基于标题/URL做简单匹配
    for item in items:
        title = item.get("title", "")
        url = item.get("url", "")
        source = item.get("source", "")

        print(f"\n处理: {title[:40]}...")

        # 构建简化政策对象（用于匹配）
        # 由于没有全文，我们用标题关键词做粗匹配
        policy = {
            "id": f"gov_{hash(title) % 100000:05d}",
            "title": title,
            "url": url,
            "source": source,
            "source_level": "国家级" if "国家" in source else "市级",
            # 这些字段需要LLM解析，但这里我们从标题推断
            "支持方向": _extract_directions(title),
            "政策原文关键词": [],
            "申报条件": {},
            "支持金额": {},
            "地区": ["上海"] if "上海" in title else ["全国"],
            "级别": "国家级" if "国家" in source else "市级",
        }

        # 匹配
        match_result = matcher.match(policy)
        print(f"    匹配度: {match_result.total_score:.0%}")

        # 评分（降低期望因为数据不完整）
        score_result = scorer.score(
            policy,
            match_result.total_score * 0.8,  # 数据不完整，降低权重
            match_result.matched_tags,
            match_result.missing_tags
        )
        print(f"    评分: {score_result.final:.1f}分 ({score_result.level}级)")

        # 风险评估
        risk_result = risk_filter.filter(policy, profile.__dict__)

        # 生成申报建议
        project_name = _generate_project_name(policy, profile)
        keywords = _generate_packaging_keywords(policy, profile)

        opp = {
            "id": policy["id"],
            "title": title,
            "url": url,
            "source": source,
            "source_level": policy["source_level"],
            "published_at": data.get("fetched_at", ""),
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
            "risk_level": risk_result.risk_level,
            "risk_score": risk_result.risk_score,
            "risk_advice": risk_result.advice,
            "is_worth_applying": risk_result.is_worth_applying and score_result.final >= 40,
            "roi": score_result.roi,
            "recommended_project": project_name,
            "packaging_keywords": keywords,
            "reasons": score_result.reasons,
            "warnings": risk_result.detailed_risks
        }
        opportunities.append(opp)

    # 过滤+排序
    opportunities = [o for o in opportunities if o["is_worth_applying"]]
    opportunities.sort(key=lambda x: (x["score"], x["match_score"]), reverse=True)

    # 保存
    output = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "gov-fetched",
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

    # 摘要
    print("\n" + "=" * 60)
    print(f"政策机会摘要: {len(opportunities)} 条")
    print("=" * 60)

    for o in opportunities[:5]:
        print(f"\n{o['level']}级 {o['score']:.1f}分 {o['priority']}")
        print(f"  {o['title'][:60]}")
        if o['matched_tags']:
            print(f"  命中: {', '.join(o['matched_tags'][:3])}")


def _extract_directions(title: str) -> list:
    """从标题提取支持方向（简单规则）"""
    directions = []

    # 物流相关
    if any(kw in title for kw in ["物流", "运输", "配送", "快递"]):
        directions.append("智慧物流")

    # AI相关
    if any(kw in title for kw in ["人工智能", "AI", "数字化", "智能"]):
        directions.append("数字化转型")

    # 低空经济
    if any(kw in title for kw in ["低空", "无人机", "航空"]):
        directions.append("低空经济")

    # 儿童友好（不相关）
    if any(kw in title for kw in ["儿童"]):
        directions.append("社会建设")

    return directions


if __name__ == "__main__":
    process_gov_policies()
