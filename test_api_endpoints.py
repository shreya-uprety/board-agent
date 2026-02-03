import requests
import json

BASE_URL = "https://iso-clinic-v3-481780815788.europe-west1.run.app"

print("=" * 60)
print("Testing if /api/update-todo-status endpoint exists")
print("=" * 60)

# Test with OPTIONS to see if endpoint exists
try:
    r = requests.options(f"{BASE_URL}/api/update-todo-status", timeout=5)
    print(f"OPTIONS: {r.status_code}")
    print(f"Allow: {r.headers.get('Allow', 'N/A')}")
except Exception as e:
    print(f"OPTIONS failed: {e}")

# Test with GET to see error type
try:
    r = requests.get(f"{BASE_URL}/api/update-todo-status", timeout=5)
    print(f"\nGET: {r.status_code}")
    print(f"Response: {r.text[:200]}")
except Exception as e:
    print(f"GET failed: {e}")

# Test with POST and empty body
try:
    r = requests.post(f"{BASE_URL}/api/update-todo-status", json={}, timeout=5)
    print(f"\nPOST (empty): {r.status_code}")
    print(f"Response: {r.text[:300]}")
except Exception as e:
    print(f"POST failed: {e}")

print("\n" + "=" * 60)
print("Checking other TODO-related endpoints")
print("=" * 60)

# Check if there's a PUT endpoint for board-items
todo_id = "enhanced-todo-1770128004630-28cu962m0"
r = requests.put(f"{BASE_URL}/api/board-items/{todo_id}", 
                  json={"todoData": {"title": "Updated"}},
                  timeout=5)
print(f"\nPUT /api/board-items/{todo_id[:20]}...")
print(f"Status: {r.status_code}")
print(f"Response: {r.text[:300]}")

# Check if there's a PATCH endpoint
r = requests.patch(f"{BASE_URL}/api/board-items/{todo_id}",
                    json={"todoData": {"title": "Updated"}},
                    timeout=5)
print(f"\nPATCH /api/board-items/{todo_id[:20]}...")
print(f"Status: {r.status_code}")
print(f"Response: {r.text[:300]}")

# Check if there's an update in the todo collection directly
r = requests.put(f"{BASE_URL}/api/enhanced-todo/{todo_id}",
                  json={"todos": [{"id": "test-1", "status": "executing"}]},
                  timeout=5)
print(f"\nPUT /api/enhanced-todo/{todo_id[:20]}...")
print(f"Status: {r.status_code}")
print(f"Response: {r.text[:300]}")
