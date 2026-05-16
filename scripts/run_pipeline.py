#!/usr/bin/env python3
"""
政策处理主管道 (Policy Pipeline)

功能:
1. 抓取政策RSS
2. 解析政策全文 (LLM)
3. 企业匹配
4. 政策评分
5. 风险过滤
6. 生成申报建议

用法:
    python scripts/run_pipeline.py --fetch-only
    python scripts/run_pipeline.py --parse-only
    python scripts/run_pipeline.py --full
    python scripts/run_pipeline.py --test
"""

from __future__ import annotations

import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import argparse
import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── 从 OpenClaw config 注入 API keys ──────────────────────────
def _load_openclaw_keys():
    """从 openclaw.json 读取各 provider 的 API key 并注入环境变量"""
    import json as _json
    cfg_path = Path.home() / ".openclaw" / "openclaw.json"
    if not cfg_path.exists():
        return
    try:
        cfg = _json.loads(cfg_path.read_text(encoding="utf-8"))
        providers = cfg.get("models", {}).get("providers", {})
        # costom1 → MINIMAX_API_KEY
        c1 = providers.get("costom1", {})
        if c1.get("apiKey"):
            os.environ.setdefault("MINIMAX_API_KEY", c1["apiKey"])
            os.environ.setdefault("MINIMAX_BASE_URL", c1.get("baseUrl", "https://v2.aicodee.com/v1"))
        # costom2 → MINIMAX_API_KEY_2
        c2 = providers.get("costom2", {})
        if c2.get("apiKey"):
            os.environ.setdefault("MINIMAX_API_KEY_2", c2["apiKey"])
        # google (Gemini) → GEMINI_API_KEY
        google = providers.get("google", {})
        if google.get("apiKey"):
            os.environ.setdefault("GEMINI_API_KEY", google["apiKey"])
            os.environ.setdefault("GEMINI_BASE_URL", google.get("baseUrl", "https://generativelanguage.googleapis.com/v1beta"))
    except Exception:
        pass

_load_openclaw_keys()
# ────────────────────────────────────────────────────────────────

# 导入各模块
from scripts.parse_policy import (
    parse_single, load_policy,
    save_parsed_policy, OUTPUT_DIR as POLICIES_DIR
)
from scripts.match_policy import (
    PolicyMatcher, load_enterprise_profile, MATCH_HISTORY_FILE
)
from scripts.score_policy import PolicyScorer, SCORE_HISTORY_FILE
from scripts.risk_filter import PolicyRiskFilter, RISK_HISTORY_FILE

UTC = timezone.utc

# 数据目录
DATA_DIR = Path(__file__).parent.parent / "data"
RSS_DIR = DATA_DIR / "rss_cache"
FINAL_OUTPUT = DATA_DIR / "policy-opportunities.json"


@dataclass
class PolicyOpportunity:
    """政策机会最终输出"""
    id: str
    title: str
    url: str
    source: str
    source_level: str
    published_at: str
    deadline: str
    days_left: int

    # 解析结果
    parsed: dict

    # 匹配结果
    match_score: float
    matched_tags: list
    missing_tags: list

    # 评分结果
    score: float
    level: str
    priority: str
    dimensions: dict
    is_pre_subsidy: bool

    # 风险结果
    risk_level: str
    risk_score: float
    risk_advice: str
    is_worth_applying: bool

    # ROI
    roi: dict

    # 申报建议
    recommended_project: str
    packaging_keywords: list
    reasons: list
    warnings: list

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "source_level": self.source_level,
            "published_at": self.published_at,
            "deadline": self.deadline,
            "days_left": self.days_left,
            "match_score": self.match_score,
            "matched_tags": self.matched_tags,
            "missing_tags": self.missing_tags,
            "score": self.score,
            "level": self.level,
            "priority": self.priority,
            "is_pre_subsidy": self.is_pre_subsidy,
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "risk_advice": self.risk_advice,
            "is_worth_applying": self.is_worth_applying,
            "roi": self.roi,
            "recommended_project": self.recommended_project,
            "packaging_keywords": self.packaging_keywords,
            "reasons": self.reasons,
            "warnings": self.warnings
        }


def _fetch_gov_opml_pages(limit: int = 100) -> list:
    """
    直接从 gov.opml 页面抓取政策列表链接（绕过失效RSS）
    使用 Playwright 浏览器抓取，无速率限制
    """
    import xml.etree.ElementTree as ET
    import re
    from playwright.sync_api import sync_playwright

    HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    POLICY_KW = ["通知", "公告", "意见", "办法", "指南", "公示",
                "决定", "方案", "政策", "解读", "批复", "纲要", "规划", "条例"]

    opml_path = Path(__file__).parent.parent / "feeds" / "gov.opml"
    if not opml_path.exists():
        print(f"  gov.opml 不存在，跳过")
        return []

    tree = ET.parse(opml_path)
    items = []

    for outline in tree.getroot().iter("outline"):
        html_url = outline.get("htmlUrl") or outline.get("xmlUrl")
        title = outline.get("title", "")
        category = outline.get("category", "")
        priority = outline.get("priority", "P0")
        level = outline.get("level", "P0")

        if not html_url:
            continue

        print(f"  抓取 {title[:20]}... ", end="", flush=True)

        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin

            page_html = _playwright_fetch_page(html_url)

            # 提取 HTML 中的链接
            found = 0
            soup = BeautifulSoup(page_html, "html.parser")
            for a in soup.find_all("a", href=True):
                link_title = a.get_text(strip=True)
                link_url = urljoin(html_url, a["href"])
                if not link_title or len(link_title) < 5:
                    continue
                if not any(kw in link_title for kw in POLICY_KW):
                    continue
                items.append({
                    "title": link_title.strip(),
                    "url": link_url.strip(),
                    "source": title,
                    "category": category,
                    "priority": priority,
                    "level": level,
                    "published": "",
                })
                found += 1

            print(f"获取 {found} 条")

        except Exception as e:
            print(f"⚠️ {str(e)[:30]}")
            continue

        if len(items) >= limit:
            break

    return items[:limit]


def _playwright_fetch_page(url: str, timeout: int = 35) -> str:
    """
    Playwright 抓取单个页面，返回 HTML 内容（支持 JS 渲染和 tab 点击）
    """
    from bs4 import BeautifulSoup
    from playwright.sync_api import sync_playwright

    html_content = ""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                ignore_https_errors=True
            )
            page = context.new_page()
            page.set_default_timeout(timeout * 1000)

            # 快速导航（不等待load事件，避免JS重页面卡住）
            page.goto(url, wait_until="commit", timeout=timeout * 1000)
            page.wait_for_timeout(4000)  # 等待JS初始化

            # 尝试点击通知/公告tab
            tab_keywords = ["通知公告", "公示公告", "公告列表", "tzgg", "tz", "gsgg", "政策文件"]
            for pattern in tab_keywords:
                try:
                    clicked = page.evaluate(f"""
                        () => {{
                            const els = Array.from(document.querySelectorAll('a, button, [onclick], [data-tab], li'));
                            for (const el of els) {{
                                const text = (el.innerText || el.textContent || '').trim();
                                const href = el.href || '';
                                if (text.includes('{pattern}') || href.includes('{pattern}')) {{
                                    if (el.click) {{ el.click(); return true; }}
                                }}
                            }}
                            return false;
                        }}
                    """)
                    if clicked:
                        page.wait_for_timeout(2500)
                        break
                except Exception:
                    pass

            # 滚动触发懒加载
            for _ in range(6):
                page.evaluate("window.scrollBy(0, 600)")
                page.wait_for_timeout(800)

            html_content = page.content()
            context.close()
            browser.close()
    except Exception as e:
        html_content = f"[Playwright error: {e}]"
    return html_content

def parse_rss_feeds(opml_file: str = None, limit: int = 100) -> list:
    """抓取政策源（RSS → gov-fetched.json → gov.opml直抓）"""
    try:
        import feedparser
    except ImportError:
        print("需要安装 feedparser: pip install feedparser")
        return []

    # 尝试 policy.opml RSS 源
    if opml_file is None:
        opml_file = Path(__file__).parent.parent / "feeds" / "policy.example.opml"

    opml_path = Path(opml_file)
    if not opml_path.exists():
        print(f"OPML文件不存在: {opml_file}")
    else:
        import xml.etree.ElementTree as ET
        tree = ET.parse(opml_path)
        root = tree.getroot()

        items = []
        for outline in root.iter("outline"):
            xml_url = outline.get("xmlUrl") or outline.get("xml_url")
            title = outline.get("title", "")
            html_url = outline.get("htmlUrl", "")
            category = outline.get("category", "")
            priority = outline.get("priority", "P1")

            if not xml_url:
                continue

            try:
                feed = feedparser.parse(xml_url)
                for entry in feed.entries[:limit]:
                    item = {
                        "title": entry.get("title", ""),
                        "url": entry.get("link", ""),
                        "source": title,
                        "category": category,
                        "priority": priority,
                        "published": entry.get("published", "")
                    }
                    items.append(item)
            except Exception as e:
                print(f"  ⚠️ 抓取失败 {title}: {e}")
                continue

        if items:
            print(f"  从policy.opml RSS获取 {len(items)} 条")
            return items[:limit]

    # 优先尝试 gov.opml 直抓（政府HTML页面 → 提取政策链接）
    print("  尝试从gov.opml直接抓取政府网站...")
    items = _fetch_gov_opml_pages(limit=limit)
    if items:
        print(f"  从gov.opml直抓获取 {len(items)} 条")
        return items[:limit]

    # 尝试 gov-fetched.json 兜底
    print("  尝试从gov-fetched.json兜底...")
    gov_file = Path(__file__).parent.parent / "data" / "gov-fetched.json"
    if not gov_file.exists():
        gov_file = Path(__file__).parent.parent / "data" / "latest-gov.json"
    if gov_file.exists():
        import json as _json
        data = _json.loads(gov_file.read_text(encoding="utf-8"))
        gov_items = data.get("items", []) if isinstance(data, dict) else data
        if gov_items:
            items = [{
                "title": it.get("title", ""),
                "url": it.get("url", ""),
                "source": it.get("source", "政府网站"),
                "category": it.get("category", ""),
                "priority": it.get("priority", "P0"),
                "published": it.get("published_at", "") or it.get("published", "")
            } for it in gov_items[:limit]]
            print(f"  从{gov_file.name}加载 {len(items)} 条")
            return items

    # 尝试 policy.opml RSS
    print("  尝试policy.opml RSS...")


def process_policy(item: dict, profile) -> Optional[PolicyOpportunity]:
    """处理单个政策"""

    url = item.get("url", "")
    title = item.get("title", "")
    source = item.get("source", "")

    if not url or not title:
        return None

    print(f"\n[处理] {title[:50]}...")

    # 1. 解析政策
    parsed = parse_single(
        url=url,
        title=title,
        source=source,
        source_level=item.get("priority", ""),
        published_at=item.get("published", "")
    )

    if parsed.parse_error:
        print(f"  ❌ 解析失败，跳过")
        return None

    # 1.5 负面过滤：跳过与中通吉完全不相关的政策
    if parsed.parsed.支持方向 and "已过滤" in parsed.parsed.支持方向:
        reason = parsed.parsed.风险提示[0] if parsed.parsed.风险提示 else "不相关"
        print(f"  ⛔ 过滤（{reason}），跳过")
        return None

    matcher = PolicyMatcher(profile)
    match_result = matcher.match(parsed.to_dict())

    # 3. 政策评分
    scorer = PolicyScorer()
    score_result = scorer.score(
        parsed.to_dict(),
        match_result.total_score,
        match_result.matched_tags,
        match_result.missing_tags
    )

    # 4. 风险过滤
    risk_filter = PolicyRiskFilter()
    risk_result = risk_filter.filter(parsed.to_dict(), profile.__dict__)

    # 5. 生成申报建议
    project_name = _generate_project_name(parsed, profile)
    keywords = _generate_packaging_keywords(parsed, profile)

    # 计算剩余天数
    days_left = 0
    deadline = parsed.parsed.申报截止时间
    if deadline:
        try:
            from datetime import datetime
            deadline_dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
            days_left = (deadline_dt - datetime.now(UTC)).days
        except Exception:
            pass

    return PolicyOpportunity(
        id=parsed.id,
        title=parsed.title,
        url=url,
        source=source,
        source_level=parsed.source_level or parsed.parsed.级别,
        published_at=parsed.published_at,
        deadline=deadline or "",
        days_left=days_left,
        parsed=parsed.parsed.to_dict(),
        match_score=match_result.total_score,
        matched_tags=match_result.matched_tags,
        missing_tags=match_result.missing_tags,
        score=score_result.final,
        level=score_result.level,
        priority=score_result.priority,
        dimensions=score_result.dimensions,
        is_pre_subsidy=score_result.is_pre_subsidy,
        risk_level=risk_result.risk_level,
        risk_score=risk_result.risk_score,
        risk_advice=risk_result.advice,
        is_worth_applying=risk_result.is_worth_applying and score_result.final >= 50,
        roi=score_result.roi,
        recommended_project=project_name,
        packaging_keywords=keywords,
        reasons=score_result.reasons,
        warnings=score_result.warnings + [r["risk_point"] for r in risk_result.detailed_risks]
    )


def _generate_project_name(parsed, profile) -> str:
    """生成建议项目名称"""
    schema = parsed.parsed if hasattr(parsed, 'parsed') else parsed
    支持方向 = getattr(schema, '支持方向', []) or []
    政策关键词 = getattr(schema, '政策原文关键词', []) or []
    for project in profile.key_projects:
        project_keywords = project.get("keywords", [])
        for kw in project_keywords:
            if kw in str(支持方向) or kw in str(政策关键词):
                return project["name"]

    # 默认包装
    directions = 支持方向[:2] if 支持方向 else []
    if directions:
        return f"{directions[0]}示范项目"
    return "智慧物流建设项目"


def _generate_packaging_keywords(parsed, profile) -> list:
    """生成包装关键词"""
    schema = parsed.parsed if hasattr(parsed, 'parsed') else parsed
    keywords = []

    # 从政策支持方向提取
    for kw in getattr(schema, '支持方向', []) or []:
        keywords.append(kw)

    # 添加热点关键词
    hot_keywords = ["新质生产力", "补链强链", "数字化转型", "智慧物流"]
    for kw in hot_keywords:
        if kw not in keywords:
            keywords.append(kw)

    return keywords[:8]


def run_pipeline(limit: int = 20, only_new: bool = True):
    """运行完整管道"""

    print("=" * 60)
    print("政策处理管道启动")
    print("=" * 60)

    # 1. 加载企业画像
    print("\n[1/5] 加载企业画像...")
    profile = load_enterprise_profile("ztj")
    print(f"  企业: {profile.name}")

    # 2. 抓取RSS
    print("\n[2/5] 抓取政策RSS...")
    items = parse_rss_feeds(limit=limit)
    print(f"  获取 {len(items)} 条政策")

    if not items:
        print("  ⚠️ 未获取到政策，请检查RSS源配置")
        return

    # 3. 解析+匹配+评分+过滤
    print("\n[3/5] 处理政策...")
    opportunities = []
    for i, item in enumerate(items):
        print(f"\n[{i+1}/{len(items)}]")
        opp = process_policy(item, profile)
        if opp:
            opportunities.append(opp)
            print(f"  ✅ {opp.level}级 {opp.score:.1f}分 P{opp.priority[-1]}")

    if not opportunities:
        print("\n⚠️ 没有生成有效政策机会")
        return

    # 4. 过滤不值得申报的
    print("\n[4/5] 过滤风险...")
    before_count = len(opportunities)
    opportunities = [o for o in opportunities if o.is_worth_applying]
    print(f"  过滤后: {len(opportunities)}/{before_count} 条值得申报")

    # 5. 排序+输出
    print("\n[5/5] 生成最终报告...")
    opportunities.sort(key=lambda x: (x.score, x.match_score), reverse=True)

    output = {
        "generated_at": datetime.now(UTC).isoformat(),
        "total": len(opportunities),
        "high_priority": len([o for o in opportunities if o.priority in ["P0", "P1"]]),
        "by_level": {
            "S": len([o for o in opportunities if o.level == "S"]),
            "A": len([o for o in opportunities if o.level == "A"]),
            "B": len([o for o in opportunities if o.level == "B"]),
        },
        "opportunities": [o.to_dict() for o in opportunities]
    }

    FINAL_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    FINAL_OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  保存到: {FINAL_OUTPUT}")

    # 打印摘要
    print("\n" + "=" * 60)
    print("政策机会摘要")
    print("=" * 60)

    level_emoji = {"S": "🔥", "A": "⭐", "B": "📋", "C": "📁"}
    for o in opportunities[:10]:
        emoji = level_emoji.get(o.level, "📁")
        worth = "✅" if o.is_worth_applying else "❌"
        print(f"\n{emoji}{o.level} {o.score:.1f}分 {o.priority} {worth}")
        print(f"  {o.title[:60]}")
        print(f"  💰 {o.roi.get('subsidy', 0)}万 | "
              f"📈 ROI: {o.roi.get('roi_label', '?')} | "
              f"⏰ {o.days_left}天")
        if o.recommended_project:
            print(f"  📦 建议项目: {o.recommended_project}")


def main():
    parser = argparse.ArgumentParser(description="政策处理管道")
    parser.add_argument("--fetch-only", action="store_true", help="仅抓取RSS")
    parser.add_argument("--parse-only", action="store_true", help="仅解析政策")
    parser.add_argument("--full", action="store_true", help="完整流程")
    parser.add_argument("--test", action="store_true", help="测试模式")
    parser.add_argument("--limit", type=int, default=50, help="处理数量限制")

    args = parser.parse_args()

    if args.test or args.full:
        run_pipeline(limit=args.limit)
    elif args.fetch_only:
        items = parse_rss_feeds(limit=args.limit)
        print(f"获取 {len(items)} 条政策")
        for item in items[:5]:
            print(f"  - {item['title'][:50]}")
    else:
        parser.print_help()


if __name__ == "__main__":
    from dataclasses import dataclass
    main()
