import requests
import os
import time

api_key = os.environ.get('GEMINI_API_KEY', '')
proxies = {'http': 'http://127.0.0.1:7897', 'https': 'http://127.0.0.1:7897'}

models = [
    'gemini-2.0-flash',
    'gemini-2.0-flash-exp',
    'gemini-1.5-flash',
    'gemini-1.5-flash-001',
    'gemini-1.5-flash-002',
]

for model in models:
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
    payload = {
        'contents': [{'parts': [{'text': 'Say hi'}]}],
        'generationConfig': {'temperature': 0.1, 'maxOutputTokens': 5}
    }
    headers = {'Content-Type': 'application/json', 'X-Goog-API-Key': api_key}

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=20, proxies=proxies)
        print(f'{model}: {r.status_code}')
        if r.status_code == 200:
            print('  SUCCESS!')
            break
        elif r.status_code == 429:
            print('  Rate limited, waiting...')
            time.sleep(10)
    except Exception as e:
        print(f'{model}: ERROR - {str(e)[:50]}')
    time.sleep(2)
