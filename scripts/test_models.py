import requests
import os

api_key = os.environ.get('GEMINI_API_KEY')
proxies = {'http': 'http://127.0.0.1:7897', 'https': 'http://127.0.0.1:7897'}

url = f'https://generativelanguage.googleapis.com/v1beta/models?key={api_key}'
try:
    r = requests.get(url, proxies=proxies, timeout=15)
    print('Status:', r.status_code)
    if r.status_code == 200:
        data = r.json()
        for m in data.get('models', [])[:15]:
            name = m.get('name', '')
            print(' -', name)
except Exception as e:
    print('Error:', e)
