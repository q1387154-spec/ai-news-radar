# AI News Radar - Policy OS Agent Notes

## 产品定位

**原定位**: AI新闻聚合器（信息聚合）  
**新定位**: 政策决策操作系统 Policy OS（政策机会流）

**核心转变**: 从"看新闻"到"找机会"到"做决策"

---

## 架构升级

### 旧架构
```
RSS → JSON → 页面 (新闻流)
```

### 新架构
```
政策源(RSS/Gov)
    ↓
抓取层
    ↓
LLM结构化解析
    ↓
企业画像匹配
    ↓
政策评分 + 申报策略
    ↓
逆向过滤(风险识别)
    ↓
前端展示(政策机会流)
    ↓
战略雷达(长期)
```

---

## 核心模块

| 模块 | 文件 | 状态 |
|------|------|------|
| 政策结构化数据模型 | `docs/POLICY_SCHEMA.md` | ✅ |
| 政策源覆盖清单 | `docs/POLICY_SOURCES.md` | ✅ |
| LLM解析器设计 | `docs/POLICY_PARSER.md` | ✅ |
| 企业画像系统 | `docs/ENTERPRISE_PROFILE.md` | ✅ |
| 政策评分系统 | `docs/POLICY_SCORING.md` | ✅ |
| 申报策略+包装+逆向过滤 | `docs/POLICY_AGENTS.md` | ✅ |
| 战略雷达设计 | `docs/STRATEGIC_RADAR.md` | ✅ |
| Policy OS路线图 | `docs/ROADMAP_POLICY_OS.md` | ✅ |

---

## 数据模型

### Policy (政策)
```yaml
id: string
title: string
级别: national/provincial/municipal/district
地区: [上海, 青浦, ...]
主管部门: [发改委, 经信委, ...]
deadline: datetime
支持方向: [智慧物流, AI调度, ...]
支持金额: {金额, 单位}
申报条件: {必要资质, 规模要求, 投资要求}
企业匹配度: score
政策评分: {final, level, dimensions}
申报建议: {priority, project_names, risks}
```

### EnterpriseProfile (企业画像)
```yaml
name: 上海中通吉网络技术有限公司
industry: [物流, 快递, 供应链]
tech_stack: [AI调度, 数字孪生, 低空经济]
region: [上海, 青浦, 长三角]
certifications: {owned: [], target: []}
```

---

## 评分维度

| 维度 | 权重 |
|------|------|
| 金额规模 | 20% |
| 申报难度 | 15% |
| 命中概率(企业匹配) | 25% |
| 地域匹配 | 15% |
| 行业匹配 | 15% |
| 时间紧迫度 | 10% |

**等级**: S(85+) > A(70-84) > B(50-69) > C(<50)

---

## Agent系统

### 1. 申报策略Agent
- 推荐申报优先级
- 推荐项目名称
- 推荐联合申报单位

### 2. 政策包装Agent
- 企业项目 → 政策语言翻译
- 生成申报材料关键词
- 项目名称包装

### 3. 逆向过滤Agent
- 识别"陷阱"政策
- 评估陪跑风险
- 识别验收雷区

---

## 政策源分类

| 级别 | 优先级 | 源 |
|------|--------|-----|
| 国家级 | P0 | 发改委, 工信部, 科技部 |
| 上海市 | P0 | 经信委, 发改委, 科委 |
| 青浦区 | P0 | 经委, 科委, 财政局 |
| 物流专项 | P0 | 国家邮政局, 交通运输部 |
| 低空经济 | P0 | 民航局, 工信部无人机 |

---

## OPML配置

- 通用AI源: `feeds/follow.example.opml`
- 政策专用源: `feeds/policy.example.opml` (新增)
- 私有配置: `feeds/follow.opml` (不提交)

---

## 开发命令

```bash
# 政策源抓取
python scripts/update_news.py --output-dir data --window-hours 48 --rss-opml feeds/policy.example.opml

# LLM解析测试
python scripts/parse_policy.py --test

# 政策匹配测试
python scripts/match_policy.py --test

# 评分测试
python scripts/score_policy.py --test

# 本地预览
python -m http.server 8080
```

---

## 设计原则

1. **结构化先于展示**: 先有政策解析，再谈UI
2. **匹配先于评分**: 没有企业匹配，评分无意义
3. **过滤先于推荐**: 逆向过滤比正向推荐更值钱
4. **风险比收益更重要**: 识别"陪跑奖"比找到好政策更重要
5. **申报比拿到更难**: 重点关注验收难度

---

## 决策原则 (段永平·本分)

- 这件事该不该做？（政策值不值得申报）
- 实事求是（不夸大政策支持力度）
- 做对的事（不为了申报而申报）

---

## 风险原则 (芒格·逆向)

- 最容易在哪里被打回？（资质不匹配）
- 最容易死在哪个环节？（验收）
- 最容易被忽视的风险是什么？（垫资/陪跑）

---

## 安全规则

- 不提交私有配置
- 不泄露企业敏感信息
- 不夸大政策效果
- 不承诺申报成功率

---

## 工作流程

1. **扫描**: 抓取政策RSS
2. **解析**: LLM结构化提取
3. **画像**: 企业匹配打分
4. **过滤**: 逆向风险识别
5. **策略**: 申报方案生成
6. **包装**: 政策语言翻译
7. **展示**: 政策机会卡片

---
