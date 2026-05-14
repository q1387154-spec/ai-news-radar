# 申报策略Agent + 政策包装 + 逆向过滤
> 版本: v1.0 | 创建: 2026-05-14
> 三个Agent协同: 策略 → 包装 → 风险过滤

---

## 一、三Agent协作架构

```
政策解析结果
    ↓
┌─────────────────────────────────────┐
│  申报策略Agent                       │
│  - 推荐申报优先级                    │
│  - 推荐项目名称                      │
│  - 推荐联合申报单位                 │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│  政策包装Agent                       │
│  - 企业项目 → 政策语言翻译          │
│  - 生成申报材料关键词               │
│  - 项目名称包装                     │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│  逆向过滤Agent                       │
│  - 识别"陷阱"政策                   │
│  - 评估陪跑风险                     │
│  - 识别验收雷区                     │
└─────────────────────────────────────┘
    ↓
最终申报建议
```

---

## 二、申报策略Agent

```python
STRATEGY_AGENT_PROMPT = """
你是政策申报策略专家。基于政策分析和企业画像，给出申报策略建议。

## 输入:
- 政策结构化信息
- 企业画像
- 匹配得分
- 评分结果

## 输出策略JSON:
{
  "申报优先级": "P0|P1|P2|P3",
  "建议申报时间": "立即、本周、本月、观察",
  "推荐项目名称": ["名称1", "名称2"],
  "项目定位": "描述项目核心价值",
  "建议联合申报单位": [
    {"单位": "xxx", "理由": "补充资质/技术/产业链"}
  ],
  "材料准备重点": ["重点1", "重点2"],
  "时间节点": {
    "启动": "建议日期",
    "材料截止": "提前5天",
    "提交": "截止前3天"
  }
}

## 策略原则:
1. P0政策: 24小时内启动，优先配置资源
2. 优先选择前补贴
3. 优先选择无验收或简单验收
4. 联合申报可补资质短板
"""

class StrategyAgent:
    def generate(self, policy: dict, profile: dict, match: MatchResult, score: ScoreResult) -> dict:
        """生成申报策略"""
        response = llm.chat.completions.create(
            model="gemini-2.5-flash",
            messages=[
                {"role": "system", "content": STRATEGY_AGENT_PROMPT},
                {"role": "user", "content": json.dumps({
                    "policy": policy,
                    "profile": profile,
                    "match": match.__dict__,
                    "score": score.dimensions
                }, ensure_ascii=False)}
            ],
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
```

---

## 三、政策包装Agent

```python
PACKAGING_AGENT_PROMPT = """
你是政策申报材料包装专家。擅长将企业实际业务"翻译"成政策语言。

## 核心能力:
- 将技术方案转化为政策支持方向语言
- 将业务描述包装成符合政策导向的申报标题
- 提取政策关键词，用于申报材料

## 企业项目 → 政策语言映射:

企业实际业务:
- 运输调度平台 → 现代流通体系 | AI+物流 | 智慧供应链 | 智能调度
- 数字孪生 → 数字孪生技术 | 智慧物流 | 新基建 | 数字化转型
- 无人机配送 → 低空经济 | 无人配送 | 新质生产力 | 智慧物流
- 大数据分析 → 大数据 | 产业数字化 | 数据要素 | 智能化
- 云平台 → 云计算 | SaaS | 产业互联网 | 平台经济

## 输出JSON:
{
  "项目名称建议": ["官方申报用名1", "备选2"],
  "包装后描述": "200字以内的项目概述，符合政策导向",
  "政策语言关键词": ["词1", "词2", ...],
  "技术亮点翻译": {
    "原表述": "政策表述",
    ...
  },
  "申报材料目录": ["材料1", "材料2", ...],
  "注意事项": ["注意点1", ...]
}

## 包装原则:
1. 政策语言 ≠ 技术语言，要"翻译"
2. 突出"新质生产力"、"补链强链"、"数字化转型"等热点
3. 避免夸大，保持可验证
4. 标题要响亮但不能失实
"""

class PackagingAgent:
    def packaging(self, enterprise_project: str, policy: dict) -> dict:
        """将企业项目包装成政策语言"""
        response = llm.chat.completions.create(
            model="gemini-2.5-flash",
            messages=[
                {"role": "system", "content": PACKAGING_AGENT_PROMPT},
                {"role": "user", "content": f"""
企业项目: {enterprise_project}
目标政策: {policy['title']}
政策支持方向: {policy.get('支持方向', [])}
"""}
            ],
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
```

---

## 四、逆向过滤Agent（最值钱）

```python
REVERSE_FILTER_PROMPT = """
你是政策风险评估专家。擅长识别"看起来好，实际坑多"的政策。

## 核心问题:
1. 这个政策是不是"陪跑奖"？
2. 验收条件企业能否达到？
3. 是否需要大量垫资？
4. 是否有隐藏的地方保护要求？

## 风险类型:

### A. 高危（强烈不建议）
- 要求本地注册法人且税收归本地
- 要求采购本地设备且占比>50%
- 要求产业化但市场不明确
- 需配套资金超过企业承受能力

### B. 中危（谨慎申报）
- 后补贴且验收周期超过1年
- 验收条件包含主观评价
- 需与国企/政府联合申报
- 资金分批拨付，尾款难要

### C. 低危（可申报）
- 前补贴
- 验收条件明确可量化
- 无垫资要求
- 往年执行稳定

## 输出JSON:
{
  "风险等级": "高|中|低",
  "风险总分": 0-10 (越高越危险),
  "详细风险": [
    {
      "风险点": "描述",
      "等级": "高|中|低",
      "建议": "如何规避或应对"
    }
  ],
  "是否值得申报": true|false,
  "申报建议": "综合建议"
}

## 判断标准:
- 风险总分 > 7: 强烈不建议
- 风险总分 4-7: 谨慎申报，充分评估
- 风险总分 < 4: 可申报
"""

class ReverseFilterAgent:
    def filter(self, policy: dict, enterprise_profile: dict) -> dict:
        """逆向过滤：识别政策陷阱"""
        response = llm.chat.completions.create(
            model="gemini-2.5-flash",
            messages=[
                {"role": "system", "content": REVERSE_FILTER_PROMPT},
                {"role": "user", "content": json.dumps({
                    "policy": policy,
                    "enterprise": enterprise_profile
                }, ensure_ascii=False)}
            ],
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
    
    def is_worth_applying(self, risk_result: dict) -> tuple:
        """判断是否值得申报"""
        if risk_result["风险等级"] == "高":
            return False, "风险过高，建议放弃"
        elif risk_result["风险等级"] == "中":
            if risk_result["风险总分"] > 6:
                return False, "风险较大，谨慎申报"
            return True, "风险可控，可申报但需充分准备"
        else:
            return True, "风险低，建议申报"
```

---

## 五、综合决策流

```python
def evaluate_policy(policy: dict, enterprise: dict) -> FinalRecommendation:
    """完整政策评估流程"""
    
    # 1. 匹配
    matcher = PolicyMatcher(enterprise)
    match = matcher.match(policy)
    
    if match.total_score < 0.3:
        return FinalRecommendation(
            decision="skip",
            reason="匹配度太低(<30%)"
        )
    
    # 2. 评分
    scorer = PolicyScorer()
    score = scorer.score(policy, match)
    
    # 3. 逆向过滤
    filter_agent = ReverseFilterAgent()
    risk = filter_agent.filter(policy, enterprise)
    worth, risk_advice = filter_agent.is_worth_applying(risk)
    
    if not worth:
        return FinalRecommendation(
            decision="skip",
            reason=f"风险过高: {risk['风险点'][0]['风险点']}",
            risk_details=risk
        )
    
    # 4. 申报策略
    strategy_agent = StrategyAgent()
    strategy = strategy_agent.generate(policy, enterprise, match, score)
    
    # 5. 包装
    packaging_agent = PackagingAgent()
    # 假设企业有这些项目
    for project in enterprise.get("key_projects", []):
        packaging = packaging_agent.packaging(project, policy)
        if packaging:
            break
    
    # 6. ROI
    roi = scorer.estimate_roi(policy, match)
    
    return FinalRecommendation(
        decision="apply",
        level=score.level,
        priority=score.priority,
        match_score=match.total_score,
        policy_score=score.final,
        strategy=strategy,
        packaging=packaging,
        risk=risk,
        roi=roi,
        project_name=strategy.get("推荐项目名称", ["待定"])[0],
        key_words=packaging.get("政策语言关键词", [])
    )
```

---

## 六、最终输出示例

```json
{
  "decision": "apply",
  "level": "A",
  "priority": "P1",
  
  "match_score": 0.85,
  "policy_score": 82.5,
  
  "strategy": {
    "申报优先级": "P1",
    "建议申报时间": "本周",
    "推荐项目名称": ["基于AI的智能物流调度平台"],
    "材料准备重点": ["技术方案", "应用效果数据"]
  },
  
  "packaging": {
    "项目名称建议": ["智慧物流AI调度系统"],
    "政策语言关键词": ["现代流通体系", "AI+物流", "新质生产力", "补链强链"],
    "包装后描述": "项目以AI技术为核心，构建智能化物流调度体系..."
  },
  
  "risk": {
    "风险等级": "低",
    "风险总分": 2.5,
    "详细风险": [
      {"风险点": "需本地部署验收", "等级": "低", "建议": "提前与技术部门沟通"}
    ]
  },
  
  "roi": {
    "estimated_subsidy": 300,
    "expected_net": 280,
    "roi": 2.8,
    "roi_label": "高"
  }
}
```

---

*下一步: 整合到主流程，改造 index.html 前端展示*
