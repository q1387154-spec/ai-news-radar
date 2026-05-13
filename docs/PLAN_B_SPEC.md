# 物流政策情报雷达 · 方案B（政府官网+微信公众号定制版）

> 版本：v1.0 | 创建：2026-05-13

---

## 一、目标

废弃原 AI News Radar 的 AI 新闻抓取逻辑，重新构建**专门针对物流/快递企业的政策情报系统**：

- 数据源：政府官网 + 微信公众号（RSSHub）
- 地域聚焦：青浦区 → 上海市 → 长三角 → 国家
- 内容聚焦：政策申报、补贴、职业技能、低空经济、数字化转型

---

## 二、数据源架构

### 2.1 政府官网（无RSS → Jina Reader）

| 优先级 | 信源 | 抓取方式 | 分类标签 |
|--------|------|---------|---------|
| P0 | shqp.gov.cn（青浦区政府） | Jina Reader | 青浦,补贴,物流 |
| P0 | rsj.sh.gov.cn（上海人社） | Jina Reader | 上海,补贴,职业 |
| P0 | sww.sh.gov.cn（上海商务） | Jina Reader | 上海,物流,补贴 |
| P0 | jtw.sh.gov.cn（上海交通） | Jina Reader | 上海,物流,交通 |
| P0 | stcsm.sh.gov.cn（上海科委） | Jina Reader | 上海,高企,科小 |
| P1 | sheitc.sh.gov.cn（上海经信） | Jina Reader | 上海,数字化,补贴 |
| P1 | shanghai.chinatax.gov.cn（税务） | Jina Reader | 上海,财税,补贴 |
| P1 | fgw.sh.gov.cn（上海发改） | Jina Reader | 上海,物流,仓储 |
| P1 | sh.spb.gov.cn（邮政管理） | Jina Reader | 全国,快递,低空 |
| P2 | www.gov.cn（国务院） | Jina Reader | 国家,政策,物流 |
| P2 | www.spb.gov.cn（国家邮政局） | Jina Reader | 国家,快递,监管 |
| P2 | www.mot.gov.cn（交通部） | Jina Reader | 国家,交通,物流 |
| P2 | www.miit.gov.cn（工信部） | Jina Reader | 国家,数字化,AI |
| P2 | www.ndrc.gov.cn（发改委） | Jina Reader | 国家,投资,物流 |

### 2.2 微信公众号（RSSHub 中转）

通过 RSSHub 将微信公众号转为标准 RSS：

| 公众号 | 内容方向 | RSSHub 路由 |
|--------|---------|------------|
| 上海发布 | 上海市政策公告 | `wechat/mp/wx16a0981d82ea9ed8` |
| 上海经信委 | 产业政策 | `wechat/mp/wx7d4d3c0a70cd9a5e` |
| 上海科委 | 科技创新 | `wechat/mp/wx7dae0e0d0e0b` |
| 上海人社 | 职业补贴 | `wechat/mp/wx1b8aef80d4da8e2a` |
| 青浦发布 | 青浦政策 | `wechat/mp/wx9c60f0e3e9a0e1b` |
| 国家邮政局 | 快递监管 | `wechat/mp/wx4a9d3c5e8f0e1234` |
| 交通运输部 | 交通政策 | `wechat/mp/wx5e0a1b2c3d4f5e6a` |
| 物流沙龙 | 行业媒体 | `wechat/mp/wx6a7b8c9d0e1f2a3b` |

> 需要自建 RSSHub 实例：`docker run -d -p 1200:1200 diygod/rsshub`

### 2.3 低空经济专项（重点关注）

| 政策 | 来源 |
|------|------|
| 《上海市低空经济产业高质量发展行动方案（2024-2027年）》 | sh.spb.gov.cn |
| 《交通物流降本提质增效上海行动计划》 | jtw.sh.gov.cn |
| 《优化提升本市物流仓储设施及服务行动方案（2025-2027年）》 | www.shanghai.gov.cn |

---

## 三、技术架构

### 3.1 抓取流程

```
政府网站列表（YAML/JSON）
    ↓
Jina Reader 批量抓取（无RSS方案）
    ↓
内容解析 + 分类打标
    ↓
RSSHub（微信公众号）
    ↓
内容解析 + 分类打标
    ↓
合并去重 + 按时间排序
    ↓
输出 latest-gov.json
    ↓
GitHub Pages 自动更新
```

### 3.2 分类标签体系

**地域维度**：青浦 | 长三角 | 上海 | 国家

**内容维度**：
- `政策申报` — 高企认定、科小入库、项目申报
- `财税补贴` — 税收优惠、研发加计扣除、专项资金
- `物流科技` — 无人配送、低空经济、数字化转型
- `职业培训` — 职业技能补贴、稳岗培训
- `招聘求职` — 事业单位、国企、社招
- `监管合规` — 快递监管、数据安全、环保

### 3.3 关键文件

```
scripts/
├── fetch_gov.py          # 政府网站抓取（Jina Reader）
├── fetch_wx.py           # 微信公众号抓取（RSSHub）
├── classify.py          # 内容分类打标
└── merge.py             # 合并去重输出

data/
├── latest-gov.json      # 政策情报数据（主要输出）
└── source-status.json   # 信源健康状态
```

---

## 四、前端展示

### 4.1 分类 Tab

`全部 | 政策申报 | 财税补贴 | 物流科技 | 职业培训 | 招聘求职 | 监管合规`

### 4.2 地域筛选

`全部 | 青浦 | 长三角 | 上海 | 国家`

### 4.3 申报日历 Banner

读取 `data/calendar.json`，展示近期申报窗口期。

---

## 五、实施计划

| 阶段 | 内容 | 工期 |
|------|------|------|
| Phase 1 | 搭建 RSSHub 实例，接入微信公众号 | 1天 |
| Phase 2 | 开发 `fetch_gov.py`，抓取 P0 信源 | 1天 |
| Phase 3 | 开发分类打标 + 合并去重 | 1天 |
| Phase 4 | 替换 GitHub Actions workflow | 0.5天 |
| Phase 5 | 前端适配 + 申报日历 | 0.5天 |

**总工期：约4天**

---

## 六、风险与限制

- 政府网站可能屏蔽爬虫 → 使用 Jina Reader（ Headless Browser 模式）
- RSSHub 稳定性依赖微信接口 → 需私有部署监控
- GitHub Actions 超时（60分钟）→ 分批抓取，每批≤10个源
- 部分政府网站有验证码 → 降级处理，记录失败信源
