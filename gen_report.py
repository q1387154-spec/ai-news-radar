"""Generate policy report - real apply-worthy policies only."""
import json, sys
from datetime import datetime

# Force UTF-8 output
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

with open('data/scored/scored_2026-05-22.json', encoding='utf-8') as f:
    data = json.load(f)

today = datetime.now().strftime('%Y-%m-%d')

EXCLUDE_TITLE = ['博览会', '展览会', '峰会', '论坛', '年会', '展会', '参展', '参会',
                 '征文', '征订', '订购',
                 '医保', '社保', '低保', '失业保险', '生育', '养老基金',
                 '学校', '教育', '培训', '学费']
EXCLUDE_URL = ['.pdf', 'xinhua', 'news.cn', 'people.com', 'cctv.com',
               'ifeng.com', '163.com', 'sina.com', 'sohu.com',
               'exhibi', 'expo', 'summit', 'meeting']
INCLUDE_TITLE = ['补贴', '资助', '奖励', '支持', '申报', '申请', '项目', '资金',
                 '认定', '政策', '办法', '方案', '通知', '指南', '意见',
                 '减负', '优惠', '减免', '扶持', '奖补', '贴息']

def is_applyable(item):
    title = item.get('title', '')
    url = item.get('url', '')
    grade = item.get('grade', 'C')
    score = item.get('score', 0)
    has_apply_kw = any(kw in title for kw in INCLUDE_TITLE)
    has_exclude = any(kw in title for kw in EXCLUDE_TITLE)
    has_exclude_url = any(kw in url.lower() for kw in EXCLUDE_URL)
    is_high = grade in ('S', 'A', 'B') or score >= 65
    return has_apply_kw and not has_exclude and not has_exclude_url and is_high

valid = []
for item in data['items']:
    dl = item.get('deadline', '')[:10] if item.get('deadline') else ''
    if not dl or dl >= today:
        valid.append(item)

valid = [item for item in valid if is_applyable(item)]
valid.sort(key=lambda x: (-x.get('score', 0), x.get('grade', 'C')))

print(f"【政策雷达日报】{today}")
print(f"总抓取: {len(data['items'])}条 | 有效可申报: {len(valid)}条")
print()

count = 0
for item in valid:
    if count >= 15:
        break
    grade = item.get('grade', '?')
    score = item.get('score', 0)
    title = item.get('title', '')
    url = item.get('url', '')
    dl = (item.get('deadline') or '长期有效')[:10]
    amt = item.get('amount', '未明确')
    channel = item.get('channel', '一般政策')
    fit = item.get('fit_summary', '')
    risk = item.get('risk_flags', [])
    rec = item.get('apply_recommendation', '')
    reqs = item.get('requirements', [])

    count += 1
    print(f"{count}. 【{grade}级-{score}分】{title}")
    print(f"   渠道: {channel} | 截止: {dl} | 金额: {amt}")
    print(f"   链接: {url}")
    if fit:
        print(f"   评估: {fit}")
    if reqs:
        print(f"   条件: {', '.join(str(r) for r in reqs[:3])}")
    if risk:
        print(f"   风险: {', '.join(str(r) for r in risk)}")
    if rec:
        print(f"   建议: {rec}")
    print()

print(f"共 {count} 条有效政策")
print("说明: 已过滤PDF报告/展会通知/新闻/行业分析/非物流政策")
