import json
from datetime import datetime

with open('data/scored/scored_2026-05-22.json', encoding='utf-8') as f:
    data = json.load(f)

today = datetime.now().strftime('%Y-%m-%d')
valid = []
expired = []
no_deadline = []

for item in data['items']:
    dl = item.get('deadline', '')[:10] if item.get('deadline') else ''
    if not dl:
        no_deadline.append(item)
    elif dl >= today:
        valid.append(item)
    else:
        expired.append(item)

valid.sort(key=lambda x: -x.get('score', 0))
print(f'Total: {len(data["items"])}')
print(f'Valid (not expired): {len(valid)}')
print(f'Expired: {len(expired)}')
print(f'No deadline: {len(no_deadline)}')
print()
print('=== Top 15 Valid (by score) ===')
for i, item in enumerate(valid[:15], 1):
    dl = item.get('deadline', '无截止')[:10] if item.get('deadline') else '无截止'
    grade = item.get('grade', '?')
    score = item.get('score', 0)
    title = item.get('title', '')[:50]
    amt = item.get('amount', '')
    channel = item.get('channel', '')
    fit = item.get('fit_summary', '')[:30]
    print(f'{i:2d}. [{grade}{score}] {title}')
    print(f'    截止:{dl} | {amt} | {channel}')
    print(f'    {fit}')
    print()
