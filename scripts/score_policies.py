"""
ai-news-radar: Policy Scoring Script
Scores policy items using MiniMax LLM and outputs S/A/B/C graded results.
"""

import os
import json
import re
import glob
import logging
from datetime import datetime, timedelta
from typing import Optional
from openai import OpenAI

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("score_policies")

# ── Constants ─────────────────────────────────────────────────────────────────
BASE_URL = "https://v2.aicodee.com/v1"
MODEL = "MiniMax-M2.7-highspeed"
BATCH_SIZE = 15

GRADE_THRESHOLDS = {"S": 85, "A": 70, "B": 50}
DEFAULT_DATE = datetime.now().strftime("%Y-%m-%d")

# High-priority keywords (logistics/AI/digital focus)
HIGH_PRIORITY_KW = [
    "智慧物流", "无人机配送", "无人配送", "低空经济", "AI调度",
    "数字化转型", "智能仓储", "自动驾驶", "物流AI", "智慧仓储",
    "自动分拣", "智能物流", "无人仓储",
]
# Medium-priority keywords
MEDIUM_PRIORITY_KW = [
    "物流", "快递", "运输", "仓储", "供应链", "配送",
    "高新技术企业", "研发", "创新", "数字化", "智能化",
    "两新", "超长期国债", "设备更新", "以旧换新",
]
# Risk keywords (negative)
RISK_KW = ["垫资", "陪跑", "验收不明确", "验收难", "需配套资金"]

# ── Helpers ──────────────────────────────────────────────────────────────────

def load_input(date: str) -> list[dict]:
    """Load merged JSON for a given date."""
    path = f"data/merged/merged_{date}.json"
    if not os.path.exists(path):
        raise FileNotFoundError(f"Input file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Support both list format and dict with 'items' key
    if isinstance(data, list):
        items = data
    else:
        items = data.get('items', [])
    log.info(f"Loaded {len(items)} items from {path}")
    return items


def save_output(items: list[dict], date: str, stats: dict) -> None:
    """Save scored results."""
    out_dir = "data/scored"
    os.makedirs(out_dir, exist_ok=True)
    out_path = f"{out_dir}/scored_{date}.json"
    result = {
        "scored_at": datetime.now().isoformat(timespec="seconds") + "+08:00",
        "total_input": len(items),
        "graded": stats["graded"],
        "llm_count": stats["llm_count"],
        "backup_count": stats["backup_count"],
        "items": items,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log.info(f"Saved {len(items)} items → {out_path}")


def grade_from_score(score: int) -> str:
    if score >= GRADE_THRESHOLDS["S"]:
        return "S"
    elif score >= GRADE_THRESHOLDS["A"]:
        return "A"
    elif score >= GRADE_THRESHOLDS["B"]:
        return "B"
    else:
        return "C"


def parse_deadline(text: str | None) -> str | None:
    """Extract date from text like '2026-06-30' or '2026年6月30日'."""
    if not text:
        return None
    patterns = [
        r"(\d{4}-\d{2}-\d{2})",
        r"(\d{4})年(\d{1,2})月(\d{1,2})日",
        r"(\d{4}/\d{2}/\d{2})",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            if "年" in pat:
                return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            return m.group(1)
    return None


def deadline_score(deadline_str: str | None) -> int:
    """+15 if deadline within 30 days, +5 if no deadline (ongoing), 0 if expired."""
    if not deadline_str:
        return 5  # No deadline = ongoing program, give partial credit
    try:
        dl = datetime.strptime(deadline_str[:10], "%Y-%m-%d")
        days = (dl - datetime.now()).days
        if days < 0:
            return -20  # Expired = strong penalty
        elif days <= 30:
            return 15  # Urgent
        elif days <= 90:
            return 10  # Within 3 months
        else:
            return 5   # Future deadline
    except Exception:
        return 5


def amount_score(text: str | None) -> int:
    """+10 if a money amount is mentioned."""
    if not text:
        return 0
    return 10 if re.search(r"[\d\.]+[万千亿]元|最高|不超过|资助", text) else 0


def government_score(text: str | None) -> int:
    """+10 if likely a government policy domain."""
    if not text:
        return 0
    return 10 if re.search(r"政府|部委|市经信|市科委|区经信|区科委|工信部|科技部", text) else 0


def keyword_score(text: str | None) -> int:
    """Score based on keyword matching."""
    if not text:
        return 0
    score = 0
    combined = text
    for kw in HIGH_PRIORITY_KW:
        if kw in combined:
            score += 20
    for kw in MEDIUM_PRIORITY_KW:
        if kw in combined:
            score += 10
    for kw in RISK_KW:
        if kw in combined:
            score -= 10
    return max(0, min(100, score))


def backup_score(item: dict) -> dict:
    """Fallback heuristic scoring when LLM is unavailable."""
    title = item.get("title", "") or ""
    snippet = item.get("snippet", "") or ""
    text = title + " " + snippet

    score = keyword_score(text)
    score += deadline_score(item.get("deadline"))
    score += amount_score(text)
    score += government_score(text)
    score = max(0, min(100, score))

    return {
        "id": item.get("id", ""),
        "score": score,
        "grade": grade_from_score(score),
        "deadline": item.get("deadline") or parse_deadline(snippet),
        "amount": _extract_amount(text),
        "requirements": [],
        "fit_summary": _heuristic_summary(item, score),
        "risk_flags": _extract_risk_flags(text),
        "apply_recommendation": _recommend_from_score(score),
        "channel": _guess_channel(text),
    }


def _extract_amount(text: str) -> str:
    m = re.search(r"最高([\d\.]+[万千亿]?元?)|([\d\.]+[万千亿]?元)|资助[\d\.]+", text)
    return m.group(0) if m else ""


def _extract_risk_flags(text: str) -> list[str]:
    flags = []
    for kw in RISK_KW:
        if kw in text:
            flags.append(kw)
    return flags


def _heuristic_summary(item: dict, score: int) -> str:
    if score >= 85:
        return "高度匹配公司业务方向"
    elif score >= 70:
        return "匹配公司业务方向"
    elif score >= 50:
        return "部分匹配，可能适合"
    return "关联度较低"


def _recommend_from_score(score: int) -> str:
    if score >= 85:
        return "强烈建议申报"
    elif score >= 70:
        return "建议申报"
    elif score >= 50:
        return "可考虑申报"
    return "暂不推荐"


def _guess_channel(text: str) -> str:
    if "超长期国债" in text or "两新" in text:
        return "超长期国债/两新"
    if "低空" in text or "无人机" in text or "无人配送" in text:
        return "低空经济/无人配送"
    if "设备更新" in text or "以旧换新" in text:
        return "设备更新/以旧换新"
    if "高新技术" in text or "研发" in text:
        return "高新技术企业/研发"
    return "一般政策"


# ── LLM Scoring ──────────────────────────────────────────────────────────────

SCORING_PROMPT = """你是一名政策分析师，服务于上海中通吉网络技术有限公司（青浦区，中通快递集团子公司）。

请为以下政策打分，输出严格合法的JSON数组，每条政策一个对象，字段精简：
[id, score, grade, deadline, amount, requirements, fit_summary, risk_flags, apply_recommendation, channel]

要求：
- 只输出JSON数组，不要任何解释文字
- 严格JSON语法：数组元素之间必须有逗号，最后一个元素后无逗号
- score: 0-100整数
- grade: S(85+)/A(70-84)/B(50-69)/C(<50)
- deadline: YYYY-MM-DD或空字符串""
- amount: 资助金额描述，无则""
- requirements: 条件字符串数组，无则[]
- fit_summary: 一句话匹配说明
- risk_flags: 风险列表，无则[]
- apply_recommendation: "建议申报"/"可考虑"/"暂不推荐"
- channel: "低空经济"/"数字化转型"/"超长期国债"/"高企研发"/"一般政策"

公司偏好：物流快递智慧物流战略；规避垫资/陪跑；关注低空经济/AI调度/数字化转型。"""


def build_llm_messages(batch: list[dict]) -> list[dict]:
    """Build messages for a batch of items. Uses compact JSON."""
    items_text = json.dumps(batch, ensure_ascii=False)  # no indent = fewer tokens
    return [
        {"role": "system", "content": SCORING_PROMPT},
        {
            "role": "user",
            "content": f"请为以下 {len(batch)} 条政策打分：\n{items_text}",
        },
    ]


def extract_json_objects(text: str) -> list[dict]:
    """Robust JSON parser: extract individual {..} objects from potentially broken JSON."""
    results = []
    # Try direct JSON parse first
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    # Try to find individual JSON objects using regex
    # Match {...} but handle nested braces
    try:
        depth = 0
        start = None
        for i, c in enumerate(text):
            if c == '{':
                if depth == 0:
                    start = i
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0 and start is not None:
                    obj_str = text[start:i+1]
                    try:
                        obj = json.loads(obj_str)
                        if isinstance(obj, dict) and 'id' in obj:
                            results.append(obj)
                    except (json.JSONDecodeError, TypeError):
                        pass
                    start = None
    except Exception:
        pass
    return results


def call_llm_batch(client: OpenAI, batch: list[dict]) -> Optional[list[dict]]:
    """Call MiniMax LLM for a batch of items. Returns parsed JSON or None on failure."""
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=build_llm_messages(batch),
            temperature=0.2,
            max_tokens=4096,
        )
        raw = response.choices[0].message.content.strip()
        # Strip markdown fences
        raw = re.sub(r"^```json\s*", "", raw)
        raw = re.sub(r"^```\s*", "", raw)
        raw = raw.rstrip("`")
        # Try robust extraction
        results = extract_json_objects(raw)
        if results:
            return results
        # Fallback: try direct parse
        results = json.loads(raw)
        if isinstance(results, list):
            return results
        log.warning("LLM returned non-list, treating as parse failure")
        return None
    except json.JSONDecodeError as e:
        log.warning(f"JSON parse error: {e}")
        return None
    except Exception as e:
        log.warning(f"LLM API error: {e}")
        return None


def score_via_llm(client: OpenAI, item: dict) -> Optional[dict]:
    """Score a single item via LLM (fallback when batch fails)."""
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SCORING_PROMPT},
                {
                    "role": "user",
                    "content": f"请为以下政策打分：\n{json.dumps(item, ensure_ascii=False)}",
                },
            ],
            temperature=0.2,
            max_tokens=1024,
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r"^```json\s*", "", raw)
        raw = re.sub(r"^```\s*", "", raw)
        raw = raw.rstrip("`")
        # Try robust extraction first
        objs = extract_json_objects(raw)
        if objs and isinstance(objs[0], dict):
            return objs[0]
        # Fallback direct parse
        result = json.loads(raw)
        if isinstance(result, dict):
            return result
        return None
    except Exception as e:
        log.warning(f"Single-item LLM scoring failed: {e}")
        return None


# ── Main ──────────────────────────────────────────────────────────────────────

def ensure_id(item: dict, idx: int) -> dict:
    """Ensure every item has an id field."""
    if "id" not in item or not item["id"]:
        item["id"] = item.get("url", "") or f"item_{idx}"
    return item


def merge_scored(base: dict, scored: dict) -> dict:
    """Merge LLM scoring fields into the base item."""
    base["score"] = scored.get("score", 0)
    base["grade"] = scored.get("grade", grade_from_score(scored.get("score", 0)))
    base["deadline"] = scored.get("deadline", "") or base.get("deadline", "")
    base["amount"] = scored.get("amount", "")
    base["requirements"] = scored.get("requirements", [])
    base["fit_summary"] = scored.get("fit_summary", "")
    base["risk_flags"] = scored.get("risk_flags", [])
    base["apply_recommendation"] = scored.get("apply_recommendation", "")
    base["channel"] = scored.get("channel", "")
    return base


def process_items(items: list[dict], use_llm: bool, client: Optional[OpenAI] = None) -> tuple[list[dict], dict]:
    """Process all items, return scored list + stats."""
    graded = {"S": 0, "A": 0, "B": 0, "C": 0}
    llm_count = 0
    backup_count = 0
    results = []

    for i in range(0, len(items), BATCH_SIZE):
        batch = items[i : i + BATCH_SIZE]
        batch = [ensure_id(item, i + j) for j, item in enumerate(batch)]

        if use_llm and client:
            scored_batch = call_llm_batch(client, batch)
            if scored_batch:
                # Parse each scored item
                parsed = []
                for s in scored_batch:
                    if isinstance(s, dict) and "id" in s:
                        parsed.append(s)
                    else:
                        parsed.append(None)
                # Fallback individual items that failed to parse
                for j, scored_item in enumerate(parsed):
                    if scored_item is None:
                        individual = score_via_llm(client, batch[j])
                        if individual:
                            parsed[j] = individual
                        else:
                            log.warning(f"Individual LLM scoring failed for {batch[j].get('id','?')}, using backup")
                            parsed[j] = backup_score(batch[j])
                            backup_count += 1
                            llm_count -= 1  # compensate
                llm_count += len([p for p in parsed if p is not None])
            else:
                # Batch failed, try individually
                parsed = []
                for j, item in enumerate(batch):
                    individual = score_via_llm(client, item)
                    if individual:
                        parsed.append(individual)
                        llm_count += 1
                    else:
                        parsed.append(backup_score(item))
                        backup_count += 1
        else:
            parsed = [backup_score(item) for item in batch]
            backup_count += len(batch)

        for base, scored in zip(batch, parsed):
            if scored is None:
                scored = backup_score(base)
                backup_count += 1
            merged = merge_scored(base, scored)
            merged["grade"] = grade_from_score(merged.get("score", 0))
            results.append(merged)
            g = merged.get("grade", "C")
            if g in graded:
                graded[g] += 1

    return results, {
        "graded": graded,
        "llm_count": llm_count,
        "backup_count": backup_count,
    }


def print_summary(results: list[dict], stats: dict) -> None:
    """Print grading summary and top 5 items."""
    g = stats["graded"]
    total = sum(g.values())
    print(
        f"Scored {total} items: "
        f"S={g['S']}, A={g['A']}, B={g['B']}, C={g['C']} "
        f"(via LLM: {stats['llm_count']}, via backup: {stats['backup_count']})"
    )
    print("\nTop 5 by score:")
    top5 = sorted(results, key=lambda x: x.get("score", 0), reverse=True)[:5]
    for rank, item in enumerate(top5, 1):
        title = (item.get("title") or "")[:50]
        score = item.get("score", 0)
        grade = item.get("grade", "?")
        deadline = item.get("deadline", "无")
        amount = item.get("amount", "")
        print(f"  {rank}. [{grade}{score}] {title} | 截止:{deadline} | {amount}")


def main(date: str = DEFAULT_DATE) -> None:
    log.info(f"Starting policy scoring for date={date}")

    # Load input
    items = load_input(date)

    # Check API key
    api_key = os.environ.get("MINIMAX_API_KEY")
    use_llm = False
    client = None

    if api_key:
        try:
            client = OpenAI(api_key=api_key, base_url=BASE_URL)
            # Quick connectivity check
            client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=2,
            )
            use_llm = True
            log.info("MiniMax LLM connected successfully")
        except Exception as e:
            log.warning(f"MiniMax API not available ({e}), using backup mode")
            use_llm = False
            client = None
    else:
        log.info("MINIMAX_API_KEY not set, using backup heuristic scoring")

    # Process
    results, stats = process_items(items, use_llm=use_llm, client=client)

    # Sort by score descending
    results.sort(key=lambda x: x.get("score", 0), reverse=True)

    # Save
    save_output(results, date, stats)

    # Print summary
    print_summary(results, stats)


if __name__ == "__main__":
    import sys
    date_arg = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DATE
    main(date_arg)
