#!/usr/bin/env python3
"""测试发改委页面结构"""

import requests
from bs4 import BeautifulSoup

url = "https://www.ndrc.gov.cn/xxgk/zcfb/tz/"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
}

print(f"抓取: {url}")
r = requests.get(url, headers=headers, timeout=20)
print(f"状态: {r.status_code}")
print(f"编码: {r.encoding}")
print(f"长度: {len(r.text)}")

soup = BeautifulSoup(r.text, "html.parser")

# 找所有链接
all_links = soup.find_all("a")
print(f"\n总链接数: {len(all_links)}")

# 找所有包含"通知"的链接
policy_links = [l for l in all_links if any(kw in l.get_text() for kw in ["通知", "公告", "申报", "指南"])]
print(f"政策相关链接: {len(policy_links)}")

for l in policy_links[:10]:
    text = l.get_text().strip()[:40]
    href = l.get("href", "")
    print(f"  [{text}] -> {href[:80]}")

# 打印页面中的一些文本片段
print("\n页面文本片段:")
texts = soup.get_text(separator="\n", strip=True).split("\n")
for t in texts[:30]:
    if t.strip():
        print(f"  {t[:60]}")
