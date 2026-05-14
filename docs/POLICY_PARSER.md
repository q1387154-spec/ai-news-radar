# 政策结构化解析器 (Policy Parser)
> 版本: v1.0 | 创建: 2026-05-14
> 核心功能: 政策原文 → LLM结构化提取 → 结构化JSON

---

## 一、解析Pipeline

```
RSS抓取
   ↓
获取政策全文 (HTML/Markdown)
   ↓
内容清洗 (去广告/导航/无关区块)
   ↓
LLM结构化提取 (Prompt Engineering)
   ↓
输出Policy标准JSON
   ↓
向量入库 (语义检索用)
```

---

## 二、LLM提取Prompt

```python
POLICY_EXTRACT_PROMPT = """
你是一个政策申报专家。从政策原文中提取结构化信息。

## 输出格式 (严格JSON):
{
  "title": "政策标题",
  "级别": "国家级|省级|市级|区县级",
  "地区": ["适用地区列表"],
  "主管部门": ["发改委", "经信委", ...],
  "发布时间": "YYYY-MM-DD",
  "申报截止时间": "YYYY-MM-DD|null",
  "政策类型": "专项资金|税收优惠|资质认定|人才计划|揭榜挂帅|政府采购",
  "支持方向": ["智慧物流", "数字孪生", ...],
  "支持金额": {
    "描述": "最高500万",
    "金额": 500,
    "单位": "万"
  },
  "申报条件": {
    "必要资质": ["高新技术企业", ...],
    "规模要求": "描述",
    "投资要求": "描述"
  },
  "材料要求": ["项目申报书", "财务报告", ...],
  "评审方式": "专家评审|材料审核|竞争性分配",
  "是否后补贴": true|false,
  "验收要求": "描述|null",
  "风险提示": ["需本地部署", "验收周期长", ...],
  "政策原文关键词": ["新质生产力", "补链强链", ...],
  "适合申报企业": ["物流企业", "AI企业", ...]
}

## 注意事项:
1. 如果字段不存在，设为null
2. 金额提取数字，估算实际金额
3. 支持方向是政策明确支持的方向
4. 风险提示要诚实，不要美化
5. 返回严格JSON，不要有其他内容
"""

def parse_policy(raw_content: str, title: str) -> dict:
    """使用LLM提取政策结构化信息"""
    response = llm.chat.completions.create(
        model="gemini-2.5-flash",
        messages=[
            {"role": "system", "content": POLICY_EXTRACT_PROMPT},
            {"role": "user", "content": f"政策标题: {title}\n\n政策内容:\n{raw_content[:8000]}"}
        ],
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)
```

---

## 三、内容清洗规则

```python
def clean_policy_html(html: str) -> str:
    """清洗政策页面HTML，提取正文"""
    
    # 1. 移除无关区块
    remove_selectors = [
        "header", "footer", "nav", "aside",  # 导航类
        ".sidebar", ".menu", ".toolbar",      # 工具类
        ".ad", ".advertisement", ".related",  # 广告类
        "#header", "#footer", "#nav",          # 常用ID
    ]
    
    # 2. 保留主内容区
    keep_selectors = [
        "article", "main", ".content", 
        ".article-content", ".policy-content",
        "#article", "#content"
    ]
    
    # 3. 提取正文
    soup = BeautifulSoup(html, "html.parser")
    # ... (清洗逻辑)
    
    # 4. 截取前8000字（LLM上下文限制）
    text = soup.get_text(separator="\n", strip=True)[:8000]
    
    return text
```

---

## 四、解析结果存储

```python
@dataclass
class ParsedPolicy:
    id: str                    # hash(url+title)
    raw_title: str
    parsed: PolicySchema       # 结构化结果
    raw_content: str           # 清洗后原文
    parsed_at: datetime
    confidence: float          # 解析置信度

    def to_json(self) -> dict:
        return {
            "id": self.id,
            **self.parsed.__dict__,
            "url": self.url,
            "parsed_at": self.parsed_at.isoformat(),
            "confidence": self.confidence
        }
    
    def save(self, output_dir: str = "data/policies"):
        path = Path(output_dir) / f"{self.id}.json"
        path.write_text(json.dumps(self.to_json(), ensure_ascii=False, indent=2))
```

---

## 五、错误处理

```python
def parse_with_fallback(raw_content: str, title: str) -> dict:
    """带降级策略的解析"""
    
    # 主策略: LLM提取
    try:
        result = parse_policy(raw_content, title)
        # 验证必填字段
        assert result.get("title") and result.get("级别")
        return result
    except Exception as e:
        logger.warning(f"LLM解析失败: {e}")
    
    # 降级策略1: 规则提取
    try:
        return rule_based_extract(title, raw_content)
    except:
        pass
    
    # 降级策略2: 返回最小结构
    return {
        "title": title,
        "级别": "未知",
        "地区": ["未知"],
        "解析失败": True,
        "原始内容摘要": raw_content[:500]
    }
```

---

## 六、置信度评估

```python
def assess_confidence(parsed: dict, raw: str) -> float:
    """评估解析置信度"""
    score = 0.5  # 基础分
    
    # 有完整标题 +0.1
    if parsed.get("title") and len(parsed["title"]) > 5:
        score += 0.1
    
    # 有级别 +0.05
    if parsed.get("级别"):
        score += 0.05
    
    # 有申报截止时间 +0.1
    if parsed.get("申报截止时间"):
        score += 0.1
    
    # 有支持金额 +0.1
    if parsed.get("支持金额", {}).get("金额"):
        score += 0.1
    
    # 有支持方向 +0.1
    if parsed.get("支持方向") and len(parsed["支持方向"]) > 0:
        score += 0.1
    
    # 内容长度充足 +0.05
    if len(raw) > 3000:
        score += 0.05
    
    return min(score, 1.0)
```

---

## 七、与现有系统的集成

```python
# scripts/update_news.py 改造

def fetch_and_parse_policy(url: str, title: str) -> ParsedPolicy:
    """抓取政策并解析"""
    
    # 1. 抓取全文
    html = fetch_with_jina(url)
    
    # 2. 清洗
    content = clean_policy_html(html)
    
    # 3. LLM解析
    parsed = parse_policy(content, title)
    
    # 4. 置信度
    confidence = assess_confidence(parsed, content)
    
    return ParsedPolicy(
        id=hash_url_title(url, title),
        raw_title=title,
        parsed=parsed,
        raw_content=content[:5000],  # 存摘要
        parsed_at=datetime.now(),
        confidence=confidence
    )

# 在 update_news.py 的 fetch_<source> 函数中集成
```

---

## 八、解析状态追踪

```json
{
  "data/policy-parse-status.json": {
    "total_parsed": 156,
    "avg_confidence": 0.82,
    "by_level": {
      "国家级": 45,
      "省级": 67,
      "市级": 38,
      "区县级": 6
    },
    "last_parsed": "2026-05-14T09:30:00+08:00",
    "failed_urls": [
      {"url": "...", "reason": "页面无法访问"}
    ]
  }
}
```

---

*下一步: 与企业画像系统集成，实现自动匹配*
