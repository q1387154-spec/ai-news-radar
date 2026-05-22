#!/usr/bin/env python3
"""
merge.py - Merge and deduplicate raw policy items from multiple fetch runs.

Input:  data/raw/*.json (from fetch_policies.py output)
Output: data/merged/merged_{date}.json

Logic:
  1. Read all data/raw/ JSON files (or accept glob pattern as sys.argv[1])
  2. Merge all items from all channels across all runs
  3. Deduplicate by URL (keep one with longest snippet / most recent published_at)
  4. Extract + normalize domain and published_date
  5. Sort by published_date (newest first), then by snippet length (longest first)

Deduplication rules:
  - URL exact match → duplicate
  - Same domain + similar title (Jaccard similarity > 0.7 on Chinese text) → likely duplicate
  - Keep the one with most complete fields
"""

import json
import glob
import re
import sys
import os
from pathlib import Path
from urllib.parse import urlparse
from dateutil import parser as dateutil_parser
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Jaccard similarity for Chinese text
# ---------------------------------------------------------------------------

CHINESE_PUNCT = re.compile(r'[，。！？；：、""''《》（）【】『』「」\s,.!?;:"\'()\[\]{}]+')

def tokenize_chinese(text: str) -> set:
    """Split Chinese text into tokens using punctuation and delimiters."""
    if not text:
        return set()
    tokens = CHINESE_PUNCT.split(text.strip())
    # Filter out empty tokens and single characters (noise)
    return {t for t in tokens if len(t) > 1}

def jaccard_similarity(a: str, b: str) -> float:
    """Jaccard similarity between two strings on Chinese token sets."""
    set_a = tokenize_chinese(a)
    set_b = tokenize_chinese(b)
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)

# ---------------------------------------------------------------------------
# URL decoding helpers
# ---------------------------------------------------------------------------

def safe_decode(text: str) -> str:
    """Attempt to URL-decode a string, falling back to original."""
    if not isinstance(text, str):
        text = str(text)
    try:
        # Try URL decode
        from urllib.parse import unquote
        decoded = unquote(text, errors='strict')
        if decoded != text:
            return decoded
    except Exception:
        pass
    return text

def normalize_url(url: str) -> str:
    """Normalize a URL: decode, strip, and lower-case for comparison."""
    url = safe_decode(url).strip()
    # Normalize trailing slash
    url = re.sub(r'/$', '', url)
    return url.lower()

# ---------------------------------------------------------------------------
# Domain extraction
# ---------------------------------------------------------------------------

def extract_domain(url: str) -> str:
    """Extract clean domain from URL."""
    url = safe_decode(url)
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        # Strip leading www. for cleaner grouping
        domain = re.sub(r'^www\.', '', domain)
        return domain if domain else 'unknown'
    except Exception:
        return 'unknown'

# ---------------------------------------------------------------------------
# Date normalization
# ---------------------------------------------------------------------------

def normalize_date(value) -> str | None:
    """Normalize various date formats to YYYY-MM-DD or None."""
    if not value:
        return None
    if isinstance(value, (datetime, datetime)):
        dt = value
    else:
        try:
            dt = dateutil_parser.parse(str(value), fuzzy=True)
        except Exception:
            return None
    # If timezone-aware, convert to local
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local_tz = timezone.utc  # Keep as UTC for consistency
    dt = dt.astimezone(local_tz)
    return dt.strftime('%Y-%m-%d')

# ---------------------------------------------------------------------------
# Field completeness score
# ---------------------------------------------------------------------------

def completeness_score(item: dict) -> int:
    """Score how many non-empty core fields an item has."""
    score = 0
    for key in ['title', 'snippet', 'url', 'published_at', 'domain']:
        if item.get(key):
            score += 1
    return score

# ---------------------------------------------------------------------------
# Main merge logic
# ---------------------------------------------------------------------------

def load_raw_items(patterns: list[str]) -> tuple[list[dict], list[str]]:
    """Load all JSON files matching patterns. Returns (items, source_files)."""
    items = []
    source_files = []
    for pattern in patterns:
        for filepath in glob.glob(pattern):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # Normalize: data may be a list, or dict with 'items', or dict with 'channels'
                if isinstance(data, list):
                    file_items = data
                elif isinstance(data, dict):
                    # fetch_policies.py v2 outputs {channels: {tavily: [...], cn-search: [...], gov_html: [...]}}
                    if 'channels' in data:
                        file_items = []
                        for channel_items in data['channels'].values():
                            if isinstance(channel_items, list):
                                file_items.extend(channel_items)
                    else:
                        file_items = data.get('items', [])
                else:
                    file_items = []
                for item in file_items:
                    if isinstance(item, dict):
                        items.append(item)
                source_files.append(filepath)
            except Exception as e:
                print(f"[WARN] Failed to load {filepath}: {e}", file=sys.stderr)
    return items, source_files

def extract_url(item: dict) -> str:
    """Get normalized URL from item."""
    url = item.get('url') or item.get('link') or item.get('href') or ''
    return normalize_url(str(url))

def extract_title(item: dict) -> str:
    """Get cleaned title from item."""
    title = item.get('title') or item.get('标题') or ''
    return safe_decode(str(title).strip())

def extract_snippet(item: dict) -> str:
    """Get cleaned snippet from item."""
    snippet = (item.get('snippet') or item.get('description') or
               item.get('desc') or item.get('summary') or item.get('内容') or '')
    return safe_decode(str(snippet).strip())

def enrich_item(item: dict) -> dict:
    """Add domain and published_date to item, clean fields."""
    url = extract_url(item)
    domain = extract_domain(url) if url else 'unknown'
    title = extract_title(item)
    snippet = extract_snippet(item)
    raw_date = item.get('published_at') or item.get('publishedDate') or item.get('date') or item.get('发布时间')
    published_date = normalize_date(raw_date)
    return {
        'url': url,
        'title': title,
        'snippet': snippet,
        'domain': domain,
        'published_date': published_date,
        # Preserve original item data
        **{k: v for k, v in item.items()
           if k not in ('url', 'title', 'snippet', 'domain', 'published_date')},
    }

def dedupe(items: list[dict]) -> list[dict]:
    """
    Deduplicate items by URL + title similarity.
    Returns deduplicated list preserving the best item per group.
    """
    # First pass: exact URL deduplication
    url_map = {}  # url -> item
    for item in items:
        url = item['url']
        if not url:
            continue
        if url not in url_map:
            url_map[url] = item
        else:
            # Keep the one with longest snippet
            existing = url_map[url]
            if len(item['snippet']) > len(existing['snippet']):
                url_map[url] = item
            elif (len(item['snippet']) == len(existing['snippet']) and
                  item['published_date'] and
                  (not existing['published_date'] or item['published_date'] > existing['published_date'])):
                url_map[url] = item

    candidates = list(url_map.values())

    # Second pass: title similarity within same domain
    result = []
    for item in candidates:
        is_dup = False
        item_domain = item['domain']
        item_title = item['title']
        item_url = item['url']
        for existing in result:
            # Same domain check
            if existing['domain'] != item_domain:
                continue
            existing_url = existing['url']
            # Skip if same URL (already handled)
            if existing_url == item_url:
                is_dup = True
                break
            # Jaccard similarity on title
            if item_title and existing['title']:
                sim = jaccard_similarity(item_title, existing['title'])
                if sim > 0.7:
                    is_dup = True
                    break
        if not is_dup:
            result.append(item)

    return result

def sort_items(items: list[dict]) -> list[dict]:
    """Sort items: newest published_date first, then longest snippet."""
    def sort_key(item):
        date_str = item.get('published_date') or '0000-00-00'
        # Parse date for proper comparison
        try:
            date_val = datetime.strptime(date_str, '%Y-%m-%d')
        except Exception:
            date_val = datetime.min
        snippet_len = len(item.get('snippet') or '')
        return (date_val, snippet_len)
    return sorted(items, key=sort_key, reverse=True)

def domain_stats(items: list[dict]) -> dict:
    """Count items per domain."""
    counts = {}
    for item in items:
        domain = item.get('domain', 'unknown')
        if domain == 'unknown' or not domain:
            domain = 'unknown'
        counts[domain] = counts.get(domain, 0) + 1
    return counts

def group_by_domain(counts: dict) -> dict:
    """Group domains into gov.cn, weixin, other known, and other."""
    gov_domains = ['gov.cn', 'gov', 'gov.cn.', 'gov.cn:']
    weixin_domains = ['mp.weixin.qq.com', 'mp.weixin.qq.com.', 'weixin.qq.com']
    result = {}
    other_count = 0
    for domain, count in sorted(counts.items(), key=lambda x: -x[1]):
        if domain in gov_domains or domain.endswith('.gov.cn'):
            result['gov.cn'] = result.get('gov.cn', 0) + count
        elif domain in weixin_domains or 'weixin' in domain:
            result['mp.weixin.qq.com'] = result.get('mp.weixin.qq.com', 0) + count
        elif domain.endswith('.gov.cn') or domain.endswith('.official.com') or domain.endswith('.gocn'):
            result[domain] = count
        else:
            other_count += count
    if other_count > 0:
        result['other'] = other_count
    return result

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Determine input pattern
    if len(sys.argv) > 1:
        date_arg = sys.argv[1]
        # Treat date argument as a prefix in data/raw/{date}_*.json
        base = Path(__file__).parent.parent / 'data' / 'raw'
        patterns = [str(base / f'{date_arg}_*.json')]
    else:
        # Default: data/raw/*.json
        base = Path(__file__).parent.parent / 'data' / 'raw'
        patterns = [str(base / '*.json')]

    print(f"[merge] Pattern: {patterns}")

    raw_items, source_files = load_raw_items(patterns)

    if not raw_items:
        print("No input files found. Exiting gracefully.")
        sys.exit(0)

    total_raw = len(raw_items)
    print(f"[merge] Loaded {total_raw} raw items from {len(source_files)} files")

    # Enrich items
    enriched = [enrich_item(item) for item in raw_items]

    # Deduplicate
    unique_items = dedupe(enriched)

    # Sort
    sorted_items = sort_items(unique_items)

    total_unique = len(sorted_items)

    # Domain stats
    counts = domain_stats(sorted_items)
    by_domain = group_by_domain(counts)

    print(f"[merge] Merged {total_raw} items from {len(source_files)} files → {total_unique} unique items")
    print("[merge] Domain distribution:")
    for domain, count in sorted(by_domain.items(), key=lambda x: -x[1]):
        print(f"  {domain}: {count}")

    # Build output
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+08:00')
    output = {
        'merged_at': now,
        'source_files': sorted(source_files),
        'total_raw': total_raw,
        'total_unique': total_unique,
        'by_domain': by_domain,
        'items': sorted_items,
    }

    # Write output
    today = datetime.now().strftime('%Y-%m-%d')
    out_dir = Path(__file__).parent.parent / 'data' / 'merged'
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f'merged_{today}.json'
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[merge] Written → {out_file}")

if __name__ == '__main__':
    main()
