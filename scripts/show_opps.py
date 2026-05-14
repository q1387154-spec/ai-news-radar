import json
with open('data/policy-opportunities.json', 'r', encoding='utf-8') as f:
    d = json.load(f)
print('共', d['total'], '条机会')
print('评级分布:', d.get('by_level'))
print()
for p in d.get('opportunities', [])[:5]:
    s = p.get('total_score') or p.get('score', 0)
    title = p.get('title', '')[:45]
    print(f"{p.get('level')}级({s:.0f}分) | {title}")
