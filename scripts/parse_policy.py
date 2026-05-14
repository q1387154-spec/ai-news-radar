#!/usr/bin/env python3
"""
政策结构化解析器 (Policy Parser)

功能:
1. 抓取政策全文
2. 使用LLM提取结构化信息
3. 输出Policy标准JSON

用法:
    python scripts/parse_policy.py --url "https://xxx" --title "政策标题"
    python scripts/parse_policy.py --batch data/latest-24h.json
    python scripts/parse_policy.py --test
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import requests
    from bs4 import BeautifulSoup
    import openai
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Run: pip install requests beautifulsoup4 openai")
    sys.exit(1)

# LLM配置 - 使用 Gemini via OpenAI compatible API
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_BASE_URL = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")

# 代理配置
PROXY = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or os.environ.get("HTTPS_PROXY")

# 输出目录
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "policies"
STATUS_FILE = Path(__file__).parent.parent / "data" / "policy-parse-status.json"

UTC = timezone.utc


@dataclass
class PolicySchema:
    """政策结构化数据模型"""
    title: str
    级别: str = "未知"
    地区: list[str] = None
    主管部门: list[str] = None
    发布时间: str = None
    申报截止时间: str = None
    政策类型: str = "未知"
    支持方向: list[str] = None
    支持金额: dict = None
    申报条件: dict = None
    材料要求: list[str] = None
    评审方式: str = None
    是否后补贴: bool = False
    验收要求: str = None
    风险提示: list[str] = None
    政策原文关键词: list[str] = None
    适合申报企业: list[str] = None

    def __post_init__(self):
        if self.地区 is None:
            self.地区 = []
        if self.主管部门 is None:
            self.主管部门 = []
        if self.支持方向 is None:
            self.支持方向 = []
        if self.材料要求 is None:
            self.材料要求 = []
        if self.风险提示 is None:
            self.风险提示 = []
        if self.政策原文关键词 is None:
            self.政策原文关键词 = []
        if self.适合申报企业 is None:
            self.适合申报企业 = []
        if self.支持金额 is None:
            self.支持金额 = {}
        if self.申报条件 is None:
            self.申报条件 = {}

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ParsedPolicy:
    """解析后的政策"""
    id: str
    title: str
    url: str
    source: str
    source_level: str = ""
    published_at: str = ""
    parsed: PolicySchema = None
    raw_content: str = ""
    parsed_at: str = ""
    confidence: float = 0.0
    parse_error: str = None

    def __post_init__(self):
        if self.parsed is None:
            self.parsed = PolicySchema(title=self.title)
        if not self.parsed_at:
            self.parsed_at = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "source_level": self.source_level,
            "published_at": self.published_at,
            "parsed_at": self.parsed_at,
            "confidence": self.confidence,
            "parse_error": self.parse_error,
            **self.parsed.to_dict()
        }


# LLM提取Prompt
POLICY_EXTRACT_PROMPT = """你是一个政策申报专家。从政策原文中提取结构化信息。

## 输出格式 (严格JSON，不要有其他内容):
{
  "title": "政策标题(从原文中提取，不要修改)",
  "级别": "国家级|省级|市级|区县级",
  "地区": ["适用地区列表，如：上海、全国、青浦"],
  "主管部门": ["发改委", "经信委", "科委", "财政局", "人社局"],
  "发布时间": "YYYY-MM-DD",
  "申报截止时间": "YYYY-MM-DD",
  "政策类型": "专项资金|税收优惠|资质认定|人才计划|揭榜挂帅|政府采购|产业基金",
  "支持方向": ["智慧物流", "数字孪生", "AI调度", "低空经济"],
  "支持金额": {"描述": "最高xxx万", "金额": xxx, "单位": "万"},
  "申报条件": {
    "必要资质": ["高新技术企业", "科技型中小企业"],
    "规模要求": "描述或null",
    "投资要求": "描述或null"
  },
  "材料要求": ["项目申报书", "财务报告"],
  "评审方式": "专家评审|材料审核|竞争性分配",
  "是否后补贴": true或false,
  "验收要求": "描述或null",
  "风险提示": ["风险点1", "风险点2"],
  "政策原文关键词": ["新质生产力", "补链强链"],
  "适合申报企业": ["物流企业", "AI企业"]
}

## 注意事项:
1. 如果字段不存在或无法确定，设为null
2. 支持金额：如果说"最高500万"，金额=500；如果说"不超过10%"，金额=10且单位="百分比"
3. 是否后补贴：false=前补贴(立项即给)，true=后补贴(验收后才给)
4. 风险提示要诚实，如实反映政策风险
5. 返回严格JSON，不要有其他内容
"""


def make_policy_id(url: str, title: str) -> str:
    """生成政策唯一ID"""
    key = f"{url.strip().lower()}||{title.strip().lower()}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def clean_policy_html(html: str) -> str:
    """清洗政策页面HTML，提取正文"""
    soup = BeautifulSoup(html, "html.parser")

    # 移除无关区块
    remove_tags = ["header", "footer", "nav", "aside", "script", "style", "noscript"]
    for tag in remove_tags:
        for elem in soup.find_all(tag):
            elem.decompose()

    # 移除常见无关class/id
    remove_selectors = [
        ".sidebar", ".menu", ".toolbar", ".ad", ".advertisement",
        ".related", ".comment", ".share", "#header", "#footer"
    ]
    for selector in remove_selectors:
        for elem in soup.select(selector):
            elem.decompose()

    # 尝试找主内容区
    content_tags = ["article", "main", ".content", ".article-content",
                    ".policy-content", "#article", "#content"]
    content = None
    for tag in content_tags:
        content = soup.select_one(tag)
        if content:
            break

    if not content:
        content = soup.body if soup.body else soup

    # 提取文本
    text = content.get_text(separator="\n", strip=True)

    # 清理空行
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    text = "\n".join(lines)

    # 截取前8000字
    return text[:8000]


def fetch_policy_content(url: str, session: requests.Session = None) -> str:
    """抓取政策页面内容"""
    if session is None:
        session = requests.Session()

    try:
        # 优先尝试Jina Reader (更好的正文提取)
        jina_url = f"https://r.jina.ai/{url}"
        headers = {
            "Accept": "text/plain",
            "X-Timeout": "15",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        }
        resp = session.get(jina_url, timeout=20, headers=headers)

        if resp.status_code == 200 and len(resp.text) > 200:
            return resp.text[:8000]
    except Exception:
        pass

    # 降级：直接抓取
    try:
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        return clean_policy_html(resp.text)
    except Exception as e:
        return f"[抓取失败: {e}]"


def parse_with_llm(content: str, title: str) -> PolicySchema:
    """使用LLM提取结构化信息 - MiniMax版本"""
    import openai

    # MiniMax API配置 (costom2)
    api_key = os.environ.get("MINIMAX_API_KEY") or "sk-d0127b5dd6cff018ed0a0075eab22efe"
    base_url = os.environ.get("MINIMAX_BASE_URL") or "https://v2.aicodee.com/v1"

    try:
        client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url
        )

        response = client.chat.completions.create(
            model="MiniMax-M2.7-highspeed",
            messages=[
                {"role": "system", "content": POLICY_EXTRACT_PROMPT},
                {"role": "user", "content": f"政策标题: {title}\n\n政策内容:\n{content[:6000]}"}
            ],
            temperature=0.1,
            max_tokens=2048
        )

        text = response.choices[0].message.content

        # 提取JSON
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        data = json.loads(text)

        return PolicySchema(
            title=data.get("title", title),
            级别=data.get("级别", "未知"),
            地区=data.get("地区") or [],
            主管部门=data.get("主管部门") or [],
            发布时间=data.get("发布时间"),
            申报截止时间=data.get("申报截止时间"),
            政策类型=data.get("政策类型", "未知"),
            支持方向=data.get("支持方向") or [],
            支持金额=data.get("支持金额"),
            申报条件=data.get("申报条件") or {},
            材料要求=data.get("材料要求") or [],
            评审方式=data.get("评审方式"),
            是否后补贴=data.get("是否后补贴", False),
            验收要求=data.get("验收要求"),
            风险提示=data.get("风险提示") or [],
            政策原文关键词=data.get("政策原文关键词") or [],
            适合申报企业=data.get("适合申报企业") or []
        )

    except Exception as e:
        raise RuntimeError(f"LLM解析失败: {e}")


def assess_confidence(parsed: PolicySchema, raw: str) -> float:
    """评估解析置信度"""
    score = 0.5

    if parsed.title and len(parsed.title) > 5:
        score += 0.1
    if parsed.级别 and parsed.级别 != "未知":
        score += 0.05
    if parsed.申报截止时间:
        score += 0.1
    if parsed.支持金额 and parsed.支持金额.get("金额"):
        score += 0.1
    if parsed.支持方向 and len(parsed.支持方向) > 0:
        score += 0.1
    if len(raw) > 3000:
        score += 0.05

    return min(score, 1.0)


def parse_policy_with_fallback(url: str, title: str, source: str = "",
                               source_level: str = "", published_at: str = "") -> ParsedPolicy:
    """带降级策略的解析"""
    policy_id = make_policy_id(url, title)

    # 1. 抓取内容
    content = fetch_policy_content(url)
    if not content or len(content) < 100:
        return ParsedPolicy(
            id=policy_id,
            title=title,
            url=url,
            source=source,
            source_level=source_level,
            published_at=published_at,
            raw_content=content,
            parse_error="内容抓取失败"
        )

    # 2. LLM解析
    try:
        parsed = parse_with_llm(content, title)
    except Exception as e:
        # 降级：返回最小结构
        return ParsedPolicy(
            id=policy_id,
            title=title,
            url=url,
            source=source,
            source_level=source_level,
            published_at=published_at,
            raw_content=content[:500],
            parsed=PolicySchema(title=title),
            parse_error=f"LLM解析失败: {str(e)}"
        )

    # 3. 置信度
    confidence = assess_confidence(parsed, content)

    return ParsedPolicy(
        id=policy_id,
        title=parsed.title or title,
        url=url,
        source=source,
        source_level=source_level,
        published_at=published_at,
        parsed=parsed,
        raw_content=content[:2000],
        confidence=confidence
    )


def save_parsed_policy(parsed: ParsedPolicy, output_dir: Path = OUTPUT_DIR):
    """保存解析结果"""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{parsed.id}.json"
    path.write_text(json.dumps(parsed.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def update_parse_status(new_entry: dict = None):
    """更新解析状态"""
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)

    status = {"total": 0, "success": 0, "failed": 0, "last_updated": "", "recent": []}
    if STATUS_FILE.exists():
        try:
            status = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    status["last_updated"] = datetime.now(UTC).isoformat()
    status["total"] = status.get("total", 0) + 1

    if new_entry:
        if new_entry.get("success"):
            status["success"] = status.get("success", 0) + 1
        else:
            status["failed"] = status.get("failed", 0) + 1

        status["recent"] = [new_entry] + status.get("recent", [])[:20]

    STATUS_FILE.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def load_policy(policy_id: str) -> dict | None:
    """加载已解析的政策"""
    policy_file = OUTPUT_DIR / f"{policy_id}.json"
    if not policy_file.exists():
        return None
    try:
        return json.loads(policy_file.read_text(encoding="utf-8"))
    except Exception:
        return None


def parse_single(url: str, title: str, source: str = "", source_level: str = "",
                 published_at: str = "") -> ParsedPolicy:
    """解析单个政策"""
    print(f"[解析] {title[:50]}...")
    print(f"       URL: {url}")

    parsed = parse_policy_with_fallback(url, title, source, source_level, published_at)

    if parsed.parse_error:
        print(f"       ❌ 错误: {parsed.parse_error}")
        update_parse_status({
            "title": title[:50],
            "url": url,
            "success": False,
            "error": parsed.parse_error
        })
    else:
        print(f"       ✅ 成功 (置信度: {parsed.confidence:.0%})")
        print(f"       级别: {parsed.parsed.级别}")
        print(f"       地区: {', '.join(parsed.parsed.地区)}")
        if parsed.parsed.支持方向:
            print(f"       方向: {', '.join(parsed.parsed.支持方向[:3])}")
        update_parse_status({
            "title": title[:50],
            "url": url,
            "success": True,
            "confidence": parsed.confidence,
            "level": parsed.parsed.级别
        })

    # 保存
    path = save_parsed_policy(parsed)
    print(f"       保存: {path.name}")

    return parsed


def parse_batch(input_file: str, limit: int = 10):
    """批量解析"""
    input_path = Path(input_file)
    if not input_path.exists():
        print(f"文件不存在: {input_file}")
        return

    data = json.loads(input_path.read_text(encoding="utf-8"))
    items = data.get("items", [])

    print(f"[批量解析] 共 {len(items)} 条政策，限制 {limit} 条")
    print("=" * 60)

    success = 0
    for i, item in enumerate(items[:limit]):
        title = item.get("title", "")
        url = item.get("url", "") or item.get("link", "")
        source = item.get("source", "")
        published = item.get("published", item.get("published_at", ""))

        if not url or not title:
            continue

        print(f"\n[{i+1}/{min(len(items), limit)}]")
        parsed = parse_single(url, title, source, "", published)
        if not parsed.parse_error:
            success += 1

    print("\n" + "=" * 60)
    print(f"[完成] 成功: {success}/{min(len(items), limit)}")


def test_parse():
    """测试解析"""
    print("[测试模式]")
    print("-" * 60)

    # 测试URL
    test_cases = [
        {
            "url": "https://www.ndrc.gov.cn/xxgk/zcfb/tz/202505/t20250512_1435821.html",
            "title": "关于支持现代物流体系建设的通知",
            "source": "国家发改委",
            "source_level": "国家级"
        }
    ]

    for tc in test_cases:
        print(f"\n测试: {tc['title']}")
        parse_single(tc["url"], tc["title"], tc["source"], tc["source_level"])


def main():
    parser = argparse.ArgumentParser(description="政策结构化解析器")
    parser.add_argument("--url", help="政策URL")
    parser.add_argument("--title", help="政策标题")
    parser.add_argument("--source", default="", help="来源")
    parser.add_argument("--source-level", default="", help="来源级别")
    parser.add_argument("--published", default="", help="发布时间")
    parser.add_argument("--batch", help="批量解析JSON文件")
    parser.add_argument("--limit", type=int, default=10, help="批量解析数量限制")
    parser.add_argument("--test", action="store_true", help="运行测试")

    args = parser.parse_args()

    if args.test:
        test_parse()
    elif args.batch:
        parse_batch(args.batch, args.limit)
    elif args.url and args.title:
        parse_single(args.url, args.title, args.source, args.source_level, args.published)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
