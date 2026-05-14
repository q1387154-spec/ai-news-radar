import requests

sources = [
    ('青浦区', 'https://www.shqp.gov.cn'),
    ('上海人社', 'https://rsj.sh.gov.cn'),
    ('国务院', 'https://www.gov.cn'),
    ('国家邮政局', 'https://www.spb.gov.cn'),
    ('上海交通', 'https://jtw.sh.gov.cn'),
]
for name, url in sources:
    try:
        r = requests.get(f'https://r.jina.ai/https://{url}', timeout=25)
        text = r.text
        lines = text.split('\n')
        title = next((l[6:].strip() for l in lines if l.startswith('Title:')), name)
        content_start = next((i for i, l in enumerate(lines) if l.startswith('Markdown Content:')), 0)
        content = '\n'.join(lines[content_start+1:])
        print(f'{name}: OK | {len(content)} chars | {title[:40]}')
    except Exception as e:
        print(f'{name}: ERROR - {e}')
