import requests
import json
import time

BASE_URL = "https://iso-clinic-v3-481780815788.europe-west1.run.app"

# Step 1: Create a new TODO
print("=" * 60)
print("Step 1: Creating new TODO")
print("=" * 60)

todo_payload = {
    "title": "Test Background TODO",
    "description": "Testing TODO creation and updates",
    "todos": [
        {
            "id": "task-1",
            "text": "First Task",
            "status": "pending",
            "agent": "Test Agent",
            "subTodos": [
                {"text": "Subtask 1.1", "status": "pending"},
                {"text": "Subtask 1.2", "status": "pending"}
            ]
        },
        {
            "id": "task-2",
            "text": "Second Task",
            "status": "pending",
            "agent": "Test Agent",
            "subTodos": [
                {"text": "Subtask 2.1", "status": "pending"}
            ]
        }
    ],
    "patientId": "pt-dbdc623a"
}

r = requests.post(f"{BASE_URL}/api/enhanced-todo", json=todo_payload, timeout=15)
print(f"Create Status: {r.status_code}")
todo_data = r.json()
todo_id = todo_data.get('id')
print(f"✅ TODO created with ID: {todo_id}")

time.sleep(1)

# Try various endpoint patterns
print("\n" + "=" * 60)
print("Testing various endpoint patterns")
print("=" * 60)

endpoints_to_test = [
    # Standard update
    ("POST", f"/api/update-todo-status", {"id": todo_id, "task_id": "task-1", "index": "", "status": "executing", "patientId": "pt-dbdc623a"}),
    # With patient in URL
    ("POST", f"/api/update-todo-status/pt-dbdc623a", {"id": todo_id, "task_id": "task-1", "status": "executing"}),
    # Enhanced todo update
    ("PUT", f"/api/enhanced-todo/{todo_id}", {"task_id": "task-1", "status": "executing", "patientId": "pt-dbdc623a"}),
    ("PATCH", f"/api/enhanced-todo/{todo_id}", {"task_id": "task-1", "status": "executing", "patientId": "pt-dbdc623a"}),
    # Patient-specific todo
    ("PUT", f"/api/enhanced-todo/pt-dbdc623a/{todo_id}", {"task_id": "task-1", "status": "executing"}),
    # Board items with patient
    ("PUT", f"/api/board-items/pt-dbdc623a/{todo_id}", {"todoData": {"todos": [{"id": "task-1", "status": "executing"}]}}),
]

for method, endpoint, payload in endpoints_to_test:
    url = BASE_URL + endpoint
    print(f"\n{method} {endpoint}")
    try:
        if method == "POST":
            r = requests.post(url, json=payload, timeout=10)
        elif method == "PUT":
            r = requests.put(url, json=payload, timeout=10)
        elif method == "PATCH":
            r = requests.patch(url, json=payload, timeout=10)
        print(f"  Status: {r.status_code}")
        print(f"  Response: {r.text[:200]}")
    except Exception as e:
        print(f"  Error: {e}")

print("\n" + "=" * 60)
print("Done testing endpoints")
print("=" * 60)
