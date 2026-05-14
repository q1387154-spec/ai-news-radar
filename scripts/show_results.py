import json
with open('data/policy-opportunities.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
print('共生成', data['total'], '条机会')
print()
opps = data.get('opportunities', [])
for p in opps:
    title = p.get('title') or p.get('policy_title', 'N/A')
    score = p.get('total_score') or p.get('score', 0)
    level = p.get('level', 'N/A')
    print(f"级别:{level} | 评分:{score:.1f} | {title[:50]}")
