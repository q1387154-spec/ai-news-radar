#!/usr/bin/env python3
"""调试发改委页面 - 保存完整HTML"""

import requests
from bs4 import BeautifulSoup

url = "https://www.ndrc.gov.cn/xxgk/zcfb/tz/"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

r = requests.get(url, headers=headers, timeout=20)
r.encoding = 'utf-8'  # 强制用utf-8

# 保存HTML
with open("debug_ndrc.html", "w", encoding="utf-8") as f:
    f.write(r.text)
print(f"已保存 {len(r.text)} 字节到 debug_ndrc.html")

soup = BeautifulSoup(r.text, "html.parser")

# 找所有链接
all_links = soup.find_all("a")
print(f"总链接: {len(all_links)}")

# 打印前20个链接的文本和href
for i, l in enumerate(all_links[:30]):
    text = l.get_text(strip=True)
    href = l.get("href", "")
    if text and len(text) > 5:
        print(f"{i}: [{text[:30]}] -> {href[:60]}")
