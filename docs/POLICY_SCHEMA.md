# 政策结构化数据模型 (Policy Schema)
> 版本: v1.0 | 创建: 2026-05-14
> 用途: 政策解析 → 结构化 → 匹配 → 评分全链路

## 核心实体

```yaml
Policy:
  # 基础识别
  id: string              # 政策唯一标识 (hash of url+title)
  title: string          # 政策标题
  url: string             # 原始链接
  source: string          # 来源网站
  source_level:           # 来源级别
    - national           # 国家级
    - provincial         # 省级
    - municipal          # 市级
    - district           # 区级
  
  # 时间窗口
  published_at: datetime  # 发布时间
  deadline: datetime|null # 申报截止时间
  window_days: int        # 窗口剩余天数 (computed)
  
  # 地域信息
  region:                 # 适用地区
    - 全国
    - 上海
    - 青浦
  city: string|null
  
  # 主管部门
  competent_authority:
    - 发改委
    - 经信委
    - 科委
    - 财政局
    - 商务委
  
  # 政策内容
  policy_type:            # 政策类型
    - 专项资金
    - 税收优惠
    - 资质认定
    - 人才计划
    - 揭榜挂帅
    - 政府采购
    - 产业基金
    
  support_direction:      # 支持方向 (关键词)
    - 智慧物流
    - 低空经济
    - AI调度
    - 数字孪生
    - 新质生产力
    
  # 财务信息
  support_amount:          # 支持金额
    min: number|null
    max: number|null
    unit: string          # 万/千万/亿
    is_percentage: bool   # 是否为比例（税收优惠）
    
  # 申报条件
  conditions:
    required_certs:        # 必要资质
      - 高新技术企业
      - 科技型中小企业
      - 专精特新
    required_scale:        # 规模要求
    required_investment:   # 投资要求
    
  # 企业匹配 (computed)
  enterprise_fit:
    score: float           # 匹配度 0-1
    matched_tags: []       # 命中的企业标签
    missing_tags: []       # 缺失的条件
    
  # 政策评分 (computed)
  policy_score:
    final: float           # 综合评分 0-100
    level:                 # S/A/B/C
    dimensions:
      amount_score: float  # 金额规模
      difficulty_score: float # 申报难度
      hit_rate: float     # 命中概率
      region_match: float  # 地域匹配
      industry_match: float # 行业匹配
      urgency: float      # 时间紧迫度
      is_pre_subsidy: bool # 是否后补贴
    
  # 申报建议 (computed)
  recommendation:
    priority:              # P0/P1/P2
    project_names: []      # 建议包装的项目名称
    packaging_keywords: [] # 包装用关键词
    risks: []              # 风险提示
    roi_estimate: float    # ROI估算
    subsidy_type:          # 前补贴/后补贴
```

## 企业画像模板

```yaml
EnterpriseProfile:
  company: string          # 企业名称
  tags:                    # 企业标签
    industry:              # 行业
      - 物流
      - 快递
      - 供应链
    tech:                  # 技术方向
      - AI调度
      - 数字孪生
      - 自动驾驶
      - 低空经济
    region:                # 地域
      - 上海
      - 青浦
      - 长三角
    certs:                 # 已有资质
      - 高新技术企业
      - 科技型中小企业
      - ISO27001
    scale:                 # 规模
      - 员工人数
      - 年营收
      - 研发投入占比
    business:              # 业务关键词
      - 网络货运
      - 智慧物流
      - 无人配送
      - 即时配送

  target_policies:         # 目标政策类型
    - 数字化转型专项资金
    - 高企认定
    - 科小认定
    - 人才引进
```

## 评分维度定义

| 维度 | 权重 | 计算方式 |
|------|------|---------|
| 金额规模 | 20% | max(实际金额/参考基准, 1.0) |
| 申报难度 | 15% | 条件越少分越高 |
| 命中概率 | 25% | 企业标签与政策条件匹配度 |
| 地域匹配 | 15% | 企业所在地vs政策适用地 |
| 行业匹配 | 15% | 企业行业标签命中 |
| 时间紧迫度 | 10% | 窗口期越短分越高 |

## 推荐等级

```yaml
S:  85-100分  强烈推荐，P0优先级
A:  70-84分   建议申报，P1优先级  
B:  50-69分   可选申报，P2优先级
C:  <50分    暂不推荐
```

## 示例输出

```json
{
  "id": "ndrc_2026_567",
  "title": "关于支持现代物流体系建设的通知",
  "source_level": "national",
  "region": ["全国", "上海"],
  "competent_authority": ["发改委"],
  "deadline": "2026-09-30",
  "support_amount": {"min": 300, "max": 500, "unit": "万"},
  "support_direction": ["智慧物流", "数字孪生", "低空经济"],
  "conditions": {
    "required_certs": ["高新技术企业"],
    "required_investment": 1000
  },
  "enterprise_fit": {
    "score": 0.85,
    "matched_tags": ["物流", "AI调度", "上海", "高新技术企业"],
    "missing_tags": []
  },
  "policy_score": {
    "final": 82,
    "level": "A",
    "dimensions": {
      "amount_score": 75,
      "difficulty_score": 65,
      "hit_rate": 85,
      "region_match": 100,
      "industry_match": 90,
      "urgency": 60,
      "is_pre_subsidy": true
    }
  },
  "recommendation": {
    "priority": "P1",
    "project_names": [
      "基于数字孪生的智慧物流调度平台",
      "AI驱动的末端配送优化系统"
    ],
    "packaging_keywords": [
      "现代流通体系",
      "新质生产力",
      "智慧供应链",
      "补链强链"
    ],
    "risks": [
      "需本地部署验收",
      "验收周期6个月"
    ],
    "roi_estimate": 2.5
  }
}
```
