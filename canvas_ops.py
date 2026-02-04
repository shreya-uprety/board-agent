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
CACHE_TTL_SECONDS = 300  # Cache board items for 5 MINUTES (board API has cold starts)

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
    sidebar_item = None  # Store sidebar separately to put first
    
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
            # Check if this is sidebar (contains patient info) - save separately
            if clean_item.get('id') == 'sidebar-1' or clean_item.get('componentType') == 'Sidebar':
                sidebar_item = clean_item
            else:
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

    # Put sidebar (patient info) FIRST so it's always in the context
    if sidebar_item:
        clean_data.insert(0, sidebar_item)

    return clean_data

def get_board_items(quiet=False, force_refresh=False):
    """Get all board items for current patient. Set quiet=True to reduce log noise."""
    global _board_items_cache, _cache_expiry
    
    import logging
    logger = logging.getLogger("canvas-ops")
    
    patient_id = patient_manager.get_patient_id().lower()
    url = BASE_URL + f"/api/board-items/patient/{patient_id}"
    local_path = f"{config.output_dir}/board_items_{patient_id}.json"
    
    logger.info(f"⏱️ get_board_items: START for {patient_id}")
    
    # Check in-memory cache first (unless force refresh)
    current_time = time.time()
    if not force_refresh and patient_id in _board_items_cache:
        if current_time < _cache_expiry.get(patient_id, 0):
            logger.info(f"⏱️ get_board_items: CACHE HIT (memory)")
            if not quiet:
                print(f"⚡ Using cached board items for {patient_id}")
            return _board_items_cache[patient_id]
    
    # Check local file cache BEFORE making API call (fast fallback)
    if not force_refresh and os.path.exists(local_path):
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data and len(data) > 0:
                    # Update in-memory cache from file
                    _board_items_cache[patient_id] = data
                    _cache_expiry[patient_id] = time.time() + CACHE_TTL_SECONDS
                    logger.info(f"⏱️ get_board_items: CACHE HIT (file) - {len(data)} items")
                    if not quiet:
                        print(f"📂 Using cached file for {patient_id} ({len(data)} items)")
                    return data
        except Exception as e:
            logger.warning(f"Failed to read local cache: {e}")
    
    data = []
    
    # Try fetching from API (may be slow due to Cloud Run cold start)
    logger.info(f"⏱️ get_board_items: Fetching from API...")
    try:
        if not quiet:
            print(f"🌍 Fetching from: {url}")
        response = requests.get(url, timeout=30)  # Longer timeout for Cloud Run cold starts
        
        if response.status_code == 200:
            try:
                raw_data = response.json()
                
                # Handle API format: {"patientId": "...", "items": [...]} 
                # OR nested: {"patientId": "...", "items": {"items": [...]}}
                if isinstance(raw_data, dict):
                    if 'items' in raw_data:
                        items = raw_data['items']
                        # Check for nested items.items structure
                        if isinstance(items, dict) and 'items' in items:
                            if not quiet:
                                print(f"✅ Nested API format detected (items.items)")
                            data = items['items']
                        elif isinstance(items, list):
                            if not quiet:
                                print(f"✅ Standard API format detected")
                            data = items
                        else:
                            raise ValueError(f"Unexpected items type: {type(items)}")
                    else:
                        raise ValueError("No 'items' key in response")
                elif isinstance(raw_data, list):
                    data = raw_data
                else:
                    raise ValueError(f"Unexpected response type: {type(raw_data)}")
                
                # Validate response is a list
                if not isinstance(data, list):
                    print(f"⚠️ API returned non-list data: {type(data)}")
                    raise ValueError("Expected list, got " + str(type(data)))
                
                data = board_items_process(data)
                
                # Update in-memory cache
                _board_items_cache[patient_id] = data
                _cache_expiry[patient_id] = time.time() + CACHE_TTL_SECONDS
                
                # Save to patient-specific file cache
                os.makedirs(config.output_dir, exist_ok=True)
                with open(local_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4)
                logger.info(f"⏱️ get_board_items: API SUCCESS - {len(data)} items cached")
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
        # Fall through to return empty

    # If we get here, both API and cache failed
    logger.warning(f"⏱️ get_board_items: No data available for {patient_id}")
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
    """Create enhanced TODO using API v2.0.0 /api/todos/enhanced endpoint
    This allows task objects with status and agent fields that can be updated later
    """
    url = BASE_URL + "/api/todos/enhanced"

    # API v2.0.0 enhanced expects: {title, description, todos: [{text, status, agent}], patientId}
    
    payload = {
        "title": payload_body.get("title", "Task List"),
        "description": payload_body.get("description", ""),
        "todos": payload_body.get("todos", []),  # Enhanced uses 'todos' with objects
        "patientId": patient_manager.get_patient_id()
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as response:
            with open(f"{config.output_dir}/todo_payload.json", "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=4)
            
            response_text = await response.text()
            print(f"TODO API status: {response.status}")
            
            if response.status in [200, 201]:
                try:
                    data = json.loads(response_text)
                    with open(f"{config.output_dir}/todo_response.json", "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=4)
                    return data
                except:
                    print(f"⚠️ Could not parse TODO response: {response_text[:200]}")
                    return {"id": None, "error": "Could not parse response"}
            else:
                print(f"⚠️ TODO creation failed: {response.status} - {response_text[:200]}")
                with open(f"{config.output_dir}/todo_response.json", "w", encoding="utf-8") as f:
                    json.dump({"error": response_text, "status": response.status}, f, ensure_ascii=False, indent=4)
                return {"id": None, "error": response_text}

async def update_todo(payload):
    """Update TODO status using POST /api/todos/update-status
    Payload: {id, task_id, status, patientId}
    - task_id: Use exact task_id from TODO response (e.g., "task-report-1")
    - status: "executing" or "finished"
    """
    url = BASE_URL + "/api/todos/update-status"
    
    update_payload = {
        "id": payload.get("id"),
        "task_id": payload.get("task_id"),
        "status": payload.get("status"),
        "patientId": patient_manager.get_patient_id()
    }
    
    # Add index for subtodo updates (use string format)
    if "subtodo_index" in payload:
        update_payload["index"] = str(payload.get("subtodo_index"))
    else:
        update_payload["index"] = ""

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=update_payload) as response:
            with open(f"{config.output_dir}/update_todo_payload.json", "w", encoding="utf-8") as f:
                json.dump(update_payload, f, ensure_ascii=False, indent=4)
            
            response_text = await response.text()
            print(f"Update TODO API status: {response.status}")
            
            if response.status in [200, 201]:
                try:
                    data = json.loads(response_text)
                    with open(f"{config.output_dir}/update_todo_response.json", "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=4)
                    return data
                except:
                    return {"status": "success"}
            else:
                print(f"⚠️ Update TODO failed: {response.status} - {response_text[:200]}")
                return {"status": "error", "code": response.status, "message": response_text}

async def create_lab(payload):
    """Create lab results - API expects individual lab results, so send each one separately"""
    url = BASE_URL + "/api/lab-results"
    patient_id = patient_manager.get_patient_id()
    
    lab_results = payload.get('labResults', [])
    date = payload.get('date')
    source = payload.get('source', 'Agent Generated')
    
    print(f"🧪 Sending {len(lab_results)} lab results individually...")
    
    results = []
    errors = []
    
    async with aiohttp.ClientSession() as session:
        for lab in lab_results:
            # Send each lab result with fields at top level
            unit = lab.get("unit")
            if not unit or unit == "":
                unit = "-"  # Use dash for dimensionless values like INR
            
            lab_payload = {
                "parameter": lab.get("parameter"),
                "value": lab.get("value"),
                "unit": unit,
                "status": lab.get("status"),
                "range": lab.get("range"),
                "trend": lab.get("trend", "stable"),
                "date": date,
                "source": source,
                "patientId": patient_id
            }
            
            # Validate all required fields are present
            required_fields = ["parameter", "value", "unit", "status", "range"]
            missing = [f for f in required_fields if lab_payload.get(f) is None]
            if missing:
                error_msg = f"{lab.get('parameter')}: Missing required fields: {missing}"
                errors.append(error_msg)
                print(f"  ❌ {error_msg}")
                continue
            
            try:
                async with session.post(url, json=lab_payload) as response:
                    response_text = await response.text()
                    
                    if response.status in [200, 201]:
                        try:
                            data = json.loads(response_text)
                            results.append(data)
                            print(f"  ✅ {lab.get('parameter')}: {response.status}")
                        except:
                            results.append({"status": "success", "parameter": lab.get("parameter")})
                    else:
                        error_msg = f"{lab.get('parameter')}: {response.status} - {response_text[:100]}"
                        errors.append(error_msg)
                        print(f"  ❌ {error_msg}")
                        # Debug output for failures
                        print(f"     Payload: {json.dumps(lab_payload, indent=2)[:300]}")
            except Exception as e:
                error_msg = f"{lab.get('parameter')}: {str(e)}"
                errors.append(error_msg)
                print(f"  ❌ {error_msg}")
    
    # Save for debugging
    with open(f"{config.output_dir}/lab_payload.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=4)
    
    summary = {
        "status": "success" if not errors else "partial",
        "total": len(lab_results),
        "successful": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors if errors else None
    }
    
    with open(f"{config.output_dir}/lab_response.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=4)
    
    print(f"📊 Lab results: {len(results)}/{len(lab_results)} successful")
    
    return summary

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
    print("Start create diagnostic report")
    url = BASE_URL + "/api/diagnostic-report"
    
    # AI now generates complete diagnosticData structure
    # LLM generates: {title, component, props: {diagnosticData: {...complete structure...}}}
    # Pass it through as-is
    props = payload.get('props', {})
    diagnostic_data = props.get('diagnosticData', {})
    
    api_payload = {
        'title': payload.get('title', 'DILI Diagnostic Panel'),
        'component': payload.get('component', 'DILIDiagnostic'),
        'diagnosticData': diagnostic_data,  # Complete structure from AI
        'zone': "dili-analysis-zone",
        'patientId': patient_manager.get_patient_id()
    }
    
    with open(f"{config.output_dir}/diagnosis_create_payload.json", "w", encoding="utf-8") as f:
        json.dump(api_payload, f, ensure_ascii=False, indent=4)
    
    try:
        response = requests.post(url, json=api_payload, timeout=15)
        print(f"Diagnosis API status: {response.status_code}")
        
        if response.status_code in [200, 201]:
            data = response.json()
            with open(f"{config.output_dir}/diagnosis_create_response.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            return {"status": "success", "data": data, "payload": api_payload}
        else:
            # API error - save payload locally and return it as the report
            error_text = response.text
            print(f"⚠️ Board API returned {response.status_code}, saving report locally")
            print(f"Error: {error_text}")
            with open(f"{config.output_dir}/diagnosis_create_response.json", "w", encoding="utf-8") as f:
                json.dump({"status": "local", "code": response.status_code, "error": error_text, "payload": api_payload}, f, ensure_ascii=False, indent=4)
            return {"status": "local", "message": f"Report saved locally (API returned {response.status_code})", "data": api_payload}
    except Exception as e:
        print(f"❌ Error creating diagnosis: {e}")
        with open(f"{config.output_dir}/diagnosis_create_response.json", "w", encoding="utf-8") as f:
            json.dump({"status": "error", "error": str(e), "payload": api_payload}, f, ensure_ascii=False, indent=4)
        return {"status": "local", "message": str(e), "data": api_payload}    
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
    
    # API expects patientData at root level, not inside props
    # The generate_patient_report() returns: {title, component, props: {patientData: {...}}}
    
    patient_data = {}
    if 'props' in payload and 'patientData' in payload.get('props', {}):
        patient_data = payload['props']['patientData']
    elif 'patientData' in payload:
        patient_data = payload['patientData']
    
    # Send the complete patient data structure as-is to match frontend expectations
    api_payload = {
        'title': payload.get('title', 'Patient Summary Report'),
        'component': payload.get('component', 'PatientReport'),
        'patientData': patient_data,  # Send complete nested structure
        'zone': "patient-report-zone",
        'patientId': patient_manager.get_patient_id()
    }

    with open(f"{config.output_dir}/report_create_payload.json", "w", encoding="utf-8") as f:
        json.dump(api_payload, f, ensure_ascii=False, indent=4)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=api_payload, timeout=aiohttp.ClientTimeout(total=15)) as response:
                print(f"Report API status: {response.status}")
                response_text = await response.text()
                print(f"Report API response: {response_text[:500]}")
                
                if response.status in [200, 201]:
                    try:
                        data = json.loads(response_text)
                    except:
                        data = {"raw": response_text}
                    with open(f"{config.output_dir}/report_create_response.json", "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=4)
                    return {"status": "success", "data": data, "payload": api_payload}
                else:
                    # API error - save payload locally
                    print(f"⚠️ Board API returned {response.status}, saving report locally")
                    print(f"Error body: {response_text}")
                    with open(f"{config.output_dir}/report_create_response.json", "w", encoding="utf-8") as f:
                        json.dump({"status": "local", "code": response.status, "error_body": response_text, "payload": api_payload}, f, ensure_ascii=False, indent=4)
                    return {"status": "local", "message": f"Report saved locally (API returned {response.status})", "data": api_payload}
    except Exception as e:
        print(f"❌ Error creating report: {e}")
        with open(f"{config.output_dir}/report_create_response.json", "w", encoding="utf-8") as f:
            json.dump({"status": "error", "error": str(e), "payload": payload}, f, ensure_ascii=False, indent=4)
        return {"status": "local", "message": str(e), "data": payload}
        
async def create_schedule(payload):
    """Create schedule using POST /api/components/schedule
    Payload should already be fully structured from AI generation
    """
    url = BASE_URL + "/api/components/schedule"
    
    # Ensure patientId is set
    if "patientId" not in payload:
        payload["patientId"] = patient_manager.get_patient_id()
    
    # Debug output
    print(f"🔧 Sending schedule payload: {json.dumps(payload, indent=2)[:500]}...")

    with open(f"{config.output_dir}/schedule_create_payload.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=4)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as response:
                print(f"Schedule API status: {response.status}")
                
                if response.status in [200, 201]:
                    data = await response.json()
                    with open(f"{config.output_dir}/schedule_create_response.json", "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=4)
                    return {
                        "status": "success",
                        "message": "Schedule created on board",
                        "api_response": data,
                        "id": data.get("id")
                    }
                else:
                    error_text = await response.text()
                    print(f"⚠️ Schedule API returned {response.status}: {error_text[:200]}")
                    with open(f"{config.output_dir}/schedule_create_response.json", "w", encoding="utf-8") as f:
                        json.dump({"status": "error", "code": response.status, "error": error_text}, f, ensure_ascii=False, indent=4)
                    return {
                        "status": "error",
                        "message": f"Schedule creation failed (API returned {response.status})"
                    }
    except Exception as e:
        print(f"❌ Error creating schedule: {e}")
        return {
            "status": "error",
            "message": str(e)
        }
        
async def create_notification(payload):
    """Send notification using POST /api/focus/notification"""
    url = BASE_URL + "/api/focus/notification"
    
    api_payload = {
        "message": payload.get("message", "Notification from MedForce Agent"),
        "type": payload.get("type", "info"),  # info, success, warning, error
        "patientId": patient_manager.get_patient_id()
    }

    with open(f"{config.output_dir}/notification_create_payload.json", "w", encoding="utf-8") as f:
        json.dump(api_payload, f, ensure_ascii=False, indent=4)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=api_payload, timeout=aiohttp.ClientTimeout(total=15)) as response:
                print(f"Notification API status: {response.status}")
                
                if response.status in [200, 201]:
                    data = await response.json()
                    with open(f"{config.output_dir}/notification_create_response.json", "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=4)
                    return {
                        "status": "success",
                        "message": "Notification sent to all connected clients",
                        "api_response": data
                    }
                else:
                    error_text = await response.text()
                    print(f"⚠️ Notification API returned {response.status}: {error_text[:200]}")
                    with open(f"{config.output_dir}/notification_create_response.json", "w", encoding="utf-8") as f:
                        json.dump({"status": "error", "code": response.status, "error": error_text}, f, ensure_ascii=False, indent=4)
                    return {
                        "status": "error",
                        "message": f"Notification failed (API returned {response.status})"
                    }
    except Exception as e:
        print(f"❌ Error sending notification: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

async def create_legal(payload):
    """Create legal compliance report on board"""
    url = BASE_URL + "/api/legal-compliance"
    
    # AI now generates complete legalData structure with all forms
    # LLM generates: {title, component, props: {legalData: {...complete structure...}}}
    # Pass it through as-is
    props = payload.get('props', {})
    legal_data = props.get('legalData', {})
    
    api_payload = {
        'title': payload.get('title', 'Legal Compliance Report'),
        'component': payload.get('component', 'LegalCompliance'),
        'legalData': legal_data,  # Complete structure from AI
        'zone': "medico-legal-report-zone",
        'patientId': patient_manager.get_patient_id()
    }

    with open(f"{config.output_dir}/legal_create_payload.json", "w", encoding="utf-8") as f:
        json.dump(api_payload, f, ensure_ascii=False, indent=4)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=api_payload, timeout=aiohttp.ClientTimeout(total=15)) as response:
                print(f"Legal API status: {response.status}")
                response_text = await response.text()
                print(f"Legal API response: {response_text[:500]}")
                
                if response.status in [200, 201]:
                    try:
                        data = json.loads(response_text)
                    except:
                        data = {"raw": response_text}
                    with open(f"{config.output_dir}/legal_create_response.json", "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=4)
                    return {"status": "success", "data": data, "payload": api_payload}
                else:
                    print(f"⚠️ Legal API returned {response.status}: {response_text}")
                    with open(f"{config.output_dir}/legal_create_response.json", "w", encoding="utf-8") as f:
                        json.dump({"status": "local", "code": response.status, "error": response_text, "payload": api_payload}, f, ensure_ascii=False, indent=4)
                    return {"status": "local", "message": f"Legal report saved locally (API returned {response.status})", "data": api_payload}
    except Exception as e:
        print(f"❌ Error creating legal report: {e}")
        with open(f"{config.output_dir}/legal_create_response.json", "w", encoding="utf-8") as f:
            json.dump({"status": "error", "error": str(e), "payload": api_payload}, f, ensure_ascii=False, indent=4)
        return {"status": "local", "message": str(e), "data": api_payload}