#!/usr/bin/env python3
"""
政策逆向过滤器 (Policy Risk Filter)

功能:
1. 识别"陷阱"政策
2. 评估陪跑风险
3. 识别验收雷区

用法:
    python scripts/risk_filter.py --policy-id xxxx
    python scripts/risk_filter.py --batch
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 路径配置
DATA_DIR = Path(__file__).parent.parent / "data"
POLICIES_DIR = DATA_DIR / "policies"
ENTERPRISE_DIR = DATA_DIR / "enterprise"
RISK_HISTORY_FILE = ENTERPRISE_DIR / "risk_history.json"

UTC = timezone.utc


@dataclass
class RiskResult:
    """风险评估结果"""
    policy_id: str
    title: str
    risk_level: str  # 高/中/低
    risk_score: float  # 0-10, 越高越危险
    detailed_risks: list[dict]
    is_worth_applying: bool
    advice: str

    def to_dict(self) -> dict:
        return asdict(self)


class PolicyRiskFilter:
    """逆向过滤器"""

    # 高危风险点
    HIGH_RISK_PATTERNS = [
        {
            "pattern": "本地注册",
            "description": "要求在本地注册法人",
            "severity": "高",
            "reason": "限制企业注册地，增加合规成本"
        },
        {
            "pattern": "税收归属",
            "description": "要求税收归本地",
            "severity": "高",
            "reason": "可能影响企业整体税负"
        },
        {
            "pattern": "采购.*本地",
            "description": "要求采购本地设备>50%",
            "severity": "高",
            "reason": "限制采购选择，可能增加成本"
        },
        {
            "pattern": "产业化.*验收",
            "description": "要求产业化验收",
            "severity": "高",
            "reason": "市场风险转嫁企业"
        },
        {
            "pattern": "配套资金.*100%",
            "description": "要求100%配套资金",
            "severity": "高",
            "reason": "资金压力大"
        }
    ]

    # 中危风险点
    MEDIUM_RISK_PATTERNS = [
        {
            "pattern": "后补贴",
            "description": "验收后才拨付资金",
            "severity": "中",
            "reason": "需要企业垫资"
        },
        {
            "pattern": "验收.*一年",
            "description": "验收周期超过1年",
            "severity": "中",
            "reason": "资金回笼慢"
        },
        {
            "pattern": "主观评价",
            "description": "验收包含主观评价",
            "severity": "中",
            "reason": "验收结果不确定"
        },
        {
            "pattern": "联合申报",
            "description": "需与国企/政府联合",
            "severity": "中",
            "reason": "依赖第三方，协调成本高"
        },
        {
            "pattern": "分批拨付",
            "description": "资金分批拨付",
            "severity": "中",
            "reason": "尾款可能难要"
        }
    ]

    # 低危特征
    LOW_RISK_FEATURES = [
        "前补贴",
        "立项即拨",
        "免验收",
        "无需产业化",
        "无需配套",
        "材料审核",
        "无需现场核查"
    ]

    def filter(self, policy: dict, enterprise: dict = None) -> RiskResult:
        """评估政策风险"""

        detailed_risks = []
        risk_score = 0.0

        # 检查高危模式
        policy_text = self._get_policy_text(policy)
        for pattern in self.HIGH_RISK_PATTERNS:
            if pattern["pattern"] in policy_text:
                detailed_risks.append({
                    "risk_point": pattern["description"],
                    "level": pattern["severity"],
                    "suggestion": pattern["reason"],
                    "matched": pattern["pattern"]
                })
                risk_score += 3.0

        # 检查中危模式
        for pattern in self.MEDIUM_RISK_PATTERNS:
            if pattern["pattern"] in policy_text:
                detailed_risks.append({
                    "risk_point": pattern["description"],
                    "level": pattern["severity"],
                    "suggestion": pattern["reason"],
                    "matched": pattern["pattern"]
                })
                risk_score += 1.5

        # 额外风险评估
        # 1. 垫资风险
        if policy.get("是否后补贴", False):
            amount = policy.get("支持金额", {}).get("金额", 0) or 0
            if amount > 100:
                risk_score += 1.0
                detailed_risks.append({
                    "risk_point": f"后补贴+大金额({amount}万)",
                    "level": "中",
                    "suggestion": "需准备大额垫资，建议提前评估现金流",
                    "matched": "后补贴+大金额"
                })

        # 2. 验收风险
        if policy.get("验收要求"):
            验收_text = str(policy.get("验收要求", ""))
            if any(kw in 验收_text for kw in ["现场", "实地", "核查"]):
                risk_score += 0.5
                detailed_risks.append({
                    "risk_point": "需现场验收",
                    "level": "低",
                    "suggestion": "提前准备现场演示和材料",
                    "matched": "现场验收"
                })

        # 3. 资质缺口风险
        required_certs = policy.get("申报条件", {}).get("必要资质") or []
        owned_certs = enterprise.get("certifications", {}).get("owned") or [] if enterprise else []
        missing = [c for c in required_certs if c not in owned_certs]
        if missing:
            risk_score += 1.0
            detailed_risks.append({
                "risk_point": f"资质缺口: {', '.join(missing)}",
                "level": "中",
                "suggestion": "需先取得相关资质，或选择其他政策",
                "matched": "资质缺失"
            })

        # 4. 时间风险
        deadline = policy.get("申报截止时间")
        if deadline:
            try:
                if isinstance(deadline, str):
                    from datetime import timedelta
                    deadline_dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
                    days_left = (deadline_dt - datetime.now(UTC)).days
                    if days_left < 14:
                        risk_score += 0.5
                        detailed_risks.append({
                            "risk_point": f"时间紧迫(仅剩{days_left}天)",
                            "level": "低",
                            "suggestion": "立即启动申报准备",
                            "matched": "时间紧迫"
                        })
            except Exception:
                pass

        # 限制最高风险分
        risk_score = min(risk_score, 10.0)

        # 判断风险等级
        if risk_score >= 7:
            risk_level = "高"
            is_worth = False
            advice = "风险过高，建议放弃或大幅降低预期"
        elif risk_score >= 4:
            risk_level = "中"
            is_worth = True
            advice = "风险可控，可申报但需充分评估和准备"
        else:
            risk_level = "低"
            is_worth = True
            advice = "风险低，建议申报"

        # 特殊加分项
        policy_text_lower = policy_text.lower()
        for feature in self.LOW_RISK_FEATURES:
            if feature.lower() in policy_text_lower:
                risk_score = max(0, risk_score - 0.5)

        return RiskResult(
            policy_id=policy.get("id", ""),
            title=policy.get("title", ""),
            risk_level=risk_level,
            risk_score=round(risk_score, 1),
            detailed_risks=detailed_risks,
            is_worth_applying=is_worth,
            advice=advice
        )

    def _get_policy_text(self, policy: dict) -> str:
        """获取政策全文文本"""
        parts = [
            policy.get("title", "") or "",
            policy.get("级别", "") or "",
            str(policy.get("支持金额", "") or ""),
            str(policy.get("申报条件", "") or ""),
            policy.get("验收要求", "") or "",
            str(policy.get("支持方向", []) or []),
            " ".join(policy.get("风险提示", []) or [])
        ]
        return " ".join(str(p) for p in parts if p)


def load_policy(policy_id: str) -> Optional[dict]:
    """加载政策"""
    policy_file = POLICIES_DIR / f"{policy_id}.json"
    if not policy_file.exists():
        return None
    return json.loads(policy_file.read_text(encoding="utf-8"))


def load_enterprise() -> dict:
    """加载企业画像"""
    profile_file = ENTERPRISE_DIR / "ztj-profile.json"
    if profile_file.exists():
        return json.loads(profile_file.read_text(encoding="utf-8"))
    return {}


def filter_policy(policy_id: str) -> Optional[RiskResult]:
    """过滤单个政策"""
    policy = load_policy(policy_id)
    if not policy:
        print(f"政策不存在: {policy_id}")
        return None

    enterprise = load_enterprise()
    risk_filter = PolicyRiskFilter()
    result = risk_filter.filter(policy, enterprise)

    return result


def batch_filter() -> list:
    """批量过滤"""
    if not POLICIES_DIR.exists():
        return []

    risk_filter = PolicyRiskFilter()
    enterprise = load_enterprise()

    results = []
    for f in POLICIES_DIR.glob("*.json"):
        try:
            policy = json.loads(f.read_text(encoding="utf-8"))
            result = risk_filter.filter(policy, enterprise)
            results.append({
                **result.to_dict(),
                "title": policy.get("title", ""),
                "级别": policy.get("级别", ""),
                "is_pre_subsidy": not policy.get("是否后补贴", False)
            })
        except Exception:
            continue

    return sorted(results, key=lambda x: x["risk_score"], reverse=True)


def print_risk_result(result: RiskResult, policy: dict = None):
    """打印风险结果"""
    level_emoji = {"高": "🔴", "中": "🟡", "低": "🟢"}
    emoji = level_emoji.get(result.risk_level, "⚪")

    print("\n" + "=" * 60)
    print(f"政策: {result.title}")
    print("=" * 60)

    print(f"\n{emoji} 风险等级: {result.risk_level}级 | "
          f"⚠️ 风险分: {result.risk_score}/10")

    print(f"\n💡 {result.advice}")

    if result.detailed_risks:
        print(f"\n📋 风险详情:")
        for risk in result.detailed_risks:
            level_icon = level_emoji.get(risk["level"], "⚪")
            print(f"  {level_icon} [{risk['level']}] {risk['risk_point']}")
            print(f"      → {risk['suggestion']}")

    # 申报建议
    print(f"\n{'✅' if result.is_worth_applying else '❌'} 申报建议: "
          f"{'值得申报' if result.is_worth_applying else '不建议申报'}")


def save_risk_history(results: list):
    """保存风险历史"""
    ENTERPRISE_DIR.mkdir(parents=True, exist_ok=True)

    history = {
        "last_updated": datetime.now(UTC).isoformat(),
        "total": len(results),
        "not_worth": len([r for r in results if not r["is_worth_applying"]]),
        "high_risk": len([r for r in results if r["risk_level"] == "高"]),
        "results": results[:30]
    }

    RISK_HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="政策逆向过滤器")
    parser.add_argument("--policy-id", help="政策ID")
    parser.add_argument("--batch", action="store_true", help="批量过滤")
    parser.add_argument("--show-warn", action="store_true", help="只显示高风险")

    args = parser.parse_args()

    if args.policy_id:
        result = filter_policy(args.policy_id)
        if result:
            policy = load_policy(args.policy_id)
            print_risk_result(result, policy)
    elif args.batch:
        print("[批量风险过滤]")
        results = batch_filter()

        if args.show_warn:
            results = [r for r in results if r["risk_level"] == "高"]
            print(f"高风险政策: {len(results)} 条")
        else:
            print(f"共 {len(results)} 条政策")

        print("-" * 60)

        level_emoji = {"高": "🔴", "中": "🟡", "低": "🟢"}
        for r in results[:20]:
            emoji = level_emoji.get(r["risk_level"], "⚪")
            pre = "前补" if r.get("is_pre_subsidy") else "后补"
            print(f"{emoji}{r['risk_level']} {r['risk_score']:>4.1f}/10 | "
                  f"{pre} | {r['title'][:40]}")

        save_risk_history(results)
        print(f"\n已保存风险历史到: {RISK_HISTORY_FILE}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
