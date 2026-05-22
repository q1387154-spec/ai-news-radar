"""
ai-news-radar: Source Discovery Script
Auto-discovers new policy sources from scored results and maintains approved/pending list.
"""

import json
import re
import hashlib
from datetime import datetime, date as date_obj
from pathlib import Path
from urllib.parse import urlparse

# ── paths ────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
DATA_ROOT    = PROJECT_ROOT / "data"
SOURCES_FILE = DATA_ROOT / "sources" / "sources.json"


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _load_sources():
    """Load existing sources JSON, return dict with approved/pending sets."""
    if SOURCES_FILE.exists():
        with open(SOURCES_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return raw
    return {"sources": {"approved": [], "pending": []}}


def _save_sources(data):
    SOURCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SOURCES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_scored_items(today_str):
    """Load today's scored JSON. Falls back to the most recent scored file."""
    scored_dir = DATA_ROOT / "scored"
    candidates = []

    # 1) exact today match
    today_file = scored_dir / f"scored_{today_str}.json"
    if today_file.exists():
        candidates.append(today_file)

    # 2) most recent file if no exact match
    if not candidates:
        existing = sorted(scored_dir.glob("scored_*.json"), reverse=True)
        if existing:
            candidates.append(existing[0])

    items = []
    for path in candidates:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # support both a list or {"items":[...]} wrapper
        if isinstance(data, list):
            items.extend(data)
        elif isinstance(data, dict):
            items.extend(data.get("items", []))
    return items


# ── domain extraction ─────────────────────────────────────────────────────────

GOV_DEPT_NAMES = {
    # ministry keywords → display name
    "mof":      "财政部",
    "most":     "科技部",
    "mot":      "交通运输部",
    "mlr":      "自然资源部",
    "mee":      "生态环境部",
    "mam":      "农业农村部",
    "moe":      "教育部",
    "nhc":      "国家卫健委",
    "saiting": "中央网信办",
    "cac":      "中央网信办",
    "gov":      "政府",
}

CITY_GOV_PATTERNS = [
    # Shanghai
    (r"sh\.gov\.cn", "上海市人民政府"),
    (r"sheitc",     "上海市经信委"),
    (r"shzjw",      "上海市经信委"),
    (r"stcsm",      "上海市科委"),
    (r"shtic",      "上海市商务委"),
    (r"shzrzx",     "上海市人社局"),
    # Beijing
    (r"beijing\.gov\.cn", "北京市人民政府"),
    (r"bjgov",              "北京市人民政府"),
    # Guangdong
    (r"gd\.gov\.cn",       "广东省人民政府"),
    (r"gdzx\.gov\.cn",  "广东省人民政府"),
    # Zhejiang
    (r"zj\.gov\.cn",       "浙江省人民政府"),
    # Jiangsu
    (r"jiangsu\.gov\.cn",  "江苏省人民政府"),
    # National
    (r"gov\.cn/policy",    "中央政府政策"),
]


def extract_domain(url):
    """Return netloc from URL."""
    try:
        parsed = urlparse(url)
        return parsed.netloc.lower()
    except Exception:
        return ""


def _classify_type(domain):
    if "gov.cn" in domain or domain.endswith(".gov"):
        return "gov"
    if "weixin" in domain or "mp.weixin" in domain:
        return "wechat"
    return "news"


def _classify_tier(source_type, domain, title="", snippet=""):
    """Assign tier 1-3 based on quality signals."""
    if source_type == "gov":
        return 1
    if source_type == "wechat":
        # government-affiliated wechat accounts
        gov_keywords = ["政府", "官方", "部委", "经信委", "科委", "人社", "发改委", "财政局"]
        combined = (title + snippet).lower()
        for kw in gov_keywords:
            if kw in combined:
                return 1
        return 2
    return 3


def _extract_gov_dept_name(domain, url):
    """Extract human-readable department name from gov URL."""
    # check explicit city patterns first
    for pattern, name in CITY_GOV_PATTERNS:
        if re.search(pattern, domain, re.IGNORECASE):
            return name

    # check ministry short codes in path
    try:
        parsed = urlparse(url)
        path = parsed.path.lower()
        for code, name in GOV_DEPT_NAMES.items():
            if code in path:
                return name
    except Exception:
        pass

    # generic fallback
    return domain


def _extract_wechat_source_name(title, snippet, url):
    """Try to derive WeChat account name from context."""
    # common patterns: "来源：XXX" or "公众号：XXX"
    combined = title + "\n" + snippet

    m = re.search(r"来源[：:]\s*([^\n\r]{2,30})", combined)
    if m:
        return m.group(1).strip()

    m = re.search(r"公众号[：:]\s*([^\n\r]{2,30})", combined)
    if m:
        return m.group(1).strip()

    # try to clean domain
    domain = extract_domain(url)
    if "weixin" in domain or "mp.weixin" in domain:
        return f"WeChat-{domain}"
    return "WeChat"


def _build_source_name(url, source_type, title, snippet):
    if source_type == "gov":
        return _extract_gov_dept_name(extract_domain(url), url)
    if source_type == "wechat":
        return _extract_wechat_source_name(title, snippet, url)
    # news: use domain
    domain = extract_domain(url)
    # strip www.
    domain = re.sub(r"^www\.", "", domain)
    return domain


# ── hashing ───────────────────────────────────────────────────────────────────

def make_source_id(domain):
    """12-char hash ID from domain."""
    return hashlib.sha1(domain.encode()).hexdigest()[:12]


# ── core logic ────────────────────────────────────────────────────────────────

SCORE_THRESHOLD = 70


def discover_sources():
    today_str = _today()

    # load
    sources_data = _load_sources()
    approved_list = sources_data["sources"]["approved"]
    pending_list  = sources_data["sources"]["pending"]

    # build lookup sets
    approved_domains = {item["url"] for item in approved_list}
    pending_domains  = {item["url"] for item in pending_list}

    # load scored items
    items = _load_scored_items(today_str)

    if not items:
        print("No scored policy items found.")
        print(f"Checked: data/scored/scored_{today_str}.json or most recent scored file.")
        return

    # filter to A/B grade
    ab_items = [it for it in items if it.get("score", 0) >= SCORE_THRESHOLD]

    # collect new source candidates: domain -> {name, type, tier, matched_ids, topics}
    candidates = {}  # domain -> candidate dict

    for item in ab_items:
        url    = item.get("url", "")
        title  = item.get("title", "")
        snippet = item.get("snippet", "") or item.get("summary", "")
        score  = item.get("score", 0)
        pid    = item.get("id", url)

        if not url:
            continue

        domain = extract_domain(url)
        if not domain:
            continue

        source_type = _classify_type(domain)
        tier        = _classify_tier(source_type, domain, title, snippet)
        name        = _build_source_name(url, source_type, title, snippet)

        if domain not in candidates:
            candidates[domain] = {
                "name": name,
                "url": domain,
                "type": source_type,
                "tier": tier,
                "matchedPolicyIds": [],
                "topics": set(),
            }

        candidates[domain]["matchedPolicyIds"].append(pid)

        # topics from keywords or tags
        topics = item.get("keywords", []) or item.get("tags", []) or []
        if isinstance(topics, list):
            for t in topics:
                if isinstance(t, str) and t.strip():
                    candidates[domain]["topics"].add(t.strip())
        elif isinstance(topics, str):
            candidates[domain]["topics"].add(topics.strip())

    # filter out already known
    new_candidates = {
        dom: cand for dom, cand in candidates.items()
        if dom not in approved_domains and dom not in pending_domains
    }

    # build report stats
    total_ab          = len(ab_items)
    unique_domains    = len(candidates)
    new_count         = len(new_candidates)

    # add new to pending
    now_iso = datetime.now().isoformat()
    for domain, cand in new_candidates.items():
        pending_item = {
            "id":               make_source_id(domain),
            "name":             cand["name"],
            "url":              cand["url"],
            "type":             cand["type"],
            "tier":             cand["tier"],
            "addedAt":          now_iso,
            "topics":           sorted(cand["topics"]),
            "matchedPolicyIds": cand["matchedPolicyIds"],
        }
        pending_list.append(pending_item)

    # write back
    sources_data["sources"]["pending"] = pending_list
    _save_sources(sources_data)

    # ── print report ────────────────────────────────────────────────────────

    print()
    print("=== Source Discovery Report ===")
    print(f"Total A/B policies analyzed:    {total_ab}")
    print(f"Unique source domains found:    {unique_domains}")
    print(f"New sources discovered:         {new_count}")
    print()

    if new_candidates:
        for domain, cand in sorted(new_candidates.items()):
            matched = len(cand["matchedPolicyIds"])
            print(f"  [pending] {cand['name']} ({cand['type']}, tier {cand['tier']}) - matched {matched} policies")
        print()
        print(f"Sources now pending review: {len(pending_list)}")
    else:
        print("No new sources discovered.")

    print()
    print(f"Sources file updated: {SOURCES_FILE}")


if __name__ == "__main__":
    discover_sources()
