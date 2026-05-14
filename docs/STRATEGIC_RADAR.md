# 企业战略雷达 (Strategic Radar)
> 版本: v1.0 | 创建: 2026-05-14
> 核心功能: 政策数据 → 高频词分析 → 趋势预判 → 战略建议

---

## 一、核心思路

```
政策文本 → 高频词提取 → 政策热度 → 资金流向 → 行业预判
                                    ↓
                            战略建议输出
```

**本质**: 政策本质上是"国家未来五年的投资地图"。通过监控政策高频词和补贴流向，可以：
- 提前预判哪个行业会拿钱
- 提前预判哪个赛道会爆发
- 提前预判哪些方向国家会持续投入

---

## 二、高频词分析

```python
class HighFrequencyAnalyzer:
    """政策高频词分析"""
    
    def extract_keywords(self, policies: list, window_days: int = 90) -> dict:
        """提取高频词"""
        
        # 收集近期政策文本
        texts = []
        for p in policies:
            if self._is_recent(p, window_days):
                texts.append(p.get("title", ""))
                texts.extend(p.get("支持方向", []))
                texts.extend(p.get("政策原文关键词", []))
        
        # 词频统计
        word_freq = {}
        for text in texts:
            words = self._tokenize(text)
            for w in words:
                word_freq[w] = word_freq.get(w, 0) + 1
        
        # 按频率排序
        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
        
        return {
            "period": f"最近{window_days}天",
            "total_policies": len(policies),
            "keywords": sorted_words[:50],  # Top 50
            "trending_up": self._get_trending(sorted_words),
            "trending_down": self._get_declining(sorted_words)
        }
    
    def _tokenize(self, text: str) -> list:
        """分词"""
        # 简单分词 + 停用词过滤
        stop_words = {"关于", "支持", "建设", "发展", "推进", "促进", "的通知"}
        words = []
        for word in jieba.cut(text):
            if len(word) >= 2 and word not in stop_words:
                words.append(word)
        return words
```

---

## 三、资金流向追踪

```python
class FundFlowTracker:
    """政策资金流向追踪"""
    
    def track(self, policies: list) -> dict:
        """追踪资金流向"""
        
        flows = {
            "by_industry": {},    # 按行业
            "by_region": {},      # 按地区
            "by_level": {},       # 按级别
            "by_type": {}         # 按政策类型
        }
        
        for p in policies:
            amount = p.get("支持金额", {}).get("金额", 0)
            if not amount:
                continue
            
            # 按行业
            for direction in p.get("支持方向", []):
                flows["by_industry"][direction] = \
                    flows["by_industry"].get(direction, 0) + amount
            
            # 按地区
            for region in p.get("地区", []):
                flows["by_region"][region] = \
                    flows["by_region"].get(region, 0) + amount
            
            # 按级别
            level = p.get("级别", "未知")
            flows["by_level"][level] = \
                flows["by_level"].get(level, 0) + amount
        
        return flows
    
    def get_top_sectors(self, flows: dict, top_n: int = 10) -> list:
        """获取资金流入Top行业"""
        industry_flows = flows["by_industry"]
        sorted_flows = sorted(industry_flows.items(), key=lambda x: x[1], reverse=True)
        return sorted_flows[:top_n]
```

---

## 四、趋势预判

```python
class TrendPredictor:
    """趋势预判"""
    
    def predict(self, historical_policies: list, forecast_months: int = 6) -> dict:
        """预判未来趋势"""
        
        # 1. 计算每月政策发布量
        monthly_counts = self._count_by_month(historical_policies)
        
        # 2. 识别上升行业
        rising_sectors = self._identify_rising(historical_policies)
        
        # 3. 识别政策密集区
        policy_clusters = self._find_clusters(historical_policies)
        
        # 4. 生成预判
        predictions = []
        for sector in rising_sectors:
            predictions.append({
                "sector": sector,
                "confidence": "高" if sector["growth_rate"] > 0.5 else "中",
                "forecast": f"{sector['name']}将在未来{forecast_months}个月持续获得政策支持",
                "action": "建议提前布局{sector['name']}相关业务"
            })
        
        return {
            "predictions": predictions,
            "rising_sectors": rising_sectors,
            "monthly_trend": monthly_counts,
            "policy_clusters": policy_clusters
        }
```

---

## 五、战略建议生成

```python
STRATEGIC_ADVISOR_PROMPT = """
你是企业战略顾问。基于政策分析，给出战略建议。

## 输入数据:
- 高频词分析结果
- 资金流向追踪结果
- 趋势预判结果
- 企业画像

## 输出战略建议JSON:
{
  "战略机会": [
    {
      "方向": "xxx",
      "依据": "近30天出现xx次，政策支持力度增大",
      "建议行动": "提前布局xxx",
      "优先级": "高|中|低"
    }
  ],
  "风险预警": [
    {
      "方向": "xxx",
      "风险": "政策退出或支持减弱",
      "建议": "收缩或转移"
    }
  ],
  "资源调配建议": {
    "短期": "优先投入xxx",
    "中期": "布局xxx",
    "长期": "关注xxx"
  }
}
"""

class StrategicAdvisor:
    def advise(self, analysis: dict, enterprise: dict) -> dict:
        """生成战略建议"""
        response = llm.chat.completions.create(
            model="gemini-2.5-flash",
            messages=[
                {"role": "system", "content": STRATEGIC_ADVISOR_PROMPT},
                {"role": "user", "content": json.dumps(analysis, ensure_ascii=False)}
            ],
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
```

---

## 六、可视化Dashboard

```
┌─────────────────────────────────────────────────────────────┐
│                    企业战略雷达 DASHBOARD                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  📊 高频词云 (近90天)                                        │
│  ┌─────────────────────────────────────────────────────┐    │
│  │    低空经济(28)  智慧物流(25)  AI调度(22)           │    │
│  │   新质生产力(20)  数字孪生(18)  数字化转型(15)     │    │
│  │      碳中和(12)      新基建(10)                    │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  💰 资金流向 (Top 5)                                        │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 低空经济        ████████████████████  5.2亿         │    │
│  │ 智慧物流        ████████████████      3.8亿         │    │
│  │ AI调度          █████████████          2.1亿         │    │
│  │ 数字孪生        ██████████              1.5亿         │    │
│  │ 碳中和          ██████                  0.8亿         │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  📈 趋势预判                                                │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 🚀 上升行业: 低空经济(+85%) AI调度(+60%)           │    │
│  │ ⚠️ 注意: 传统快递政策减少(-30%)                     │    │
│  │ 💡 预判: 未来6个月低空经济将持续密集支持            │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  🎯 战略建议                                                │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 1. [高优先级] 布局无人机配送试点，争取低空资质      │    │
│  │ 2. [高优先级] AI调度平台迭代，包装为智慧物流专项   │    │
│  │ 3. [中优先级] 关注数字孪生物流方向                 │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 七、与现有系统集成

```python
# scripts/strategic_radar.py

def run_strategic_analysis():
    """战略分析主流程"""
    
    # 1. 加载近期政策
    policies = load_policies(days=90)
    
    # 2. 高频词分析
    keyword_analyzer = HighFrequencyAnalyzer()
    keywords = keyword_analyzer.extract_keywords(policies)
    
    # 3. 资金流向
    fund_tracker = FundFlowTracker()
    flows = fund_tracker.track(policies)
    
    # 4. 趋势预判
    predictor = TrendPredictor()
    predictions = predictor.predict(policies)
    
    # 5. 战略建议
    advisor = StrategicAdvisor()
    enterprise = load_enterprise_profile()
    advice = advisor.advise({
        "keywords": keywords,
        "flows": flows,
        "predictions": predictions
    }, enterprise)
    
    # 6. 输出报告
    report = {
        "generated_at": datetime.now().isoformat(),
        "keywords": keywords,
        "flows": flows,
        "predictions": predictions,
        "advice": advice
    }
    
    save_report(report, "data/reports/strategic-radar.json")
    
    return report
```

---

## 八、执行计划

| 阶段 | 内容 | 优先级 |
|------|------|--------|
| Phase 1 | 高频词提取 + 基础Dashboard | P1 |
| Phase 2 | 资金流向可视化 | P2 |
| Phase 3 | 趋势预判模型 | P2 |
| Phase 4 | 战略建议生成 | P2 |
| Phase 5 | 实时预警机制 | P3 |

---

*这是Policy OS的长期演进方向*
