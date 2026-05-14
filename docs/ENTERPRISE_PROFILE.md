# 企业画像系统 (Enterprise Profile)
> 版本: v1.0 | 创建: 2026-05-14
> 核心功能: 构建中通吉企业画像，匹配政策并评分

---

## 一、企业画像定义

```yaml
# data/enterprise/ztj-profile.yaml

enterprise:
  name: 上海中通吉网络技术有限公司
  short_name: 中通吉
  region: 
    - 上海
    - 青浦区
    - 长三角示范区
  
  industry:
    - 物流
    - 快递
    - 供应链
    - 网络货运
  
  tech_stack:
    - AI调度
    - 数字孪生
    - 自动驾驶
    - 低空经济(无人机配送)
    - 大数据分析
    - 云计算
  
  business:
    - 快递服务
    - 智慧物流
    - 末端配送
    - 即时配送
    - 国际物流
  
  certifications:
    owned:
      - 高新技术企业  # 需要确认
      - 科技型中小企业  # 需要确认
      - ISO9001
      - ISO27001
    
    target:
      - 专精特新
      - 企业技术中心
  
  scale:
    employees: "~10000+"  # 集团层面
    revenue: "百亿级"
    rd_ratio: ">3%"        # 研发投入占比
  
  key_projects:
    - 运输调度平台
    - 数字孪生物流系统
    - 无人机配送试点
  
  ai_keywords:
    # 企业项目 → 政策包装关键词映射
    运输调度平台:
      - 现代流通体系
      - AI+物流
      - 智慧供应链
      - 智能调度
    数字孪生:
      - 数字孪生
      - 智慧物流
      - 新基建
    无人机配送:
      - 低空经济
      - 无人配送
      - 智慧物流
      - 新质生产力
```

---

## 二、政策匹配引擎

```python
class PolicyMatcher:
    """企业画像与政策匹配"""
    
    def __init__(self, profile: dict):
        self.profile = profile
    
    def match(self, policy: dict) -> MatchResult:
        """计算政策与企业的匹配度"""
        
        score = 0.0
        matched_tags = []
        missing_tags = []
        
        # 1. 行业匹配 (25%)
        industry_match = self._match_lists(
            policy.get("支持方向", []),
            self.profile["industry"] + self.profile["tech_stack"]
        )
        score += industry_match * 0.25
        matched_tags.extend(industry_match.matched)
        
        # 2. 地域匹配 (20%)
        region_match = self._match_lists(
            policy.get("地区", []),
            self.profile["region"]
        )
        score += region_match * 0.20
        
        # 3. 资质匹配 (25%)
        cert_match = self._check_certs(policy, self.profile)
        score += cert_match.score * 0.25
        matched_tags.extend(cert_match.matched)
        missing_tags.extend(cert_match.missing)
        
        # 4. 技术方向匹配 (20%)
        tech_match = self._match_lists(
            policy.get("支持方向", []),
            self.profile["tech_stack"]
        )
        score += tech_match * 0.20
        matched_tags.extend(tech_match.matched)
        
        # 5. 业务匹配 (10%)
        biz_match = self._match_lists(
            policy.get("支持方向", []),
            self.profile["business"]
        )
        score += biz_match * 0.10
        
        return MatchResult(
            total_score=round(score, 3),
            matched_tags=list(set(matched_tags)),
            missing_tags=list(set(missing_tags)),
            recommendation=self._get_recommendation(score, cert_match)
        )
    
    def _check_certs(self, policy: dict, profile: dict) -> CertResult:
        """检查资质匹配"""
        required = policy.get("申报条件", {}).get("必要资质", [])
        owned = profile["certifications"]["owned"]
        
        matched = [c for c in required if c in owned]
        missing = [c for c in required if c not in owned]
        
        score = len(matched) / len(required) if required else 1.0
        
        return CertResult(
            score=score,
            matched=matched,
            missing=missing
        )
```

---

## 三、匹配结果示例

```python
# 匹配示例
matcher = PolicyMatcher(ztj_profile)
result = matcher.match({
    "title": "关于支持智慧物流体系建设的通知",
    "地区": ["上海", "青浦"],
    "支持方向": ["智慧物流", "AI调度", "数字孪生"],
    "申报条件": {
        "必要资质": ["高新技术企业"]
    }
})

# 输出:
MatchResult(
    total_score=0.85,
    matched_tags=["物流", "AI调度", "数字孪生", "上海", "青浦", "高新技术企业"],
    missing_tags=[],
    recommendation="强烈推荐申报"
)
```

---

## 四、企业画像存储

```
data/enterprise/
├── ztj-profile.yaml          # 中通吉画像
├── profiles/                  # 其他企业画像
│   ├── supplier.yaml         # 供应商
│   └── partner.yaml          # 合作伙伴
├── match_history.json        # 匹配历史
└── policy-hits.json          # 命中政策记录
```

---

## 五、政策命中追踪

```json
// data/enterprise/policy-hits.json
{
  "last_updated": "2026-05-14T09:35:00+08:00",
  "total_hits": 12,
  "by_level": {
    "S": 2,
    "A": 5,
    "B": 5
  },
  "recent_hits": [
    {
      "policy_id": "ndrc_2026_567",
      "title": "关于支持现代物流体系建设的通知",
      "match_score": 0.85,
      "level": "A",
      "priority": "P1",
      "matched_at": "2026-05-14T08:00:00+08:00"
    }
  ]
}
```

---

## 六、快速匹配接口

```python
# scripts/match_policy.py

def quick_match(policy_id: str) -> dict:
    """快速匹配单个政策"""
    policy = load_policy(policy_id)
    profile = load_profile("ztj-profile.yaml")
    matcher = PolicyMatcher(profile)
    result = matcher.match(policy)
    
    return {
        "policy_id": policy_id,
        "title": policy["title"],
        "match_score": result.total_score,
        "matched_tags": result.matched_tags,
        "missing_tags": result.missing_tags,
        "recommendation": result.recommendation
    }

def batch_match(window_hours: int = 48) -> list:
    """批量匹配近期政策"""
    policies = load_recent_policies(window_hours)
    profile = load_profile("ztj-profile.yaml")
    matcher = PolicyMatcher(profile)
    
    results = []
    for p in policies:
        result = matcher.match(p)
        if result.total_score >= 0.5:  # 50%以上匹配度
            results.append({
                "policy_id": p["id"],
                "title": p["title"],
                "score": result.total_score,
                **result.__dict__
            })
    
    return sorted(results, key=lambda x: x["score"], reverse=True)
```

---

*下一步: 集成到 update_news.py，实现自动匹配+评分*
