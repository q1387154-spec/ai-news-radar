---
name: policy-opportunities
description: 物流政策情报雷达 — 政策匹配、申报评估、源自动发现。读取 data/scored/scored_{date}.json，生成申报建议。
version: "2.0"
author: 克劳
tags: [政策, 申报, 物流, 快递, 上海, 青浦, 雷达]
category: business
---

# 政策机会系统 v2.0 (Policy Opportunities System)

> **定位**: 从海量政策信息中，找到真正值得申报的机会
> **核心能力**: 语义匹配 + 申报可行性评估 + 源自动发现

---

## 系统架构

```
GitHub Actions（8h / 13h / 20h 北京时间）
    │
    ├── fetch_policies.py    三路并行抓取
    │     ├── Tavily 语义搜索（需 TAVILY_API_KEY）
    │     ├── cn-search（搜狗微信 + 百度，无需 key）
    │     └── 政府 HTML 直抓
    │
    ├── merge.py             合并去重
    │
    ├── score_policies.py     MiniMax 语义评分（S/A/B/C）
    │     └── 备用：关键词评分（无 key 时）
    │
    └── discover_sources.py   源自动发现
          └── pending → approved 人工确认

结果文件:
  data/raw/{date}_{run_id}.json       原始数据
  data/merged/merged_{date}.json       合并去重后
  data/scored/scored_{date}.json      评分结果 ← 主力输入
  data/sources/sources.json          源列表
  reports/{date}.json                  简报
```

---

## 评分体系

| 等级 | 分数 | 含义 | 推送 |
|------|------|------|------|
| **S** | 85+ | 高度匹配 + 金额明确 + 近截止 + 无风险 | 🔴 立即推送 |
| **A** | 70-84 | 匹配 + 有金额 + 风险可控 | 🟠 24h 内确认 |
| **B** | 50-69 | 部分匹配，待评估 | 📋 列入观察 |
| **C** | <50 | 关联度低 | 静默 |

**评分维度**（MiniMax 语义评分）:
- 行业相关性（物流/快递）× 0.25
- 地域匹配（上海/青浦）× 0.15
- 赛道相关性（低空经济/AI/数字化等）× 0.20
- 资质匹配（高企/科小）× 0.15
- 时间紧迫度 × 0.15
- 资金明确度 × 0.10

---

## 申报红线

1. **不编文件名/文号** — 只引用原文
2. **不说"必过"** — 任何申报均有风险
3. **deadline 永远第一位** — 过期政策无意义
4. **垫资风险 > 收益 → 不推**
5. **验收条件不明确 → 不推**

---

## 决策框架

| 框架 | 适用场景 |
|------|---------|
| 段永平·本分 | 这件事该不该申报？实事求是 |
| 芒格·逆向 | 最容易在哪被打回？死在哪个环节？ |
| 毛泽东·矛盾 | 当前最卡的是什么？（资质/时间/垫资/垫资） |

---

## 使用方式

### 1. 每日简报（自动）

GitHub Actions 完成后：
- S/A 级 → 推送克劳分析报告到微信
- 无 S/A 级 → 静默，不打扰

### 2. 手动查询某条政策

```
python scripts/score_policies.py 2026-05-22
```

读取 `data/scored/scored_2026-05-22.json`，输出简报。

### 3. 查看源发现状态

```
cat data/sources/sources.json
```

pending 队列需要人工确认是否加入 approved。

### 4. 深度分析特定政策

直接读取政策原文 + scored 数据：
- 申报条件是否匹配
- 验收标准是否清晰
- 最大风险点
- 项目包装建议

---

## 数据格式

### scored_{date}.json 字段说明

```json
{
  "id": "原始ID",
  "title": "政策标题",
  "url": "https://...",
  "source": "sogou_wechat|baidu|gov_html|tavily",
  "published_at": "2026-05-20",
  "snippet": "摘要...",
  "score": 85,
  "grade": "S",
  "deadline": "2026-06-30",
  "amount": "最高300万元",
  "requirements": ["条件1", "条件2"],
  "fit_summary": "高度相关：...",
  "risk_flags": ["需垫资"],
  "apply_recommendation": "强烈建议申报",
  "channel": "低空经济/无人配送"
}
```

### sources.json 字段说明

```json
{
  "sources": {
    "approved": [{ "id", "name", "url", "type", "tier", "addedAt", "topics" }],
    "pending":  [{ "id", "name", "url", "type", "tier", "addedAt", "topics", "matchedPolicyIds" }]
  }
}
```

---

## 六大赛道关键词

| 赛道 | 关键词 |
|------|--------|
| 低空经济/无人配送 | 低空经济, eVTOL, 无人机物流, 空域改革, 无人配送 |
| 超长期国债/两新 | 超长期国债, 两重两新, 设备更新, 技改, 专项债 |
| AI+物流 | 智慧物流, 物流大模型, AI调度, 数字孪生, 数据要素 |
| 专精特新/高企 | 专精特新, 高企, 研发费用加计扣除, 小巨人 |
| 人社补贴 | 稳岗返还, 技能补贴, 培训, 就业见习 |
| 物流行业 | 物流, 快递, 供应链, 仓储, 网络货运 |

---

## 企业画像

```
上海中通吉网络技术有限公司
├── 行业: 物流 / 快递 / 供应链
├── 区域: 上海 / 青浦 / 长三角
├── 资质: 科技型中小企业（已认定），高新技术企业（待确认）
├── 重点: 智慧物流 / 无人机配送 / AI调度 / 低空经济
└── 偏好: 不垫资 / 不陪跑 / 验收量化
```

---

## CI/CD 说明

- **触发**: 每天 08:00 / 13:00 / 20:00（北京时间）
- **手动触发**: GitHub Actions → Policy Radar Pipeline → Run workflow
- **Secrets 需要**:
  - `TAVILY_API_KEY` — Tavily 语义搜索（免费额度 1000 次/月）
  - `MINIMAX_API_KEY` — MiniMax 评分（备用方案无需 key）
- **Pages 重建**: fork 限制，需手动 Settings → Pages → Re-run
