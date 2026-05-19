#!/usr/bin/env python3
"""
analyze_opportunities.py — 政策机会分析（纯本地计算，无需 AI API）

基于规则对企业画像和政策进行匹配、打分、过滤。

输入: data/merged.json
输出: data/policy-opportunities.json

企业画像（中通吉）:
    行业: 物流/快递
    区域: 上海/青浦
    资质: 科技型中小企业（科小）
    重点: 数字化转型 / 低空经济 / 智慧物流

评分维度:
    - 地域匹配（上海/青浦）
    - 行业匹配（物流/快递）
    - 资质匹配（科小/高企）
    - 时间紧迫度
    - 补贴金额规模

用法:
    python scripts/analyze_opportunities.py --input data/merged.json --output data/policy-opportunities.json
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path


# ═══════════════════════════════════════════════════════════════
# 企业画像
# ═══════════════════════════════════════════════════════════════
ENTERPRISE = {
    "name": "上海中通吉网络技术有限公司",
    "short_name": "中通吉",
    "industry": ["物流", "快递", "供应链", "网络货运"],
    "region": ["上海", "青浦", "长三角"],
    "certifications": {
        "owned": ["科技型中小企业"],  # 待确认
        "target": ["高新技术企业", "专精特新", "小巨人"],
    },
    "tech_stack": ["AI调度", "智慧物流", "数字化转型", "低空经济（无人机配送）"],
    "key_projects": [
        {"name": "智慧物流数字化转型项目", "keywords": ["数字化转型", "智慧物流", "物流数字化"]},
        {"name": "无人机配送试点项目", "keywords": ["低空经济", "无人机配送", "智慧快递"]},
        {"name": "仓储智能化升级项目", "keywords": ["仓储", "智能化", "冷链", "供应链升级"]},
    ],
}

# ═══════════════════════════════════════════════════════════════
# 关键词匹配规则
# ═══════════════════════════════════════════════════════════════
MATCH_RULES = {
    # 行业关键词 → 权重
    "industry": {
        "物流": 1.0, "快递": 1.0, "货运": 0.8, "仓储": 0.8,
        "供应链": 0.7, "配送": 0.8, "末端配送": 1.0, "网络货运": 0.9,
    },
    # 地域关键词
    "region": {
        "青浦": 1.0, "上海": 0.9, "长三角": 0.7, "国家": 0.3,
    },
    # 资质关键词
    "cert": {
        "科小": 1.0, "科技型中小企业": 1.0,
        "高企": 0.9, "高新技术企业": 0.9,
        "专精特新": 0.8, "小巨人": 0.8,
    },
    # 政策类型
    "policy_type": {
        "补贴": 1.0, "扶持": 1.0, "资助": 0.9, "奖励": 0.9,
        "专项资金": 1.0, "减负": 0.8,
        "认定": 0.7, "备案": 0.5, "申报": 0.8,
    },
}

# 行业热点赛道
TRACKS = {
    "低空经济": ["低空经济", "无人机", "eVTOL", "飞行汽车", "空域改革", "无人配送", "智慧快递"],
    "数字化转型": ["数字化转型", "数智化", "智慧物流", "数字孪生", "AI调度", "产业互联网"],
    "财税补贴": ["补贴", "扶持", "资助", "奖励", "专项资金", "减负", "减税", "减免"],
    "高企认定": ["高企", "高新技术企业", "研发费用", "加计扣除", "科小", "专精特新", "小巨人"],
    "人社补贴": ["稳岗", "技能补贴", "创业", "就业见习", "培训", "社保补贴"],
    "物流行业": ["物流", "快递", "货运", "仓储", "供应链", "冷链", "绿色物流"],
}


def score_item(item: dict) -> dict:
    """对单条政策进行评分"""
    title = item.get("title", "")
    content = item.get("content", "")[:1000]  # 只看前1000字
    summary = item.get("summary", "")
    text = (title + " " + content + " " + summary).lower()

    scores = {}
    matched_tags = []
    missing_tags = []

    # 1. 行业匹配
    ind_score = 0
    for kw, weight in MATCH_RULES["industry"].items():
        if kw in text:
            ind_score = max(ind_score, weight)
            if kw not in matched_tags:
                matched_tags.append(kw)
    scores["industry"] = ind_score

    # 2. 地域匹配
    reg_score = 0
    for kw, weight in MATCH_RULES["region"].items():
        if kw in text:
            reg_score = max(reg_score, weight)
    scores["region"] = reg_score

    # 3. 赛道匹配
    track_score = 0
    for track, kws in TRACKS.items():
        if any(kw in text for kw in kws):
            track_score = max(track_score, 0.8)
            if track not in matched_tags:
                matched_tags.append(track)
    scores["track"] = track_score

    # 4. 资质匹配（如果有内容提到资质要求）
    cert_score = 0
    cert_text = text
    for kw, weight in MATCH_RULES["cert"].items():
        if kw in cert_text:
            # 检查企业是否有这个资质
            if kw in ENTERPRISE["certifications"]["owned"]:
                cert_score = max(cert_score, weight)  # 有资质，匹配
            else:
                cert_score = max(cert_score, weight * 0.5)  # 没资质，但可争取
    scores["cert"] = cert_score

    # 5. 时间紧迫度（越近越高）
    deadline_score = 0.5
    deadline = extract_deadline(item)
    if deadline:
        days = (deadline - datetime.now(timezone.utc)).days
        if days < 0:
            deadline_score = 0  # 已过期
        elif days <= 7:
            deadline_score = 1.0
        elif days <= 14:
            deadline_score = 0.9
        elif days <= 30:
            deadline_score = 0.7
        elif days <= 90:
            deadline_score = 0.5
    scores["deadline"] = deadline_score

    # 综合评分（加权）
    final = (
        scores["industry"] * 0.25 +
        scores["region"] * 0.15 +
        scores["track"] * 0.25 +
        scores["cert"] * 0.15 +
        scores["deadline"] * 0.20
    ) * 100

    # 等级
    if final >= 85:
        level = "S"
    elif final >= 70:
        level = "A"
    elif final >= 50:
        level = "B"
    else:
        level = "C"

    # 是否值得申报
    is_worth = (
        scores["industry"] >= 0.5 and
        (scores["region"] >= 0.5 or "国家" in text) and
        final >= 40 and
        scores["deadline"] > 0
    )

    # 优先级
    priority = "P1"
    if level in ["S", "A"] and is_worth:
        priority = "P0"

    return {
        "final": round(final, 1),
        "level": level,
        "priority": priority,
        "scores": {k: round(v, 2) for k, v in scores.items()},
        "matched_tags": matched_tags,
        "is_worth_applying": is_worth,
        "days_left": calc_days_left(deadline),
        "deadline": deadline.isoformat() if deadline else "",
    }


def extract_deadline(item: dict) -> 'datetime|None':
    """从内容中提取截止日期（多pattern兜底）"""
    raw_text = item.get("content", "")[:5000]
    title = item.get("title", "")
    text = (title + " " + raw_text).lower()

    # 优先从原文提取（更精确）
    date_patterns_raw = [
        # 申报截止类（最常见）
        r"截止[：:　]*(\d{4})[-年/](\d{1,2})[-月/](\d{1,2})",
        r"截至[：:　]*(\d{4})[-年/](\d{1,2})[-月/](\d{1,2})",
        r"申报截止[：:　]*(\d{4})[-年/](\d{1,2})[-月/](\d{1,2})",
        r"受理截止[：:　]*(\d{4})[-年/](\d{1,2})[-月/](\d{1,2})",
        r"在线申报截止[：:　]*(\d{4})[-年/](\d{1,2})[-月/](\d{1,2})",
        # 常见日期格式
        r"(\d{4})年(\d{1,2})月(\d{1,2})日",
        r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})",
        # 止/终格式
        r"(\d{4})年(\d{1,2})月(\d{1,2})止",
        r"(\d{4})年(\d{1,2})月(\d{1,2})截止",
        # 含"发布"字样
        r"发布[：:　]*(\d{4})[-年/](\d{1,2})[-月/](\d{1,2})",
        r"日期[：:　]*(\d{4})[-年/](\d{1,2})[-月/](\d{1,2})",
        r"时间[：:　]*(\d{4})[-年/](\d{1,2})[-月/](\d{1,2})",
    ]

    for pat in date_patterns_raw:
        m = re.search(pat, text)
        if m:
            try:
                year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if 2020 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                    return datetime(year, month, day, tzinfo=timezone.utc)
            except Exception:
                pass

    # 降级：匹配相对表达（如"本通知自发布之日起30日内"）
    # 这类通常意味着短期内截止，给予默认30天后
    if any(k in text for k in ["自发布之日起", "尽快", "从速", "从通知之日起"]):
        # 默认30天后
        from datetime import timedelta
        return datetime.now(timezone.utc) + timedelta(days=30)

    return None


def calc_days_left(deadline: 'datetime|None') -> int:
    if not deadline:
        return 999
    delta = deadline - datetime.now(timezone.utc)
    return max(0, delta.days)


def extract_amount(text: str) -> dict:
    """从文本中提取补贴金额（宽松匹配）"""
    # 扩大pattern范围
    patterns = [
        # 最常见格式
        r"最高(?:资助|支持|补贴|奖励)?\s*(\d+(?:\.\d+)?)\s*(?:万|亿元|元)",
        r"(?:资助|支持|补贴|奖励)\s*(?:高达|不超过|上限)?\s*(\d+(?:\.\d+)?)\s*(?:万|亿元|元)",
        r"(?:单项|单个项目)?\s*(?:支持|资助|补贴)\s*(\d+(?:\.\d+)?)\s*(?:万|亿元|元)",
        r"(\d+(?:\.\d+)?)\s*(?:万|亿元|元)\s*(?:资助|补贴|奖励|支持)",
        # 百分比类
        r"补贴比例\s*(\d+(?:\.\d+)?)\s*%",
        # 简化匹配
        r"(\d+(?:\.\d+)?)\s*万元",
        r"(\d+(?:\.\d+)?)\s*亿元",
    ]
    amounts = []
    for pat in patterns:
        matches = re.findall(pat, text)
        for m in matches:
            try:
                val = float(m)
                # 合理范围过滤：100元 ~ 100亿
                if 100 <= val <= 1e10:
                    amounts.append(val)
            except Exception:
                pass

    if not amounts:
        return {"amount": 0, "unit": "万元", "label": "未知"}
    max_amt = max(amounts)
    if max_amt >= 10000:
        return {"amount": max_amt / 10000, "unit": "亿元", "label": f"{max_amt/10000:.1f}亿"}
    elif max_amt >= 1:
        return {"amount": max_amt, "unit": "万元", "label": f"{max_amt:.0f}万"}
    else:
        return {"amount": max_amt * 10000, "unit": "元", "label": f"{max_amt*10000:.0f}元"}


def generate_project_name(item: dict) -> str:
    """生成建议项目名称"""
    title = item.get("title", "")
    tags = item.get("tags", [])

    if any(k in title for k in ["低空", "无人机", "eVTOL"]):
        return "无人机配送智慧物流试点项目"
    if any(k in title for k in ["数字", "智慧物流", "AI", "数智"]):
        return "智慧物流数字化转型项目"
    if any(k in title for k in ["仓储", "冷链"]):
        return "智能仓储冷链升级项目"
    if any(k in title for k in ["技改", "设备更新", "改造"]):
        return "物流设施技术改造项目"
    if any(k in title for k in ["研发", "科小", "高企"]):
        return "物流科技研发创新项目"

    # 从 tag 推断
    if "低空经济" in tags:
        return "无人机配送智慧物流试点项目"
    if "数字化" in tags:
        return "智慧物流数字化转型项目"
    if "物流快递" in tags:
        return "智慧物流综合服务项目"

    return "现代物流智慧化建设项目"


def analyze_opportunities(input_file: str, output_file: str):
    """主函数"""
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print(f"{'='*60}")
    print(f"政策机会分析（本地计算）")
    print(f"{'='*60}")

    data = json.loads(Path(input_file).read_text(encoding="utf-8"))
    items = data.get("items", [])
    print(f"输入: {len(items)} 条政策")

    opportunities = []
    for i, item in enumerate(items):
        result = score_item(item)
        if result["final"] < 30 and not result["is_worth_applying"]:
            continue  # 跳过完全不相关的

        deadline = extract_deadline(item)
        days_left = calc_days_left(deadline)
        amount_info = extract_amount(item.get("content", "")[:3000])
        project_name = generate_project_name(item)

        opp = {
            "id": item.get("id", f"opp_{i}"),
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "source": item.get("source", item.get("source_name", "")),
            "source_level": item.get("level", item.get("_source", "")),
            "type": item.get("_source", "unknown"),
            "published_at": item.get("published_at", ""),
            "deadline": deadline.isoformat() if deadline else "",
            "days_left": days_left,

            # 评分
            "score": result["final"],
            "level": result["level"],
            "priority": result["priority"],
            "scores": result["scores"],
            "matched_tags": result["matched_tags"],
            "is_worth_applying": result["is_worth_applying"],

            # 金额
            "amount": amount_info["amount"],
            "amount_label": amount_info["label"],

            # 建议
            "recommended_project": project_name,
            "tags": item.get("tags", []),
            "regions": item.get("regions", []),
        }
        opportunities.append(opp)

    # 按评分排序
    opportunities.sort(key=lambda x: (x["priority"] == "P0", x["score"]), reverse=True)

    # 统计
    total = len(opportunities)
    by_level = {"S": 0, "A": 0, "B": 0, "C": 0}
    by_priority = {"P0": 0, "P1": 0}
    worth_count = sum(1 for o in opportunities if o["is_worth_applying"])

    for o in opportunities:
        by_level[o["level"]] = by_level.get(o["level"], 0) + 1
        by_priority[o["priority"]] = by_priority.get(o["priority"], 0) + 1

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "enterprise": ENTERPRISE["name"],
        "total_input": len(items),
        "total_output": total,
        "worth_applying": worth_count,
        "by_level": by_level,
        "by_priority": by_priority,
        "opportunities": opportunities,
    }

    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    Path(output_file).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    # 打印摘要
    print(f"\n分析完成:")
    print(f"  输入: {len(items)} 条")
    print(f"  输出: {total} 条机会")
    print(f"  值得申报: {worth_count} 条")
    print(f"  等级分布: S={by_level['S']} A={by_level['A']} B={by_level['B']} C={by_level['C']}")
    print(f"  优先级: P0={by_priority['P0']} P1={by_priority['P1']}")
    print(f"\nTop 5 机会:")
    for o in opportunities[:5]:
        emoji = "🔥" if o["level"] == "S" else "⭐" if o["level"] == "A" else "📋"
        worth = "✅" if o["is_worth_applying"] else "❌"
        print(f"  {emoji} {o['level']} {o['score']:.0f}分 {o['priority']} {worth}")
        print(f"    {o['title'][:55]}")
        print(f"    💰 {o['amount_label']} | ⏰ {o['days_left']}天 | {o['source']}")
    print(f"\n输出: {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="政策机会分析")
    parser.add_argument("--input", default="data/merged.json")
    parser.add_argument("--output", default="data/policy-opportunities.json")
    args = parser.parse_args()

    base = Path(__file__).parent.parent
    inp = base / args.input
    out = base / args.output

    if not inp.exists():
        print(f"输入文件不存在: {inp}")
        sys.exit(1)

    analyze_opportunities(str(inp), str(out))
