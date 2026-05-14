import requests

url = 'https://r.jina.ai/https://www.shqp.gov.cn'
r = requests.get(url, timeout=25)
print(f'Status: {r.status_code}')
print(f'Content-Type: {r.headers.get("content-type")}')
print(f'Response (first 1000): {r.text[:1000]}')
