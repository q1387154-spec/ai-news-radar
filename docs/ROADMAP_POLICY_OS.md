# 伯乐Policy OS 改造路线图
> 版本: v1.0 | 更新: 2026-05-14

---

## 目标架构

```
政策源 (RSS/Gov)
    ↓
抓取层 (scripts/)
    ↓
LLM结构化 (政策解析)
    ↓
企业画像匹配
    ↓
政策评分 + 申报策略
    ↓
逆向过滤 (风险识别)
    ↓
前端展示 (政策机会流)
    ↓
战略雷达 (长期)
```

---

## 当前状态 vs 目标

| 模块 | 当前 | 目标 |
|------|------|------|
| 数据源 | AI新闻RSS | 政策官网RSS |
| 内容 | 仅标题 | 全文+结构化 |
| 解析 | 无 | LLM提取 |
| 匹配 | 无 | 企业画像 |
| 评分 | 无 | 多维评分 |
| 策略 | 无 | 申报策略 |
| 包装 | 无 | 政策语言翻译 |
| 过滤 | 无 | 逆向风险过滤 |
| 前端 | 新闻列表 | 政策机会卡片 |

---

## 执行计划

### Phase 0: 基础修复（本周）

- [ ] 修复 `data/latest-gov.json` 为空问题
- [ ] 配置真正的政策RSS源（发改委/经信委/科委）
- [ ] 部署 GitHub Actions 验证

### Phase 1: 核心功能（2周）

| 任务 | 文档 | 状态 |
|------|------|------|
| 政策结构化数据模型 | `docs/POLICY_SCHEMA.md` | ✅ 完成 |
| 政策源覆盖清单 | `docs/POLICY_SOURCES.md` | ✅ 完成 |
| LLM解析器 | `docs/POLICY_PARSER.md` | ✅ 完成 |
| 企业画像系统 | `docs/ENTERPRISE_PROFILE.md` | ✅ 完成 |
| 政策评分系统 | `docs/POLICY_SCORING.md` | ✅ 完成 |
| 申报策略Agent | `docs/POLICY_AGENTS.md` | ✅ 完成 |

### Phase 2: 集成开发（2-3周）

- [ ] 开发 `scripts/parse_policy.py` - 政策解析脚本
- [ ] 开发 `scripts/match_policy.py` - 匹配脚本
- [ ] 开发 `scripts/score_policy.py` - 评分脚本
- [ ] 开发 `scripts/risk_filter.py` - 逆向过滤脚本
- [ ] 改造 `scripts/update_news.py` - 集成LLM解析
- [ ] 改造 `index.html` - 新增政策卡片展示

### Phase 3: 前端改造（1-2周）

- [ ] 政策评分卡片组件
- [ ] 申报建议展示
- [ ] 风险提示UI
- [ ] 高级筛选（按级别/金额/截止时间）

### Phase 4: 战略雷达（长期）

- [ ] 高频词提取
- [ ] 资金流向Dashboard
- [ ] 趋势预判
- [ ] 战略建议生成

---

## 技术栈

```
前端:     HTML/CSS/JS (现有)
后端:     Python 3
LLM:      Gemini 2.5 Flash (Google API)
数据:     JSON 文件
部署:     GitHub Actions + Pages
抓取:     RSS + Jina Reader (备选)
知识库:   本地 JSON (向量检索后续加)
```

---

## 关键文件

```
ai-news-radar-fork/
├── docs/
│   ├── POLICY_SCHEMA.md      # ✅ 结构化数据模型
│   ├── POLICY_SOURCES.md     # ✅ 政策源清单
│   ├── POLICY_PARSER.md      # ✅ LLM解析器设计
│   ├── ENTERPRISE_PROFILE.md # ✅ 企业画像
│   ├── POLICY_SCORING.md     # ✅ 评分系统
│   ├── POLICY_AGENTS.md      # ✅ 申报策略+包装+逆向过滤
│   └── STRATEGIC_RADAR.md    # ✅ 战略雷达设计
│
├── scripts/
│   ├── update_news.py        # 主抓取脚本 (待改造)
│   ├── parse_policy.py       # 新增: LLM解析
│   ├── match_policy.py       # 新增: 匹配
│   └── score_policy.py       # 新增: 评分
│
├── data/
│   ├── policies/             # 新增: 解析后政策库
│   ├── enterprise/           # 新增: 企业画像
│   └── reports/              # 新增: 分析报告
│
├── index.html                # 待改造: 政策卡片UI
└── feeds/
    └── policy.opml           # 新增: 政策RSS源
```

---

## 立即行动项

### 今天可以做的（2小时）

1. 配置 `feeds/policy.opml` - 政策RSS源
2. 手动运行一次抓取验证
3. 提交代码到 GitHub

### 本周可以做的（1-2天）

1. 开发 LLM 解析脚本
2. 测试政策结构化提取
3. 配置 GitHub Actions 自动抓取

### 下周可以做的（3-5天）

1. 开发匹配+评分
2. 改造前端展示
3. 配置企业画像

---

## 产品定位更新

**原来**: AI新闻雷达（信息聚合）  
**现在**: 政策决策操作系统（Policy OS）

**核心差异**:
- 不再是"看新闻"
- 而是"找机会"
- 最终是"做决策"

---

*下一步: 开始 Phase 1 开发，从 scripts/parse_policy.py 入手*
