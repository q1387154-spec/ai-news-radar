import requests
from bs4 import BeautifulSoup
import sys

sys.stdout.reconfigure(encoding='utf-8')

r = requests.get('https://www.mofcom.gov.cn/zcfb/', headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
print('Status:', r.status_code)

soup = BeautifulSoup(r.text, 'html.parser')

links = []
for a in soup.find_all('a', href=True)[:30]:
    t = a.get_text(strip=True)[:40]
    h = a['href']
    if t and len(t) > 5:
        links.append((t, h))

for t, h in links[:15]:
    print(t[:35], '->', h[:70])
