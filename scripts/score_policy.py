#!/usr/bin/env python3
"""
政策评分器 (Policy Scorer)

功能:
1. 多维度政策评分
2. 计算ROI
3. 生成申报建议

用法:
    python scripts/score_policy.py --policy-id xxxx
    python scripts/score_policy.py --batch
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Optional

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 路径配置
DATA_DIR = Path(__file__).parent.parent / "data"
POLICIES_DIR = DATA_DIR / "policies"
ENTERPRISE_DIR = DATA_DIR / "enterprise"
SCORE_HISTORY_FILE = ENTERPRISE_DIR / "score_history.json"

UTC = timezone.utc


@dataclass
class ScoreResult:
    """评分结果"""
    policy_id: str
    title: str
    final: float  # 0-100
    level: str  # S/A/B/C
    priority: str  # P0/P1/P2/P3
    dimensions: dict
    is_pre_subsidy: bool
    roi: dict
    reasons: list[str]
    warnings: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


class PolicyScorer:
    """政策评分器"""

    # 评分权重
    WEIGHTS = {
        "amount": 0.20,
        "difficulty": 0.15,
        "hit_rate": 0.25,
        "region": 0.15,
        "industry": 0.15,
        "urgency": 0.10
    }

    # 基准金额
    AMOUNT_BASELINE = 100  # 万

    def score(self, policy: dict, match_score: float = 0.5,
              matched_tags: list = None, missing_tags: list = None) -> ScoreResult:
        """计算综合评分"""

        matched_tags = matched_tags or []
        missing_tags = missing_tags or []

        dimensions = {
            "amount": self._score_amount(policy),
            "difficulty": self._score_difficulty(policy, missing_tags),
            "hit_rate": match_score,
            "region": self._score_region(policy),
            "industry": self._score_industry(policy),
            "urgency": self._score_urgency(policy)
        }

        # 加权求和
        final = sum(dimensions[k] * self.WEIGHTS[k] for k in self.WEIGHTS) * 100

        # 等级
        level = self._get_level(final)

        # 优先级
        priority = self._get_priority(final, dimensions["urgency"], missing_tags)

        # 是否前补贴
        is_pre_subsidy = not policy.get("是否后补贴", False)

        # ROI估算
        roi = self._estimate_roi(policy, match_score, missing_tags)

        # 原因
        reasons, warnings = self._get_reasons(policy, dimensions, match_score,
                                              matched_tags, missing_tags)

        return ScoreResult(
            policy_id=policy.get("id", ""),
            title=policy.get("title", ""),
            final=round(final, 1),
            level=level,
            priority=priority,
            dimensions={k: round(v * 100, 1) for k, v in dimensions.items()},
            is_pre_subsidy=is_pre_subsidy,
            roi=roi,
            reasons=reasons,
            warnings=warnings
        )

    def _score_amount(self, policy: dict) -> float:
        """金额规模评分"""
        amount_info = policy.get("支持金额", {})
        amount = amount_info.get("金额", 0) if amount_info else 0

        if not amount:
            return 0.5

        score = min(amount / self.AMOUNT_BASELINE, 1.0)
        return score

    def _score_difficulty(self, policy: dict, missing_tags: list) -> float:
        """申报难度评分 (越容易分越高)"""
        conditions = policy.get("申报条件", {})

        difficulty = 0

        # 必要资质越多越难
        certs = conditions.get("必要资质") or []
        difficulty += len(certs) * 0.15

        # 有缺失资质
        difficulty += len(missing_tags) * 0.2

        # 有投资要求
        if conditions.get("投资要求"):
            difficulty += 0.15

        # 有规模要求
        if conditions.get("规模要求"):
            difficulty += 0.1

        # 有验收要求
        if policy.get("验收要求"):
            difficulty += 0.2

        # 有垫资风险(后补贴)
        if policy.get("是否后补贴", False):
            difficulty += 0.1

        return max(0.0, 1.0 - difficulty)

    def _score_urgency(self, policy: dict) -> float:
        """时间紧迫度评分"""
        deadline_str = policy.get("申报截止时间")
        if not deadline_str:
            return 0.5

        try:
            if isinstance(deadline_str, str):
                deadline = datetime.fromisoformat(deadline_str.replace("Z", "+00:00"))
            else:
                deadline = deadline_str

            days_left = (deadline - datetime.now(UTC)).days
        except Exception:
            return 0.5

        if days_left < 0:
            return 0.0
        elif days_left <= 7:
            return 1.0
        elif days_left <= 14:
            return 0.8
        elif days_left <= 30:
            return 0.6
        elif days_left <= 60:
            return 0.4
        else:
            return 0.2

    def _score_region(self, policy: dict) -> float:
        """地域匹配评分"""
        regions = policy.get("地区", [])

        if any(r in ["上海", "青浦"] for r in regions):
            return 1.0
        elif any(r in ["长三角", "江苏", "浙江"] for r in regions):
            return 0.7
        elif "全国" in regions or "国家级" in regions:
            return 0.5
        else:
            return 0.3

    def _score_industry(self, policy: dict) -> float:
        """行业匹配评分"""
        directions = policy.get("支持方向", [])
        keywords = policy.get("政策原文关键词", [])

        enterprise_keywords = [
            "物流", "快递", "供应链", "AI调度", "数字孪生",
            "低空经济", "自动驾驶", "智慧物流", "新质生产力"
        ]

        all_text = " ".join(directions + keywords)
        matched = sum(1 for kw in enterprise_keywords if kw in all_text)

        if not directions and not keywords:
            return 0.5

        return min(matched / 3.0, 1.0)  # 最多匹配3个关键词

    def _get_level(self, score: float) -> str:
        """获取等级"""
        if score >= 85:
            return "S"
        elif score >= 70:
            return "A"
        elif score >= 50:
            return "B"
        else:
            return "C"

    def _get_priority(self, score: float, urgency: float, missing_tags: list) -> str:
        """获取优先级"""
        # 有重大资质缺失直接降级
        if missing_tags and any(c in missing_tags for c in ["高新技术企业", "专精特新"]):
            if score >= 70:
                return "P1"  # 降级
            elif score >= 50:
                return "P2"

        if score >= 85 and urgency >= 0.6:
            return "P0"
        elif score >= 70 and urgency >= 0.4:
            return "P1"
        elif score >= 50:
            return "P2"
        else:
            return "P3"

    def _estimate_roi(self, policy: dict, match_score: float,
                      missing_tags: list) -> dict:
        """估算ROI"""
        amount_info = policy.get("支持金额") or {}
        subsidy = amount_info.get("金额") or 0
        if subsidy is None:
            subsidy = 0
        is_pre = not policy.get("是否后补贴", False)

        # 估算成本
        labor_cost = 2 * 2 * 0.5  # 2人 * 2周 * 0.5万/周
        material_cost = 0.3

        # 垫资(后补贴)
        advance_fund = subsidy * 0.3 if not is_pre else 0

        # 陪跑风险
        risk_factor = 0.2 if missing_tags else 0.05

        # 匹配度影响
        risk_factor += (1 - match_score) * 0.2

        # 预期收益
        expected_subsidy = subsidy * (1 - risk_factor)
        total_cost = labor_cost + material_cost + advance_fund

        roi = (expected_subsidy - total_cost) / total_cost if total_cost > 0 else 0

        return {
            "subsidy": subsidy,
            "labor_cost": labor_cost,
            "material_cost": material_cost,
            "advance_fund": round(advance_fund, 1),
            "risk_factor": round(risk_factor, 2),
            "expected_net": round(expected_subsidy - total_cost, 1),
            "roi": round(roi, 2),
            "roi_label": "高" if roi > 2 else "中" if roi > 1 else "低"
        }

    def _get_reasons(self, policy: dict, dimensions: dict, match_score: float,
                     matched_tags: list, missing_tags: list) -> tuple:
        """获取评分原因"""
        reasons = []
        warnings = []

        # 正面原因
        if dimensions["amount"] >= 0.8:
            reasons.append(f"💰 支持金额较高 ({dimensions['amount']:.0%})")
        if match_score >= 0.8:
            reasons.append(f"🎯 企业匹配度高 ({match_score:.0%})")
        if dimensions["region"] >= 0.9:
            reasons.append("📍 地域完全匹配")
        if policy.get("支持方向"):
            dirs = policy.get("支持方向", [])[:2]
            reasons.append(f"🎯 支持方向: {', '.join(dirs)}")

        # 负面原因
        if dimensions["difficulty"] < 0.5:
            warnings.append("⚠️ 申报难度较高")
        if missing_tags:
            warnings.append(f"⚠️ 资质缺口: {', '.join(missing_tags)}")
        if dimensions["urgency"] >= 0.8:
            warnings.append("⏰ 时间紧迫，抓紧申报")
        if policy.get("是否后补贴"):
            warnings.append("💸 后补贴，需准备垫资")
        if policy.get("验收要求"):
            warnings.append("📋 有验收要求")

        return reasons, warnings


def load_policy(policy_id: str) -> Optional[dict]:
    """加载政策"""
    policy_file = POLICIES_DIR / f"{policy_id}.json"
    if not policy_file.exists():
        return None
    return json.loads(policy_file.read_text(encoding="utf-8"))


def score_policy(policy_id: str) -> Optional[ScoreResult]:
    """评分单个政策"""
    policy = load_policy(policy_id)
    if not policy:
        print(f"政策不存在: {policy_id}")
        return None

    scorer = PolicyScorer()

    # 从政策中提取匹配信息
    # 注意: 这里复用之前匹配的结果，如果有的话
    match_score = 0.5
    matched_tags = []
    missing_tags = []

    # 尝试从企业匹配历史获取
    match_history_file = ENTERPRISE_DIR / "match_history.json"
    if match_history_file.exists():
        history = json.loads(match_history_file.read_text(encoding="utf-8"))
        for r in history.get("results", []):
            if r.get("policy_id") == policy_id:
                match_score = r.get("total_score", 0.5)
                matched_tags = r.get("matched_tags", [])
                missing_tags = r.get("missing_tags", [])
                break

    result = scorer.score(policy, match_score, matched_tags, missing_tags)
    return result


def batch_score(min_level: str = "C") -> list:
    """批量评分"""
    scorer = PolicyScorer()

    # 加载所有政策
    if not POLICIES_DIR.exists():
        return []

    policies = []
    for f in POLICIES_DIR.glob("*.json"):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
            policies.append(p)
        except Exception:
            continue

    # 加载匹配历史
    match_history = {}
    match_history_file = ENTERPRISE_DIR / "match_history.json"
    if match_history_file.exists():
        history = json.loads(match_history_file.read_text(encoding="utf-8"))
        for r in history.get("results", []):
            match_history[r["policy_id"]] = r

    results = []
    level_filter = {"S": 85, "A": 70, "B": 50, "C": 0}

    for p in policies:
        match_info = match_history.get(p.get("id", ""), {})
        result = scorer.score(
            p,
            match_info.get("total_score", 0.5),
            match_info.get("matched_tags", []),
            match_info.get("missing_tags", [])
        )

        # 等级过滤
        if result.final >= level_filter.get(min_level, 0):
            results.append({
                **result.to_dict(),
                "title": p.get("title", ""),
                "级别": p.get("级别", ""),
                "地区": p.get("地区", []),
                "deadline": p.get("申报截止时间")
            })

    return sorted(results, key=lambda x: x["final"], reverse=True)


def print_score_result(result: ScoreResult, policy: dict = None):
    """打印评分结果"""
    level_emoji = {"S": "🔥", "A": "⭐", "B": "📋", "C": "📁"}
    level_color = {"S": "红色", "A": "黄色", "B": "蓝色", "C": "灰色"}

    print("\n" + "=" * 60)
    print(f"政策: {result.title}")
    print("=" * 60)

    print(f"\n{level_emoji.get(result.level, '📁')} 等级: {result.level}级 | "
          f"💯 评分: {result.final}分 | "
          f"🏷 优先级: {result.priority}")

    print(f"\n💰 预估支持: {result.roi['subsidy']}万")
    print(f"📈 ROI: {result.roi['roi_label']} ({result.roi['roi']:.1f}x)")
    if result.roi['advance_fund'] > 0:
        print(f"⚠️ 需垫资: {result.roi['advance_fund']}万")

    print(f"\n📊 维度得分:")
    dim_names = {
        "amount": "金额",
        "difficulty": "难度",
        "hit_rate": "命中",
        "region": "地域",
        "industry": "行业",
        "urgency": "紧迫"
    }
    for k, v in result.dimensions.items():
        bar = "█" * int(v / 10) + "░" * (10 - int(v / 10))
        print(f"   {dim_names.get(k, k):<6}: {v:>5.1f}/100 {bar}")

    if result.reasons:
        print(f"\n{chr(10).join(result.reasons)}")
    if result.warnings:
        print(f"\n{chr(10).join(result.warnings)}")


def save_score_history(results: list):
    """保存评分历史"""
    ENTERPRISE_DIR.mkdir(parents=True, exist_ok=True)

    history = {
        "last_updated": datetime.now(UTC).isoformat(),
        "total": len(results),
        "by_level": {
            "S": len([r for r in results if r["level"] == "S"]),
            "A": len([r for r in results if r["level"] == "A"]),
            "B": len([r for r in results if r["level"] == "B"]),
            "C": len([r for r in results if r["level"] == "C"])
        },
        "results": results[:50]
    }

    SCORE_HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="政策评分器")
    parser.add_argument("--policy-id", help="政策ID")
    parser.add_argument("--batch", action="store_true", help="批量评分")
    parser.add_argument("--min-level", default="C", choices=["S", "A", "B", "C"],
                        help="最低显示等级")

    args = parser.parse_args()

    if args.policy_id:
        result = score_policy(args.policy_id)
        if result:
            policy = load_policy(args.policy_id)
            print_score_result(result, policy)
    elif args.batch:
        print("[批量评分]")
        results = batch_score(min_level=args.min_level)
        print(f"共 {len(results)} 条政策等级 >= {args.min_level}级")
        print("-" * 60)

        level_emoji = {"S": "🔥", "A": "⭐", "B": "📋", "C": "📁"}
        for r in results[:20]:
            emoji = level_emoji.get(r["level"], "📁")
            deadline = r.get("deadline", "无截止")
            print(f"{emoji}{r['level']} {r['final']:>5.1f}分 | "
                  f"{r.get('级别', ''):<6} | {r['title'][:40]}")
            if deadline and deadline != "无截止":
                print(f"         ⏰ {deadline}")

        save_score_history(results)
        print(f"\n已保存评分历史到: {SCORE_HISTORY_FILE}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
