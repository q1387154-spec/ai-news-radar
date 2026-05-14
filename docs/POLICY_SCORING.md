# 政策评分系统 (Policy Scoring)
> 版本: v1.0 | 创建: 2026-05-14
> 核心功能: 多维度评分 → 推荐等级 + 申报优先级

---

## 一、评分维度

| 维度 | 权重 | 说明 | 计算方式 |
|------|------|------|---------|
| **金额规模** | 20% | 支持金额大小 | max(金额/基准, 1.0)，上限1.0 |
| **申报难度** | 15% | 条件门槛高低 | 条件越少分越高 |
| **命中概率** | 25% | 企业匹配度 | 企业画像匹配得分 |
| **地域匹配** | 15% | 地域覆盖度 | 完全匹配=1.0，部分=0.5 |
| **行业匹配** | 15% | 行业相关性 | 关键词命中数量/总数 |
| **时间紧迫度** | 10% | 窗口期剩余 | 剩余天数越少分越高 |

---

## 二、评分计算

```python
class PolicyScorer:
    """政策评分器"""
    
    AMOUNT_BASELINE = 100  # 基准金额: 100万
    
    def score(self, policy: dict, match_result: MatchResult) -> ScoreResult:
        """计算综合评分"""
        
        dimensions = {
            "amount": self._score_amount(policy),           # 20%
            "difficulty": self._score_difficulty(policy),   # 15%
            "hit_rate": match_result.total_score,           # 25% (复用匹配结果)
            "region_match": self._score_region(policy),    # 15%
            "industry_match": self._score_industry(policy), # 15%
            "urgency": self._score_urgency(policy),        # 10%
        }
        
        # 加权求和
        weights = [0.20, 0.15, 0.25, 0.15, 0.15, 0.10]
        final_score = sum(d * w for d, w in zip(dimensions.values(), weights))
        
        # 计算等级
        level = self._get_level(final_score)
        
        # 计算优先级
        priority = self._get_priority(final_score, dimensions["urgency"], match_result.missing_tags)
        
        # 是否后补贴标记
        is_pre_subsidy = policy.get("是否后补贴", False)
        
        return ScoreResult(
            final=round(final_score, 1),
            level=level,
            priority=priority,
            dimensions=dimensions,
            is_pre_subsidy=is_pre_subsidy,
            reasons=self._get_reasons(dimensions, match_result)
        )
    
    def _score_amount(self, policy: dict) -> float:
        """金额规模评分"""
        amount = policy.get("支持金额", {}).get("金额", 0)
        if not amount:
            return 0.5  # 无金额信息给中间分
        
        score = min(amount / self.AMOUNT_BASELINE, 1.0)
        return score
    
    def _score_difficulty(self, policy: dict) -> float:
        """申报难度评分 (越容易分越高)"""
        conditions = policy.get("申报条件", {})
        
        difficulty_factors = 0
        
        # 必要资质越多越难
        certs = conditions.get("必要资质", [])
        difficulty_factors += len(certs) * 0.2
        
        # 有投资要求
        if conditions.get("投资要求"):
            difficulty_factors += 0.2
        
        # 有规模要求
        if conditions.get("规模要求"):
            difficulty_factors += 0.1
        
        # 有验收要求
        if policy.get("验收要求"):
            difficulty_factors += 0.2
        
        return max(0.0, 1.0 - difficulty_factors)
    
    def _score_urgency(self, policy: dict) -> float:
        """时间紧迫度评分"""
        deadline = policy.get("申报截止时间")
        if not deadline:
            return 0.5  # 无截止时间给中间分
        
        days_left = (deadline - datetime.now()).days
        
        if days_left < 0:
            return 0.0  # 已过期
        elif days_left <= 7:
            return 1.0  # 紧急
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
        enterprise_regions = ["上海", "青浦", "长三角"]
        
        # 完全匹配上海/青浦
        if any(r in ["上海", "青浦"] for r in regions):
            return 1.0
        # 匹配长三角
        elif any(r in ["长三角", "江苏", "浙江"] for r in regions):
            return 0.7
        # 国家级
        elif "全国" in regions or "国家级" in regions:
            return 0.5
        else:
            return 0.3
    
    def _score_industry(self, policy: dict) -> float:
        """行业匹配评分"""
        directions = policy.get("支持方向", [])
        enterprise_industries = [
            "物流", "快递", "供应链", "AI调度", "数字孪生",
            "低空经济", "自动驾驶", "智慧物流"
        ]
        
        matched = sum(1 for d in directions if any(e in d for e in enterprise_industries))
        return matched / len(directions) if directions else 0.5
```

---

## 三、等级划分

```python
def _get_level(self, score: float) -> str:
    if score >= 85:
        return "S"  # 强烈推荐
    elif score >= 70:
        return "A"  # 建议申报
    elif score >= 50:
        return "B"  # 可选申报
    else:
        return "C"  # 暂不推荐

def _get_priority(self, score: float, urgency: float, missing_tags: list) -> str:
    # 综合评分和时间紧迫度
    if score >= 85 and urgency >= 0.6:
        return "P0"  # 立即行动
    elif score >= 70 and urgency >= 0.4:
        return "P1"  # 本周完成
    elif score >= 50:
        return "P2"  # 列入计划
    else:
        return "P3"  # 观察
```

---

## 四、ROI估算

```python
def estimate_roi(self, policy: dict, match_result: MatchResult) -> dict:
    """估算申报ROI"""
    
    # 基础数据
    subsidy = policy.get("支持金额", {}).get("金额", 0)  # 万
    is_pre = not policy.get("是否后补贴", False)
    has_验收 = bool(policy.get("验收要求"))
    
    # 估算成本
    # 人力成本 (2人 * 2周 * 0.5万/周)
    labor_cost = 2 * 2 * 0.5  # 万
    
    # 材料成本
    material_cost = 0.3  # 万
    
    # 可能的垫资 (后补贴)
    advance_fund = subsidy * 0.3 if is_pre else 0  # 万
    
    # 陪跑风险
    risk_factor = 0.2 if match_result.missing_tags else 0.05
    
    # 预期收益
    expected_subsidy = subsidy * (1 - risk_factor)
    
    # ROI
    total_cost = labor_cost + material_cost + advance_fund
    roi = (expected_subsidy - total_cost) / total_cost if total_cost > 0 else 0
    
    return {
        "estimated_subsidy": subsidy,  # 万
        "labor_cost": labor_cost,      # 万
        "material_cost": material_cost,# 万
        "advance_fund_needed": advance_fund,  # 万 (仅后补贴)
        "risk_factor": risk_factor,
        "expected_net": expected_subsidy - total_cost,
        "roi": round(roi, 2),
        "roi_label": "高" if roi > 2 else "中" if roi > 1 else "低"
    }
```

---

## 五、评分结果示例

```python
result = scorer.score(policy, match_result)

# 输出:
ScoreResult(
    final=82.5,
    level="A",
    priority="P1",
    dimensions={
        "amount": 0.85,
        "difficulty": 0.70,
        "hit_rate": 0.85,
        "region_match": 1.0,
        "industry_match": 0.90,
        "urgency": 0.60
    },
    is_pre_subsidy=True,
    reasons=[
        "✅ 支持智慧物流方向，完全匹配",
        "✅ 上海青浦地域，完全匹配", 
        "✅ 支持金额500万，规模较大",
        "⚠️ 需高新技术企业资质",
        "⚠️ 截止时间还有45天"
    ]
)

roi = scorer.estimate_roi(policy, match_result)
# ROI: 2.3 (高)
```

---

## 六、前端展示

```
政策评分卡片:
┌─────────────────────────────────────┐
│ 🔥 S级推荐 │ 💰 82.5分 │ ⏰ P1优先级 │
├─────────────────────────────────────┤
│ 支持金额: 500万    窗口期: 45天      │
│ 匹配度: 85%      等级: 高新技术企业│
├─────────────────────────────────────┤
│ 维度得分:                            │
│ 💰 金额 17/20  ████████████░░      │
│ 📋 难度 10.5/15 ██████░░░░░░       │
│ 🎯 命中 21.25/25 ████████████░░    │
│ 📍 地域 15/15   ██████████████     │
│ 🏭 行业 13.5/15 ████████░░░░       │
│ ⏱ 紧迫 6/10    ███░░░░░░░░        │
├─────────────────────────────────────┤
│ 风险提示:                           │
│ ⚠️ 需高新技术企业资质               │
│ ⚠️ 需本地部署验收                   │
├─────────────────────────────────────┤
│ 💡 建议项目: 基于AI的智能调度平台   │
│ 📦 包装关键词: 智慧物流/新质生产力  │
└─────────────────────────────────────┘
```

---

*下一步: 申报策略Agent → 政策包装 → 逆向过滤*
