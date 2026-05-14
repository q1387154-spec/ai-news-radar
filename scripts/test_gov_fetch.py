#!/usr/bin/env python3
"""测试政府网站抓取"""

import requests
from bs4 import BeautifulSoup

test_urls = [
    ('发改委', 'https://www.ndrc.gov.cn/xxgk/zcfb/tz/'),
    ('工信部', 'https://www.miit.gov.cn/zwgk/zcwj/'),
    ('上海经信委', 'https://www.sheitc.sh.gov.cn/zwgk/tz/'),
    ('上海科委', 'https://stcsm.sh.gov.cn/zwgk/tz/'),
    ('青浦', 'http://www.shqp.gov.cn/zwgk/tzgg/'),
]

for name, url in test_urls:
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        r = requests.get(url, timeout=15, headers=headers)
        r.encoding = 'utf-8'
        soup = BeautifulSoup(r.text, 'html.parser')
        links = soup.find_all('a', href=True)
        kws = ['通知', '公告', '申报', '指南', '办法']
        policy_links = [l for l in links if any(kw in l.get_text() for kw in kws)]
        print(f'\n{name}: {r.status_code}, 找到 {len(policy_links)} 条')
        for l in policy_links[:3]:
            text = l.get_text().strip()[:35]
            href = l['href'][:70]
            print(f'  {text}')
            print(f'    -> {href}')
    except Exception as e:
        print(f'{name}: ERROR - {e}')
