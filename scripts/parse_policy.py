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
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

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


def playwright_fetch_content(url: str, timeout: int = 30) -> str:
    """
    使用 Playwright 浏览器抓取页面内容（绕过 Jina 限速）
    无速率限制，适合大规模抓取政府政策页面
    """
    from playwright.sync_api import sync_playwright

    text = f"[Playwright抓取失败: 未知错误]"

    try:
        with sync_playwright() as p:
            # 启动 headless Chrome
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                ignore_https_errors=True
            )
            page = context.new_page()
            page.set_default_timeout(timeout * 1000)

            # 导航 + 等待内容加载
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)

            if response is None or response.status >= 400:
                text = f"[HTTP {response.status if response else 'None'}: {url}]"
            else:
                # 滚动一下触发懒加载内容
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                    page.wait_for_timeout(1000)
                except Exception:
                    pass

                # 提取正文
                content = page.content()
                text = clean_policy_html(content)

            context.close()
            browser.close()

    except Exception as e:
        text = f"[Playwright抓取失败: {e}]"

    return text[:8000]


def fetch_policy_content(url: str, session: requests.Session = None) -> str:
    """
    抓取政策页面内容，优先使用 Playwright 浏览器（无速率限制）
    降级使用直接 requests 抓取
    """
    # 优先：Playwright 浏览器抓取（无速率限制）
    try:
        content = playwright_fetch_content(url)
        if content and len(content) > 200 and "抓取失败" not in content:
            return content
    except Exception:
        pass

    # 降级：直接 requests 抓取
    if session is None:
        session = requests.Session()
        retry = Retry(total=2, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('http://', adapter)
        session.mount('https://', adapter)

    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        return clean_policy_html(resp.text)
    except Exception as e:
        return f"[抓取失败: {e}]"


def _call_openai_compatible(client: openai.OpenAI, model: str, messages: list,
                              temperature: float = 0.1, max_tokens: int = 2048) -> str:
    """调用 OpenAI 兼容接口，返回文本或抛出异常"""
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens
    )
    return response.choices[0].message.content


def _is_retriable_error(e: Exception) -> bool:
    """判断错误是否值得重试（配额不足/限速/服务器错误）"""
    msg = str(e).lower()
    # 403: 配额耗尽 / 429: 速率限制 / 5xx: 服务器错误
    retriable_codes = [403, 429, 500, 502, 503, 504]
    retriable_keywords = [
        "quota", "rate limit", "insufficient_user_quota",
        "429", "rate_limit", "too many requests",
        "500", "502", "503", "service unavailable", "gateway error",
        "403", "额度", "配额", "limit exceeded"
    ]
    for code in retriable_codes:
        if str(code) in msg:
            return True
    for kw in retriable_keywords:
        if kw.lower() in msg:
            return True
    return False


def _build_client(api_key: str, base_url: str, timeout: int = 60):
    """构建 OpenAI 兼容客户端"""
    import openai as _openai
    return _openai.OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=0  # 我们自己在模型层面重试
    )


def parse_with_llm(content: str, title: str) -> PolicySchema:
    """
    使用 LLM 提取结构化信息，带多级模型降级。

    降级顺序 (自动切换):
      1. MiniMax costom1  (primary)
      2. MiniMax costom2  (first fallback)
      3. Gemini 2.5 Flash (second fallback, via Google API)
    """
    import openai as _openai

    # ── 模型配置 ──────────────────────────────────────────────
    # Primary: costom1 MiniMax
    PRIMARY_KEY = os.environ.get("MINIMAX_API_KEY") or "sk-d0127b5dd6cff018ed0a0075eab22efe"
    PRIMARY_URL = os.environ.get("MINIMAX_BASE_URL") or "https://v2.aicodee.com/v1"
    PRIMARY_MODEL = "MiniMax-M2.7-highspeed"

    # Fallback 1: costom2 MiniMax (独立配额)
    COSTOM2_KEY = os.environ.get("MINIMAX_API_KEY_2") or ""
    COSTOM2_URL = PRIMARY_URL  # 同一家代理商
    COSTOM2_MODEL = "MiniMax-M2.7-highspeed"

    # Fallback 2: Gemini 2.5 Flash (Google OpenAI-compatible endpoint)
    # 端点: https://generativelanguage.googleapis.com/v1beta/openai/chat/completions
    GEMINI_KEY = os.environ.get("GEMINI_API_KEY") or ""
    GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
    GEMINI_MODEL = "gemini-2.5-flash"
    GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta"
    GEMINI_MODEL = "gemini-2.0-flash-exp"

    # Fallback 2: MiniMax-Alt (costom1)
    ALT_KEY = os.environ.get("MINIMAX_API_KEY_2") or "sk-xxxx-alt"  # 需用户配置
    ALT_URL = "https://v2.aicodee.com/v1"
    ALT_MODEL = "MiniMax-M2.7-highspeed"

    # ── Prompt ─────────────────────────────────────────────────
    system_prompt = POLICY_EXTRACT_PROMPT
    user_prompt = f"政策标题: {title}\n\n政策内容:\n{content[:6000]}"
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    # ── 尝试各模型 ───────────────────────────────────────────
    last_error = None

    candidates = [
        (PRIMARY_KEY,  PRIMARY_URL,  PRIMARY_MODEL,  "MiniMax(costom1)"),
        (COSTOM2_KEY,  COSTOM2_URL,  COSTOM2_MODEL, "MiniMax(costom2)"),
        (GEMINI_KEY,  GEMINI_URL,  GEMINI_MODEL,  "Gemini-2.5-Flash"),
    ]

    for api_key, base_url, model, model_name in candidates:
        if not api_key or api_key.startswith("sk-xxxx"):
            continue  # 跳过未配置的备用 key

        try:
            client = _build_client(api_key, base_url)
            raw_text = _call_openai_compatible(client, model, messages)
            # 成功 → 解析 JSON
            text = raw_text.strip()
            if text.startswith("```json"):
                text = text[7:]
            elif text.startswith("```"):
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

        except _openai.APIError as e:
            # 401/403/404: 认证/配额问题，不重试当前模型，尝试下一个
            if e.status_code in (401, 403, 404):
                last_error = RuntimeError(f"[{model_name}] 认证/配额错误 ({e.status_code}): {e}")
                continue
            elif e.status_code in (429, 500, 502, 503, 504):
                last_error = RuntimeError(f"[{model_name}] 可重试错误 ({e.status_code}): {e}")
                continue
            else:
                last_error = RuntimeError(f"[{model_name}] API错误 ({e.status_code}): {e}")
                continue

        except Exception as e:
            if _is_retriable_error(e):
                last_error = RuntimeError(f"[{model_name}] 可重试: {e}")
                continue
            else:
                # 不可重试的错误（JSON解析失败等），直接抛出
                raise RuntimeError(f"[{model_name}] 解析失败: {e}")

    # 所有模型都失败
    raise RuntimeError(f"所有模型均失败: {last_error}")


# ── 关键词解析器（替代 LLM） ─────────────────────────────────────

LEVEL_URL_PATTERNS = [
    (r"ndrc\.gov\.cn|mof\.gov\.cn|miit\.gov\.cn|mot\.gov\.cn|most\.gov\.cn|caac\.gov\.cn|spb\.gov\.cn|nda\.gov\.cn|mohrss\.gov\.cn", "国家级"),
    (r"sh\.gov\.cn|sww\.sh\.gov\.cn|rsj\.sh\.gov\.cn|stcsm\.sh\.gov\.cn|jtw\.sh\.gov\.cn|fgw\.sh\.gov\.cn|sheitc\.sh\.gov\.cn", "上海市级"),
    (r"shqp\.gov\.cn", "青浦区级"),
]
DEPT_PATTERNS = [
    (r"发展改革委|发改委", ["发改委"]),
    (r"经济和信息化委员会|经信委|经信局", ["经信委"]),
    (r"科学技术委员会|科委|科技局", ["科委"]),
    (r"财政局|财政厅", ["财政局"]),
    (r"人力资源和社会保障局|人社局|人社厅", ["人社局"]),
    (r"商务委员会|商务委|商委", ["商务委"]),
    (r"交通委员会|交通委|交通局", ["交通委"]),
]
SUPPORT_DIRECTION_PATTERNS = [
    (r"数字化|数智化|数字经济|数字化转型", ["数字化转型"]),
    (r"低空经济|无人机|eVTOL|飞行汽车|空域改革|通航", ["低空经济"]),
    (r"智慧物流|智能物流|现代物流|物流配送|无人配送", ["智慧物流"]),
    (r"人工智能|AI|大模型|机器学习|智能调度", ["人工智能"]),
    (r"专精特新|中小企业", ["专精特新"]),
    (r"冷链|冷库|冷藏", ["冷链物流"]),
    (r"供应链|供应链数字化|产业链", ["供应链"]),
    (r"技术改造|设备更新|机器换人", ["技术改造"]),
    (r"高新技术企业|高新企业|高企", ["高企认定"]),
    (r"科技型中小企业|科小", ["科技型中小企业"]),
    (r"职业技能|技能培训|人才培训", ["职业培训"]),
    (r"稳岗|就业见习|见习补贴", ["稳岗就业"]),
]
POLICY_TYPE_PATTERNS = [
    (r"专项资金|重点支持项目|财政补贴", "专项资金"),
    (r"税收优惠|增值税|所得税|加计扣除", "税收优惠"),
    (r"资质认定|高企认定|科技型中小企业认定|专精特新", "资质认定"),
    (r"人才计划|人才引进|人才培养|博士后", "人才计划"),
    (r"揭榜挂帅|技术攻关|科技重大专项", "揭榜挂帅"),
    (r"政府采购", "政府采购"),
    (r"产业基金|投资基金|股权投资", "产业基金"),
    (r"贷款贴息|融资担保|信贷支持", "贷款贴息"),
]
MATERIAL_PATTERNS = [
    r"项目申报书|申报书", r"营业执照|企业法人营业执照",
    r"财务报告|财务报表|审计报告|年度审计",
    r"项目可行性研究报告|可研报告",
    r"知识产权|专利、软件著作权",
    r"社保缴纳|社保证明", r"纳税证明|完税证明",
    r"法人代表|法定代表人", r"申报承诺函|诚信承诺",
]
CONDITION_PATTERNS = [
    (r"高新技术企业|高新企业|高企认定", "必要资质: 高新技术企业"),
    (r"科技型中小企业|科小企业", "必要资质: 科技型中小企业"),
    (r"注册时间|成立时间|注册年限", "注册时间要求"),
    (r"营业收入|年销售额|营收规模", "营收规模要求"),
    (r"研发投入|研发费用|RD", "研发投入要求"),
    (r"参保人数|员工规模", "人员规模要求"),
    (r"在本区注册|注册地|纳税地", "注册地要求"),
    (r"无不良信用|信用记录", "信用要求"),
    (r"未享受过|不得申报|有以下情形", "排除条件"),
]
REVIEW_PATTERNS = [
    (r"专家评审|专家论证", "专家评审"),
    (r"材料审核|书面审查", "材料审核"),
    (r"竞争性分配|竞争立项", "竞争性分配"),
    (r"先建后补|事后补贴|验收后补", "后补贴"),
    (r"先补后建|事前补贴|立项即补", "前补贴"),
]
DATE_PATTERNS = [r"(\d{4})年(\d{1,2})月(\d{1,2})日", r"(\d{4})-(\d{1,2})-(\d{1,2})", r"(\d{4})/(\d{1,2})/(\d{1,2})"]
AMOUNT_PATTERNS = [
    r"最高(?:资助|补贴|支持|奖励)?(?:达)?([\d,，.]+)\s*(万|万元)",
    r"(?:资助|补贴|支持|奖励)(?:达)?([\d,，.]+)\s*(万|万元)",
    r"金额(?:不高于|不超过|最高)?(?:达)?([\d,，.]+)\s*(万|万元)",
]

def _extract_date(text: str) -> Optional[str]:
    lines = text.split("\n")
    for line in lines:
        s = line.strip()
        if not any(kw in s for kw in ["截止", "申报截止", "受理截止", "截止日期", "申报期限", "在线提交截止"]):
            continue
        for pat in DATE_PATTERNS:
            m = re.search(pat, s)
            if m:
                y, mo, d = m.group(1), m.group(2), m.group(3)
                if 2018 <= int(y) <= 2030 and 1 <= int(mo) <= 12 and 1 <= int(d) <= 31:
                    return f"{y}-{int(mo):02d}-{int(d):02d}"
    for line in lines[:30]:
        s = line.strip()
        if "发布时间" in s or "发布日期" in s:
            for pat in DATE_PATTERNS:
                m = re.search(pat, s)
                if m:
                    y, mo, d = m.group(1), m.group(2), m.group(3)
                    if 2018 <= int(y) <= 2030 and 1 <= int(mo) <= 12 and 1 <= int(d) <= 31:
                        return f"{y}-{int(mo):02d}-{int(d):02d}"
    return None

def _extract_amount(text: str) -> dict:
    for pat in AMOUNT_PATTERNS:
        m = re.search(pat, text)
        if m:
            s = m.group(1).replace(",", "").replace("，", "")
            try:
                return {"描述": f"最高{s}{m.group(2)}", "金额": float(s), "单位": m.group(2)}
            except ValueError:
                pass
    return {}

def _extract_list(text: str, patterns: list) -> list:
    found = set()
    for pat, label in patterns:
        if re.search(pat, text):
            if isinstance(label, list):
                found.update(label)
            else:
                found.add(label)
    return list(found)

def _extract_single(text: str, patterns: list) -> str:
    for pat, label in patterns:
        if re.search(pat, text):
            return label
    return "未知"

def _extract_materials(text: str) -> list:
    found = [m.group(0) for pat in MATERIAL_PATTERNS if (m := re.search(pat, text))]
    return list(set(found))[:6]

def _extract_conditions(text: str) -> dict:
    result = {}
    for pat, label in CONDITION_PATTERNS:
        if re.search(pat, text):
            if "必要资质" in label:
                result.setdefault("必要资质", []).append(label.split(": ")[1])
            else:
                result[label] = "有要求（见原文）"
    if "必要资质" in result:
        result["必要资质"] = list(set(result["必要资质"]))
    return result

def _is_post_subsidy(text: str) -> bool:
    if re.search(r"验收后|后补贴|事后补贴|先建后补|完成后补贴|验收合格后", text):
        return True
    if re.search(r"立项即补|事前补贴|先补后建|立项后即拨付", text):
        return False
    return False

def _extract_level_from_url(url: str, text: str) -> str:
    for pat, level in LEVEL_URL_PATTERNS:
        if re.search(pat, url, re.IGNORECASE):
            return level
    return _extract_single(text, [
        (r"国家级|国家政策|国务院|部委文件", "国家级"),
        (r"上海市|上海市级|市政府文件", "上海市级"),
        (r"青浦区|青浦区区级", "青浦区级"),
    ])

def _extract_regions(text: str) -> list:
    regions = []
    for pat, labels in [
        (r"全国|国家|国务院各部委", ["全国"]),
        (r"上海|上海市", ["上海"]),
        (r"青浦|青浦区", ["青浦"]),
        (r"长三角|长三角一体化", ["长三角"]),
    ]:
        if re.search(pat, text):
            regions.extend(labels)
    return list(set(regions)) if regions else ["上海"]

def _extract_published_date(text: str) -> Optional[str]:
    for line in text.split("\n")[:30]:
        for kw in ["发布时间", "发布日期", "发文日期", "公布日期"]:
            if kw in line:
                date = _extract_date(line)
                if date:
                    return date
    return None

def _extract_risk_hints(text: str) -> list:
    risks = []
    for pat, hint in [
        (r"仅限国有企业|国有独资", "仅限国有企业，中通吉不符合"),
        (r"仅限外资企业|外商投资企业", "仅限外资企业，中通吉不符合"),
        (r"需各区推荐|各区名额分配", "需区政府推荐，需确认青浦区名额"),
        (r"已获同类补贴|不得重复申报", "已获同类补贴不得重复申报"),
        (r"须通过.*验收|验收不合格", "需通过验收，存在验收不通过风险"),
        (r"中小微企业", "针对中小微企业，中通吉规模可能超标"),
    ]:
        if re.search(pat, text):
            risks.append(hint)
    return list(set(risks))

def parse_with_keywords(content: str, title: str, url: str = "") -> PolicySchema:
    level = _extract_level_from_url(url, content)
    regions = _extract_regions(content)
    depts = _extract_list(content, DEPT_PATTERNS)
    support_directions = _extract_list(content, SUPPORT_DIRECTION_PATTERNS)
    policy_type = _extract_single(content, POLICY_TYPE_PATTERNS)
    deadline = _extract_date(content)
    published = _extract_published_date(content)
    amount = _extract_amount(content)
    materials = _extract_materials(content)
    conditions = _extract_conditions(content)
    review = _extract_single(content, REVIEW_PATTERNS)
    is_post = _is_post_subsidy(content)
    risks = _extract_risk_hints(content)
    kw_text = (title + " " + content[:500]).lower()
    policy_kw = [label for pat, label in [
        (r"新质生产力", "新质生产力"), (r"数字化转型", "数字化转型"),
        (r"低空经济", "低空经济"), (r"智能制造", "智能制造"),
        (r"碳达峰|碳中和", "绿色低碳"), (r"补链强链", "产业链协同"),
    ] if re.search(pat, kw_text)]
    suitable = []
    if support_directions:
        suitable.append("物流/快递企业")
    if re.search(r"AI|人工智能|数字化", content):
        suitable.append("科技/数字化企业")
    if re.search(r"高新技术|科技型", content):
        suitable.append("高新技术企业/科技型中小企业")
    return PolicySchema(
        title=title, 级别=level, 地区=regions, 主管部门=depts,
        发布时间=published, 申报截止时间=deadline, 政策类型=policy_type,
        支持方向=support_directions, 支持金额=amount, 申报条件=conditions,
        材料要求=materials, 评审方式=review, 是否后补贴=is_post,
        验收要求="见原文" if re.search(r"验收|绩效评价|考核", content) else None,
        风险提示=risks, 政策原文关键词=policy_kw,
        适合申报企业=suitable or ["符合支持方向的企业"]
    )

def assess_confidence(parsed: PolicySchema, raw: str) -> float:
    score = 0.6
    if parsed.title and len(parsed.title) > 5: score += 0.05
    if parsed.级别 and parsed.级别 != "未知": score += 0.05
    if parsed.申报截止时间: score += 0.1
    if parsed.支持金额 and parsed.支持金额.get("金额"): score += 0.1
    if parsed.支持方向 and len(parsed.支持方向) > 0: score += 0.1
    if len(raw) > 3000: score += 0.05
    return min(score, 1.0)

# ── LLM 解析（保留，降级用）──


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

    # 2. 关键词解析（无LLM调用，秒级完成）
    try:
        parsed = parse_with_keywords(content, title, url)
    except Exception as e:
        return ParsedPolicy(
            id=policy_id,
            title=title,
            url=url,
            source=source,
            source_level=source_level,
            published_at=published_at,
            raw_content=content[:500],
            parsed=PolicySchema(title=title),
            parse_error=f"关键词解析失败: {str(e)}"
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
