import requests

r = requests.get('https://iso-clinic-v3-481780815788.europe-west1.run.app/api/enhanced-todo/pt-dbdc623a')
print(f'Status: {r.status_code}')
print(f'Response: {r.text[:500]}')
