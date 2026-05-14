#!/usr/bin/env python3
"""
政策企业匹配器 (Policy Matcher)

功能:
1. 加载企业画像
2. 计算政策与企业匹配度
3. 输出匹配结果

用法:
    python scripts/match_policy.py --policy-id xxxx
    python scripts/match_policy.py --batch
    python scripts/match_policy.py --list
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 路径配置
DATA_DIR = Path(__file__).parent.parent / "data"
POLICIES_DIR = DATA_DIR / "policies"
ENTERPRISE_DIR = DATA_DIR / "enterprise"
MATCH_HISTORY_FILE = ENTERPRISE_DIR / "match_history.json"

UTC = timezone.utc


@dataclass
class EnterpriseProfile:
    """企业画像"""
    name: str
    short_name: str
    industry: list[str]
    tech_stack: list[str]
    region: list[str]
    business: list[str]
    certifications: dict
    scale: dict
    key_projects: list[dict]
    ai_keywords: dict

    @classmethod
    def from_yaml(cls, data: dict) -> "EnterpriseProfile":
        return cls(
            name=data.get("name", ""),
            short_name=data.get("short_name", ""),
            industry=data.get("industry", []),
            tech_stack=data.get("tech_stack", []),
            region=data.get("region", []),
            business=data.get("business", []),
            certifications=data.get("certifications", {}),
            scale=data.get("scale", {}),
            key_projects=data.get("key_projects", []),
            ai_keywords=data.get("ai_keywords", {})
        )


@dataclass
class MatchResult:
    """匹配结果"""
    policy_id: str
    title: str
    total_score: float  # 0-1
    matched_tags: list[str]
    missing_tags: list[str]
    cert_match: dict
    industry_match: float
    region_match: float
    tech_match: float
    recommendation: str

    def to_dict(self) -> dict:
        return asdict(self)


class PolicyMatcher:
    """政策匹配器"""

    def __init__(self, profile: EnterpriseProfile):
        self.profile = profile
        self.all_keywords = set(
            self.profile.industry +
            self.profile.tech_stack +
            self.profile.business
        )

    def match(self, policy: dict) -> MatchResult:
        """计算政策与企业的匹配度"""

        matched_tags = []
        missing_tags = []
        scores = {}

        # 1. 行业匹配 (40%)
        industry_score = self._match_lists(
            policy.get("支持方向", []) + policy.get("政策原文关键词", []),
            self.profile.industry + self.profile.tech_stack + self.profile.business,
            matched_tags
        )
        scores["industry"] = industry_score * 0.40

        # 2. 地域匹配 (30%)
        region_score = self._match_region(policy.get("地区", []))
        scores["region"] = region_score * 0.30

        # 3. 资质匹配 (20%)
        cert_result = self._check_certs(policy)
        scores["cert"] = cert_result["score"] * 0.20
        matched_tags.extend(cert_result["matched"])
        missing_tags.extend(cert_result["missing"])

        # 4. 技术方向匹配 (10%)
        tech_score = self._match_lists(
            policy.get("支持方向", []),
            self.profile.tech_stack,
            matched_tags
        )
        scores["tech"] = tech_score * 0.10

        # 总分
        total_score = sum(scores.values())

        # 推荐建议
        recommendation = self._get_recommendation(total_score, missing_tags)

        return MatchResult(
            policy_id=policy.get("id", ""),
            title=policy.get("title", ""),
            total_score=round(total_score, 3),
            matched_tags=list(set(matched_tags)),
            missing_tags=list(set(missing_tags)),
            cert_match=cert_result,
            industry_match=round(scores["industry"] / 0.40, 3) if scores["industry"] > 0 else 0,
            region_match=region_score,
            tech_match=tech_score,
            recommendation=recommendation
        )

    def _match_lists(self, policy_items: list, enterprise_items: list,
                     matched_tags: list) -> float:
        """列表匹配"""
        if not policy_items:
            return 0.5

        policy_set = set(policy_items)
        enterprise_set = set(enterprise_items)

        matched = policy_set & enterprise_set
        matched_tags.extend(list(matched))

        return len(matched) / len(policy_set)

    def _match_region(self, policy_regions: list) -> float:
        """地域匹配"""
        if not policy_regions:
            return 0.3  # 无地域信息给低分

        enterprise_regions = set(self.profile.region)

        # 完全匹配
        if any(r in enterprise_regions for r in policy_regions):
            # 青浦/上海优先
            if any(r in ["上海", "青浦"] for r in policy_regions):
                return 1.0
            return 0.8

        # 国家级政策
        if "全国" in policy_regions or "国家级" in policy_regions:
            return 0.6

        # 长三角
        if any(r in ["长三角", "江苏", "浙江"] for r in policy_regions):
            return 0.5

        return 0.3

    def _check_certs(self, policy: dict) -> dict:
        """检查资质匹配"""
        required = policy.get("申报条件", {}).get("必要资质", [])
        owned = set(self.profile.certifications.get("owned", []))
        target = set(self.profile.certifications.get("target", []))

        if not required:
            return {"score": 1.0, "matched": [], "missing": [], "has_gap": False}

        required_set = set(required)
        matched = list(required_set & owned)
        missing = list(required_set - owned)
        has_target = bool(required_set & target)

        # 有缺失但有目标资质，降低惩罚
        if missing and has_target:
            score = len(matched) / len(required) * 0.7  # 最多70%
        else:
            score = len(matched) / len(required) if required else 1.0

        return {
            "score": score,
            "matched": matched,
            "missing": missing,
            "has_gap": bool(missing)
        }

    def _get_recommendation(self, score: float, missing_tags: list) -> str:
        """获取推荐建议"""
        if score >= 0.8:
            if missing_tags:
                return f"强烈推荐（需补充资质: {', '.join(missing_tags)}）"
            return "强烈推荐"
        elif score >= 0.6:
            if missing_tags:
                return f"建议申报（资质差距: {', '.join(missing_tags)}）"
            return "建议申报"
        elif score >= 0.4:
            return "可选申报（匹配度一般）"
        else:
            return "暂不推荐（匹配度低）"


def load_enterprise_profile(name: str = "ztj") -> EnterpriseProfile:
    """加载企业画像"""
    profile_file = ENTERPRISE_DIR / f"{name}-profile.json"
    yaml_file = ENTERPRISE_DIR / f"{name}-profile.yaml"

    if profile_file.exists():
        data = json.loads(profile_file.read_text(encoding="utf-8"))
    elif yaml_file.exists():
        import yaml
        data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
    else:
        # 默认画像
        data = {
            "name": "上海中通吉网络技术有限公司",
            "short_name": "中通吉",
            "industry": ["物流", "快递", "供应链"],
            "tech_stack": ["AI调度", "数字孪生", "自动驾驶", "低空经济"],
            "region": ["上海", "青浦", "长三角"],
            "business": ["快递服务", "智慧物流", "末端配送", "即时配送"],
            "certifications": {
                "owned": ["高新技术企业"],
                "target": ["专精特新", "企业技术中心"]
            },
            "scale": {"employees": "10000+", "rd_ratio": ">3%"},
            "key_projects": [
                {"name": "运输调度平台", "keywords": ["现代流通体系", "AI+物流"]},
                {"name": "数字孪生", "keywords": ["数字孪生", "智慧物流"]}
            ],
            "ai_keywords": {}
        }

    return EnterpriseProfile.from_yaml(data.get("enterprise", data))


def load_policy(policy_id: str) -> Optional[dict]:
    """加载政策"""
    policy_file = POLICIES_DIR / f"{policy_id}.json"
    if not policy_file.exists():
        return None
    return json.loads(policy_file.read_text(encoding="utf-8"))


def load_all_policies() -> list[dict]:
    """加载所有政策"""
    if not POLICIES_DIR.exists():
        return []
    return [
        json.loads(f.read_text(encoding="utf-8"))
        for f in POLICIES_DIR.glob("*.json")
    ]


def match_policy(policy_id: str, profile: EnterpriseProfile = None) -> MatchResult:
    """匹配单个政策"""
    if profile is None:
        profile = load_enterprise_profile()

    policy = load_policy(policy_id)
    if not policy:
        print(f"政策不存在: {policy_id}")
        return None

    matcher = PolicyMatcher(profile)
    result = matcher.match(policy)

    return result


def batch_match(window_hours: int = None, min_score: float = 0.3) -> list:
    """批量匹配"""
    profile = load_enterprise_profile()
    matcher = PolicyMatcher(profile)

    policies = load_all_policies()

    results = []
    for p in policies:
        result = matcher.match(p)
        if result.total_score >= min_score:
            results.append({
                **result.to_dict(),
                "title": p.get("title", ""),
                "级别": p.get("级别", ""),
                "地区": p.get("地区", []),
                "支持方向": p.get("支持方向", []),
                "申报截止时间": p.get("申报截止时间")
            })

    return sorted(results, key=lambda x: x["total_score"], reverse=True)


def print_match_result(result: MatchResult, policy: dict = None):
    """打印匹配结果"""
    print("\n" + "=" * 60)
    print(f"政策: {result.title}")
    print("=" * 60)

    print(f"\n📊 匹配度: {result.total_score:.1%}")
    print(f"💡 建议: {result.recommendation}")

    if result.matched_tags:
        print(f"\n✅ 命中标签: {', '.join(result.matched_tags)}")

    if result.missing_tags:
        print(f"\n⚠️ 缺失条件: {', '.join(result.missing_tags)}")

    if policy:
        print(f"\n📍 地区: {', '.join(policy.get('地区', ['未知']))}")
        print(f"🏛 级别: {policy.get('级别', '未知')}")
        if policy.get('支持方向'):
            print(f"🎯 支持方向: {', '.join(policy.get('支持方向', [])[:5])}")


def save_match_history(results: list):
    """保存匹配历史"""
    ENTERPRISE_DIR.mkdir(parents=True, exist_ok=True)

    history = {
        "last_updated": datetime.now(UTC).isoformat(),
        "total_policies": len(results),
        "high_match": len([r for r in results if r["total_score"] >= 0.6]),
        "results": results[:50]  # 只保存最近50条
    }

    MATCH_HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="政策企业匹配器")
    parser.add_argument("--policy-id", help="政策ID")
    parser.add_argument("--batch", action="store_true", help="批量匹配")
    parser.add_argument("--list", action="store_true", help="列出所有政策")
    parser.add_argument("--min-score", type=float, default=0.3, help="最低匹配度")
    parser.add_argument("--profile", default="ztj", help="企业画像名称")

    args = parser.parse_args()

    if args.list:
        policies = load_all_policies()
        print(f"\n[政策库] 共 {len(policies)} 条政策")
        print("-" * 60)
        for p in sorted(policies, key=lambda x: x.get("parsed_at", ""), reverse=True)[:20]:
            print(f"  {p.get('id', 'N/A'):<16} | {p.get('级别', ''):<6} | {p.get('title', '')[:50]}")
        return

    if args.policy_id:
        result = match_policy(args.policy_id)
        if result:
            policy = load_policy(args.policy_id)
            print_match_result(result, policy)
    elif args.batch:
        print("[批量匹配]")
        results = batch_match(min_score=args.min_score)
        print(f"共 {len(results)} 条政策匹配度 >= {args.min_score:.0%}")
        print("-" * 60)

        for r in results[:20]:
            print(f"{r['total_score']:.1%} | {r['级别']:<6} | {r['title'][:45]}")
            if r['missing_tags']:
                print(f"         ⚠️ {', '.join(r['missing_tags'])}")

        save_match_history(results)
        print(f"\n已保存匹配历史到: {MATCH_HISTORY_FILE}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
