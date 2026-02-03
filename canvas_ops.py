import requests
import json
import time
import aiohttp
import helper_model
import os
import config
from dotenv import load_dotenv
from patient_manager import patient_manager
load_dotenv()


BASE_URL = patient_manager.get_base_url()
print("#### canvas_ops.py CANVAS_URL : ",BASE_URL)
print("#### Current Patient ID: ", patient_manager.get_patient_id())

# Simple in-memory cache for board items to avoid repeated API calls
_board_items_cache = {}
_cache_expiry = {}
CACHE_TTL_SECONDS = 30  # Cache board items for 30 seconds

# Load object descriptions if available (optional)
object_desc_data = {}
existing_desc_ids = []
try:
    with open("object_desc.json", "r", encoding="utf-8") as f:
        object_desc = json.load(f)
    for o in object_desc:
        object_desc_data[o['id']] = o['description']
        existing_desc_ids.append(o['id'])
except FileNotFoundError:
    print("ℹ️ object_desc.json not found, descriptions will be skipped")
except Exception as e:
    print(f"⚠️ Error loading object_desc.json: {e}")

def board_items_process(data):
    exclude_keys = ["x","y","width","height","createdAt","updatedAt","color","rotation", "draggable"]
    clean_data = []
    
    # Validate input is a list
    if not isinstance(data, list):
        print(f"⚠️ board_items_process received non-list: {type(data)}")
        return []
    
    for item in data:
        # Skip non-dict items
        if not isinstance(item, dict):
            print(f"⚠️ Skipping non-dict item: {type(item)}")
            continue
            
        if item.get('type') == 'ehrHub' or item.get('type') == 'zone' or item.get('type') == 'button':
            pass
        else:   
            clean_item = {}
            for k,v in item.items():
                if k not in exclude_keys:
                    clean_item[k] = v
            clean_data.append(clean_item)

    for d in clean_data:
        if not d: 
            continue
        d_id = d.get('id', '')
        if 'raw' in d_id or 'single-encounter' in d_id or 'iframe' in d_id:
            if d.get('id') in existing_desc_ids:
                d['description'] = object_desc_data.get(d.get('id'), '')
        elif d.get('id') == "dashboard-item-chronomed-2":
            d['description'] = "This timeline functions similarly to a medication timeline, but with an expanded DILI assessment focus. It presents a chronological view of the patient's clinical course, aligning multiple time-bound elements to support hepatotoxicity monitoring. Like the medication timeline tracks periods of drug exposure, this object also visualises medication start/stop dates, dose changes, and hepatotoxic risk levels. In addition, it integrates encounter history, longitudinal liver function test trends, and critical clinical events. Temporal relationships are highlighted to show how changes in medication correlate with laboratory abnormalities and clinical deterioration, providing causality links relevant to DILI analysis. The timeline is designed to facilitate retrospective assessment and ongoing monitoring by showing when key events occurred in relation to medication use and liver injury progression."
        elif 'dashboard-item' in d_id:
            if d.get('type') == 'component':
                if d.get('id') in existing_desc_ids:
                    d['description'] = object_desc_data.get(d.get('id'), '')
        elif d.get('id') == "sidebar-1":
            pass
        elif d.get('type') == 'component':
                if d.get('id') in existing_desc_ids:
                    d['description'] = object_desc_data.get(d.get('id'), '')

    return clean_data

def get_board_items(quiet=False, force_refresh=False):
    """Get all board items for current patient. Set quiet=True to reduce log noise."""
    global _board_items_cache, _cache_expiry
    
    patient_id = patient_manager.get_patient_id().lower()
    url = BASE_URL + f"/api/board-items/patient/{patient_id}"
    
    # Check cache first (unless force refresh)
    current_time = time.time()
    if not force_refresh and patient_id in _board_items_cache:
        if current_time < _cache_expiry.get(patient_id, 0):
            if not quiet:
                print(f"⚡ Using cached board items for {patient_id}")
            return _board_items_cache[patient_id]
    
    data = []
    
    # 1. Try fetching from API with short timeout
    try:
        if not quiet:
            print(f"🌍 Fetching from: {url}")
        response = requests.get(url, timeout=3)
        
        if response.status_code == 200:
            try:
                data = response.json()
                
                # Handle new API format: {"patientId": "...", "items": [...]}
                if isinstance(data, dict) and 'items' in data:
                    if not quiet:
                        print(f"✅ New API format detected, extracting items")
                    data = data['items']
                
                # Validate response is a list
                if not isinstance(data, list):
                    print(f"⚠️ API returned non-list data: {type(data)}")
                    raise ValueError("Expected list, got " + str(type(data)))
                
                data = board_items_process(data)
                
                # Update in-memory cache
                _board_items_cache[patient_id] = data
                _cache_expiry[patient_id] = time.time() + CACHE_TTL_SECONDS
                
                # Save to file cache
                os.makedirs(config.output_dir, exist_ok=True)
                with open(f"{config.output_dir}/board_items.json", "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4)
                if not quiet:
                    print(f"✅ Fetched {len(data)} items from API")
                return data
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                if not quiet:
                    print(f"❌ Invalid JSON response from API: {e}")
                    print(f"   Response text: {response.text[:200]}...")
                # Fall through to cache fallback
        else:
            if not quiet:
                print(f"⚠️ API Error: Status {response.status_code}")
                try:
                    error_text = response.text[:200] if hasattr(response, 'text') else str(response)[:200]
                    print(f"   Response: {error_text}...")
                except:
                    print(f"   Response: Could not read error response")
            # Fall through to cache fallback
            
    except Exception as e:
        if not quiet:
            print(f"❌ API request failed: {e}")
        # Fall through to cache fallback

    # 2. Fallback to local file (reached if API fails or returns non-200)
    local_path = f"{config.output_dir}/board_items.json"
    if os.path.exists(local_path):
        if not quiet:
            print(f"📂 Falling back to local cache: {local_path}")
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not quiet:
                    print(f"✅ Loaded {len(data)} items from cache")
                return data
        except Exception as e:
            if not quiet:
                print(f"❌ Failed to load local cache: {e}")
    else:
        if not quiet:
            print(f"⚠️ No local cache found at {local_path}")
            
    return []


async def initiate_easl_iframe(question):
    url = BASE_URL + "/api/send-to-easl"
    payload = {
        "patientId": patient_manager.get_patient_id(),
        "query": question,
        "metadata": {
            "source": "voice"
        }
    }

    headers = {
        "Content-Type": "application/json"
    }
    with open(f"{config.output_dir}/initiate_iframe_payload.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=4)
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        print(f"Initiate EASL iframe: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            with open(f"{config.output_dir}/initiate_iframe_response.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            return {
                "status": "success",
                "message": "Query sent to EASL iframe",
                "api_response": data,
                "query_sent": question[:500] + "..." if len(question) > 500 else question
            }
        else:
            print(f"⚠️ EASL API returned {response.status_code}")
            return {
                "status": "error",
                "message": f"EASL API returned {response.status_code}",
                "query_sent": question[:500] + "..." if len(question) > 500 else question
            }
    except Exception as e:
        print(f"❌ Error sending to EASL: {e}")
        return {
            "status": "error",
            "message": str(e),
            "query_sent": question[:500] + "..." if len(question) > 500 else question
        }

async def get_agent_question(question):
    context_str = await helper_model.generate_question(question)


    return context_str

async def get_agent_context(question):
    context_str = await helper_model.generate_context(question)


    return context_str

async def get_agent_answer(todo):
    data = await helper_model.generate_response(todo)

    result = {}
    result['content'] = data.get('answer', '')
    if todo.get('title'):
        result['title'] = todo.get('title', '').lower().replace("to do", "Result").capitalize()

    return result



async def focus_item(item_id):

    url = BASE_URL + "/api/focus"
    payload = {
        "patientId": patient_manager.get_patient_id(),
        "objectId": item_id,
        "focusOptions": {
            "zoom": 0.5
        }
    }
    print("Focus URL:",url)
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as response:
            with open(f"{config.output_dir}/focus_payload.json", "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=4)
            data = await response.json()
            with open(f"{config.output_dir}/focus_response.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            return data

async def create_todo(payload_body):

    url = BASE_URL + "/api/enhanced-todo"

    payload = payload_body
    payload["patientId"] = patient_manager.get_patient_id()

    # response = requests.post(url, json=payload)
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as response:
            with open(f"{config.output_dir}/todo_payload.json", "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=4)
            data = await response.json()
            with open(f"{config.output_dir}/todo_response.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            return data

async def update_todo(payload):
    url = BASE_URL + "/api/update-todo-status"
    payload["patientId"] = patient_manager.get_patient_id()

    # response = requests.post(url, json=payload)
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as response:
            with open(f"{config.output_dir}/upadate_todo_payload.json", "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=4)
            data = await response.json()
            # print("Update todo :", data)
            with open(f"{config.output_dir}/upadate_todo_response.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            return data

async def create_lab(payload):
   
    url = BASE_URL + "/api/lab-results"
    payload["patientId"] = patient_manager.get_patient_id()
    

    # response = requests.post(url, json=payload)
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as response:
            with open(f"{config.output_dir}/lab_payload.json", "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=4)

            data = await response.json()

            with open(f"{config.output_dir}/lab_response.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            return data

async def create_result(agent_result):
    url = BASE_URL + "/api/agents"
    
    payload = agent_result
    payload["patientId"] = patient_manager.get_patient_id()

    # response = requests.post(url, json=payload)
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as response:
            with open(f"{config.output_dir}/agentres_payload.json", "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=4)

            data = await response.json()

            with open(f"{config.output_dir}/agentres_response.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            return data
        
def create_diagnosis(payload):
    print("Start create object")
    url = BASE_URL + "/api/dili-diagnostic"
    payload['zone'] = "dili-analysis-zone"
    payload['patientId'] = patient_manager.get_patient_id()
    with open(f"{config.output_dir}/diagnosis_create_payload.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=4)
    
    try:
        response = requests.post(url, json=payload, timeout=15)
        print(f"Diagnosis API status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            with open(f"{config.output_dir}/diagnosis_create_response.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            return {"status": "success", "data": data, "payload": payload}
        else:
            # API error - save payload locally and return it as the report
            print(f"⚠️ Board API returned {response.status_code}, saving report locally")
            with open(f"{config.output_dir}/diagnosis_create_response.json", "w", encoding="utf-8") as f:
                json.dump({"status": "local", "payload": payload}, f, ensure_ascii=False, indent=4)
            return {"status": "local", "message": f"Report saved locally (API returned {response.status_code})", "data": payload}
    except Exception as e:
        print(f"❌ Error creating diagnosis: {e}")
        with open(f"{config.output_dir}/diagnosis_create_response.json", "w", encoding="utf-8") as f:
            json.dump({"status": "error", "error": str(e), "payload": payload}, f, ensure_ascii=False, indent=4)
        return {"status": "local", "message": str(e), "data": payload}    
    # async with aiohttp.ClientSession() as session:
    #     async with session.post(url, json=payload) as response:
    #         with open(f"{config.output_dir}/diagnosis_create_payload.json", "w", encoding="utf-8") as f:
    #             json.dump(payload, f, ensure_ascii=False, indent=4)

    #         data = await response.json()
    #         print("Object created")
    #         with open(f"{config.output_dir}/diagnosis_create_response.json", "w", encoding="utf-8") as f:
    #             json.dump(data, f, ensure_ascii=False, indent=4)
    #         return data
        
async def create_report(payload):
    url = BASE_URL + "/api/patient-report"
    payload['zone'] = "dili-analysis-zone"
    payload['patientId'] = patient_manager.get_patient_id()

    with open(f"{config.output_dir}/report_create_payload.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=4)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as response:
                print(f"Report API status: {response.status}")
                
                if response.status == 200:
                    data = await response.json()
                    with open(f"{config.output_dir}/report_create_response.json", "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=4)
                    return {"status": "success", "data": data, "payload": payload}
                else:
                    # API error - save payload locally
                    print(f"⚠️ Board API returned {response.status}, saving report locally")
                    with open(f"{config.output_dir}/report_create_response.json", "w", encoding="utf-8") as f:
                        json.dump({"status": "local", "payload": payload}, f, ensure_ascii=False, indent=4)
                    return {"status": "local", "message": f"Report saved locally (API returned {response.status})", "data": payload}
    except Exception as e:
        print(f"❌ Error creating report: {e}")
        with open(f"{config.output_dir}/report_create_response.json", "w", encoding="utf-8") as f:
            json.dump({"status": "error", "error": str(e), "payload": payload}, f, ensure_ascii=False, indent=4)
        return {"status": "local", "message": str(e), "data": payload}
        
async def create_schedule(payload):
    url = BASE_URL + "/api/schedule"
    
    # API requires patientId and schedulingContext
    scheduling_context = payload.get("schedulingContext") or payload.get("description") or payload.get("title") or "Follow-up appointment scheduling"
    
    api_payload = {
        "patientId": patient_manager.get_patient_id(),
        "schedulingContext": scheduling_context
    }

    with open(f"{config.output_dir}/schedule_create_payload.json", "w", encoding="utf-8") as f:
        json.dump(api_payload, f, ensure_ascii=False, indent=4)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=api_payload, timeout=aiohttp.ClientTimeout(total=15)) as response:
                print(f"Schedule API status: {response.status}")
                
                if response.status in [200, 201]:
                    data = await response.json()
                    with open(f"{config.output_dir}/schedule_create_response.json", "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=4)
                    return {
                        "status": "success",
                        "message": "Schedule panel created on board",
                        "api_response": data,
                        "payload_sent": api_payload
                    }
                else:
                    print(f"⚠️ Schedule API returned {response.status}")
                    with open(f"{config.output_dir}/schedule_create_response.json", "w", encoding="utf-8") as f:
                        json.dump({"status": "error", "code": response.status}, f, ensure_ascii=False, indent=4)
                    return {
                        "status": "local",
                        "message": f"Schedule saved locally (API returned {response.status})",
                        "payload_sent": api_payload
                    }
    except Exception as e:
        print(f"❌ Error creating schedule: {e}")
        return {
            "status": "error",
            "message": str(e),
            "payload_sent": payload
        }
        
async def create_notification(payload):
    url = BASE_URL + "/api/send-notification"
    
    # API only accepts patientId and message - no type field
    api_payload = {
        "patientId": patient_manager.get_patient_id(),
        "message": payload.get("message", "Notification from MedForce Agent")
    }

    with open(f"{config.output_dir}/notification_create_payload.json", "w", encoding="utf-8") as f:
        json.dump(api_payload, f, ensure_ascii=False, indent=4)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=api_payload, timeout=aiohttp.ClientTimeout(total=15)) as response:
                print(f"Notification API status: {response.status}")
                
                if response.status == 200:
                    data = await response.json()
                    with open(f"{config.output_dir}/notification_create_response.json", "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=4)
                    return {
                        "status": "success",
                        "message": "Notification sent to board",
                        "api_response": data,
                        "payload_sent": api_payload
                    }
                else:
                    print(f"⚠️ Notification API returned {response.status}")
                    with open(f"{config.output_dir}/notification_create_response.json", "w", encoding="utf-8") as f:
                        json.dump({"status": "error", "code": response.status}, f, ensure_ascii=False, indent=4)
                    return {
                        "status": "local",
                        "message": f"Notification saved locally (API returned {response.status})",
                        "payload_sent": api_payload
                    }
    except Exception as e:
        print(f"❌ Error sending notification: {e}")
        return {
            "status": "error",
            "message": str(e),
            "payload_sent": payload
        }
