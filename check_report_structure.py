import requests
import json

r = requests.get('https://iso-clinic-v3-481780815788.europe-west1.run.app/api/board-items/patient/pt-dbdc623a')
data = r.json()
items = data.get('items', {}).get('items', []) if isinstance(data.get('items'), dict) else data.get('items', [])

# List ALL item types to see what's on the board
types = {}
for item in items:
    t = item.get('type', 'unknown')
    types[t] = types.get(t, 0) + 1

print("All item types on board:")
for t, count in sorted(types.items()):
    print(f"  {t}: {count}")

# Check for component types
print("\nComponent types:")
for item in items:
    if item.get('componentType'):
        print(f"  {item.get('id')}: componentType={item.get('componentType')}")

