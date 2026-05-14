import requests, sys

url = 'https://www.shqp.gov.cn'
print(f'Testing Jina Reader for: {url}', file=sys.stderr)
try:
    r = requests.get(f'https://r.jina.ai/{url}', 
                    headers={"Accept": "text/plain"}, 
                    timeout=25)
    print(f'Status: {r.status_code}', file=sys.stderr)
    print(f'Response (first 400): {r.text[:400]}', file=sys.stderr)
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
