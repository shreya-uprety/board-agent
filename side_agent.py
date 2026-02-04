"""
Side Agent - Combined version with animated TODOs, error handling, and async background processing
Provides tool routing, canvas operations, and report generation for the clinic-sim-pipeline
"""

from google.genai.types import GenerateContentConfig
import google.generativeai as genai
import time
import json
import asyncio
import os
import random
import threading
import httpx
from dotenv import load_dotenv
import requests
import aiohttp
import config
import canvas_ops
load_dotenv()
import helper_model
from patient_manager import patient_manager

# Configuration
BASE_URL = patient_manager.get_base_url()
print("#### side_agent.py CANVAS_URL:", BASE_URL)
print("#### Current Patient ID:", patient_manager.get_patient_id())

# Lazy initialization - configure only when needed
_genai_configured = False
_cached_models = {}

def _ensure_genai_configured():
    global _genai_configured
    if not _genai_configured:
        genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
        _genai_configured = True

def _get_model(system_prompt_file: str = None):
    """Get or create cached model instance"""
    global _cached_models
    _ensure_genai_configured()
    
    cache_key = system_prompt_file or "default"
    if cache_key not in _cached_models:
        system_prompt = ""
        if system_prompt_file:
            try:
                with open(system_prompt_file, "r", encoding="utf-8") as f:
                    system_prompt = f.read()
            except:
                pass
        _cached_models[cache_key] = genai.GenerativeModel(
            "gemini-2.0-flash",  # Faster model
            system_instruction=system_prompt if system_prompt else None
        )
    return _cached_models[cache_key]

MODEL = "gemini-2.0-flash"  # Faster model

# ============================================================================
# TOOL PARSING - Route user queries to appropriate tools
# ============================================================================

def parse_tool(query):
    """Parse user query and route to appropriate tool - with fast keyword matching first"""
    q_lower = query.lower()
    
    # Fast keyword matching for common patterns (avoids Gemini API call)
    if any(kw in q_lower for kw in ['easl', 'guideline', 'clinical guideline', 'recommendation']):
        return {"query": query, "tool": "get_easl_answer"}
    if any(kw in q_lower for kw in ['navigate', 'go to', 'show me', 'focus on', 'zoom to']):
        return {"query": query, "tool": "navigate_canvas"}
    if any(kw in q_lower for kw in ['create task', 'add task', 'todo', 'to-do', 'reminder']):
        return {"query": query, "tool": "generate_task"}
    if any(kw in q_lower for kw in ['schedule', 'appointment', 'follow-up', 'follow up']):
        return {"query": query, "tool": "create_schedule"}
    if any(kw in q_lower for kw in ['notify', 'notification', 'alert', 'send message']):
        return {"query": query, "tool": "send_notification"}
    if any(kw in q_lower for kw in ['diagnosis', 'dili diagnosis', 'liver injury diagnosis']):
        return {"query": query, "tool": "generate_diagnosis"}
    if any(kw in q_lower for kw in ['patient report', 'summary report', 'generate report']):
        return {"query": query, "tool": "generate_patient_report"}
    if any(kw in q_lower for kw in ['legal', 'legal report', 'compliance']):
        return {"query": query, "tool": "generate_legal_report"}
    
    # Default to general Q&A for most queries (no tool needed)
    # This avoids the slow Gemini API call for simple questions
    return {"query": query, "tool": "general"}


# ============================================================================
# NAVIGATION - Focus on board items
# ============================================================================

async def resolve_object_id(query: str, context: str = ""):
    """Resolve user query to a board object ID and focus on it"""
    # Get board items using canvas_ops (has proper error handling and cache fallback)
    try:
        data = canvas_ops.get_board_items(quiet=True)  # Use quiet mode to reduce log noise
        
        board_items = []
        for item in data:
            if not isinstance(item, dict):
                continue  # Skip invalid items
            
            item_type = item.get('item_type', item.get('type', ''))
            if item_type == 'content':
                item_content = item.get('content', {})
                board_items.append({
                    "object_id": item.get('object_id', item.get('id')),
                    "item_type": item_type,
                    "title": item_content.get('title', ''),
                    "component": item_content.get('component', item.get('componentType', '')),
                })
            else:
                board_items.append({
                    "object_id": item.get('object_id', item.get('id')),
                    "componentType": item.get('componentType', ''),
                    "title": item.get('title', ''),
                })
    except Exception as e:
        print(f"❌ Error processing board items: {e}")
        board_items = []

    RESPONSE_SCHEMA = {
        "type": "OBJECT",
        "properties": {
            "objectId": {"type": "STRING", "description": "Resolved object ID."}
        },
        "required": ["objectId"]
    }

    model = _get_model("system_prompts/objectid_parser.md")
    prompt = f"User query : '{query}'\n\nBoard items: {json.dumps(board_items[:20])}"  # Limit items for speed
    
    response = model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
            temperature=0.1,
        )
    )

    result = json.loads(response.text)
    object_id = result.get('objectId')
    print(f"🎯 ObjectID Resolved: {object_id}")
    
    # Focus on the item
    focus_result = await canvas_ops.focus_item(object_id)
    return {"object_id": object_id, "focus_result": focus_result}


# ============================================================================
# EASL - Send clinical questions to EASL with animated TODO workflow
# ============================================================================

async def prepare_easl_query(question: str):
    """
    Prepare an EASL query by generating context and refined question.
    Returns the prepared data for frontend to use - does NOT send to board.
    
    Frontend can then:
    1. Display the prepared context/question to user
    2. Call board's EASL iframe API directly
    3. Or call /api/canvas/send-to-easl to let backend handle it
    """
    print("📝 Preparing EASL query (no send)...")
    
    try:
        # Load prompts
        with open("system_prompts/context_agent.md", "r", encoding="utf-8") as f:
            SYSTEM_PROMPT_CONTEXT = f.read()
        with open("system_prompts/question_gen.md", "r", encoding="utf-8") as f:
            SYSTEM_PROMPT_QUESTION = f.read()
        
        # Load EHR data
        ehr_data = await helper_model.load_ehr()
        
        # Generate clinical context
        model = genai.GenerativeModel(MODEL, system_instruction=SYSTEM_PROMPT_CONTEXT)
        prompt = f"Please generate context for: Question: {question}\n\nRaw data: {ehr_data}"
        resp = model.generate_content(prompt)
        context_result = resp.text.replace("```markdown", " ").replace("```", "")
        
        # Generate refined question
        model = genai.GenerativeModel(MODEL, system_instruction=SYSTEM_PROMPT_QUESTION)
        prompt = f"Please generate proper question: Question: {question}\n\nRaw data: {ehr_data}"
        resp = model.generate_content(prompt)
        refined_question = resp.text.replace("```markdown", " ").replace("```", "")
        
        # Build the full query for EASL
        full_query = f"Context: {context_result}\n\nQuestion: {refined_question}"
        
        # Get patient info for frontend
        patient_id = patient_manager.get_patient_id()
        base_url = patient_manager.get_base_url()
        
        return {
            "status": "prepared",
            "original_question": question,
            "generated_context": context_result,
            "refined_question": refined_question,
            "full_query": full_query,
            "patient_id": patient_id,
            "board_easl_endpoint": f"{base_url}/api/board/{patient_id}/easl",
            "board_easl_payload": {
                "patientId": patient_id,
                "query": full_query
            },
            "usage_instructions": {
                "option_1": "Frontend can POST to board_easl_endpoint with board_easl_payload",
                "option_2": "Frontend can call /api/canvas/send-to-easl to let backend send (with TODO animation)",
                "option_3": "Frontend can display context/question to user for review before sending"
            }
        }
        
    except Exception as e:
        print(f"❌ Error preparing EASL query: {e}")
        return {
            "status": "error",
            "message": str(e),
            "original_question": question
        }


async def trigger_easl(question):
    """Send clinical question to EASL with animated TODO progress"""
    print("🚀 Starting EASL workflow...")
    
    # Create TODO workflow on board for visual feedback
    easl_todo_payload = {
        "title": "EASL Guideline Query Workflow",
        "description": f"Processing EASL query: {question[:100]}...",
        "todos": [
            {
                "id": "task-context",
                "text": "Generating clinical context",
                "status": "pending",
                "agent": "Context Agent",
                "subTodos": [
                    {"text": f"Base question: {question[:80]}...", "status": "pending"},
                    {"text": "Extracting relevant patient data", "status": "pending"},
                    {"text": "Building EASL-compatible context", "status": "pending"}
                ]
            },
            {
                "id": "task-query",
                "text": "Sending query to EASL",
                "status": "pending",
                "agent": "EASL Agent",
                "subTodos": [
                    {"text": "Formatting question for guidelines", "status": "pending"},
                    {"text": "Submitting to EASL iframe", "status": "pending"}
                ]
            }
        ]
    }
    
    # Create the TODO and start background animation
    todo_obj = await canvas_ops.create_todo(easl_todo_payload)
    todo_id = todo_obj.get('id')
    
    # Start background TODO animation (non-blocking)
    asyncio.create_task(_animate_easl_todo(todo_id, question))
    
    return {
        "status": "processing",
        "message": "EASL query initiated - check board for progress",
        "todo_id": todo_id,
        "question": question
    }


async def _animate_easl_todo(todo_id: str, question: str):
    """Background task to animate TODO and process EASL query"""
    try:
        # Phase 1: Context Generation
        await canvas_ops.update_todo({"id": todo_id, "task_id": "task-context", "index": "", "status": "executing"})
        
        # Load prompts
        with open("system_prompts/context_agent.md", "r", encoding="utf-8") as f:
            SYSTEM_PROMPT_CONTEXT = f.read()
        with open("system_prompts/question_gen.md", "r", encoding="utf-8") as f:
            SYSTEM_PROMPT_QUESTION = f.read()
        
        ehr_data = await helper_model.load_ehr()
        
        # Update subtodo 0
        await canvas_ops.update_todo({"id": todo_id, "task_id": "task-context", "index": "0", "status": "finished"})
        await asyncio.sleep(0.5)
        
        # Generate context
        model = genai.GenerativeModel(MODEL, system_instruction=SYSTEM_PROMPT_CONTEXT)
        prompt = f"Please generate context for: Question: {question}\n\nRaw data: {ehr_data}"
        resp = model.generate_content(prompt)
        context_result = resp.text.replace("```markdown", " ").replace("```", "")
        
        with open(f"{config.output_dir}/context.md", "w", encoding="utf-8") as f:
            f.write(context_result)
        
        await canvas_ops.update_todo({"id": todo_id, "task_id": "task-context", "index": "1", "status": "finished"})
        await asyncio.sleep(0.5)
        
        # Generate refined question
        model = genai.GenerativeModel(MODEL, system_instruction=SYSTEM_PROMPT_QUESTION)
        prompt = f"Please generate proper question: Question: {question}\n\nRaw data: {ehr_data}"
        resp = model.generate_content(prompt)
        q_gen_result = resp.text.replace("```markdown", " ").replace("```", "")
        
        with open(f"{config.output_dir}/question.md", "w", encoding="utf-8") as f:
            f.write(q_gen_result)
        
        await canvas_ops.update_todo({"id": todo_id, "task_id": "task-context", "index": "2", "status": "finished"})
        await asyncio.sleep(0.3)
        await canvas_ops.update_todo({"id": todo_id, "task_id": "task-context", "index": "", "status": "finished"})
        
        # Phase 2: Send to EASL
        await canvas_ops.update_todo({"id": todo_id, "task_id": "task-query", "index": "", "status": "executing"})
        await asyncio.sleep(0.5)
        
        await canvas_ops.update_todo({"id": todo_id, "task_id": "task-query", "index": "0", "status": "finished"})
        
        # Send to EASL iframe
        full_question = f"Context: {context_result}\n\nQuestion: {q_gen_result}"
        easl_result = await canvas_ops.initiate_easl_iframe(full_question)
        
        await canvas_ops.update_todo({"id": todo_id, "task_id": "task-query", "index": "1", "status": "finished"})
        await asyncio.sleep(0.3)
        await canvas_ops.update_todo({"id": todo_id, "task_id": "task-query", "index": "", "status": "finished"})
        
        # Focus on EASL iframe
        await canvas_ops.focus_item("iframe-item-easl-interface")
        
        print(f"✅ EASL workflow completed")
        
    except Exception as e:
        print(f"❌ EASL workflow error: {e}")
        # Mark as failed but don't crash
        try:
            await canvas_ops.update_todo({"id": todo_id, "task_id": "task-query", "index": "", "status": "finished"})
        except:
            pass


# ============================================================================
# TASK WORKFLOW - Generate and execute tasks with background processing
# ============================================================================

async def generate_task_workflow(query: str):
    """Generate a task workflow and process it in background"""
    with open("system_prompts/task_generator.md", "r", encoding="utf-8") as f:
        SYSTEM_PROMPT = f.read()

    RESPONSE_SCHEMA = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "todos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "text": {"type": "string"},
                        "status": {"type": "string", "enum": ["pending", "executing", "finished"]},
                        "agent": {"type": "string"},
                        "subTodos": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "text": {"type": "string"},
                                    "status": {"type": "string", "enum": ["pending", "executing", "finished"]}
                                },
                                "required": ["text", "status"]
                            }
                        }
                    },
                    "required": ["id", "text", "status", "agent", "subTodos"]
                }
            }
        },
        "required": ["title", "description", "todos"]
    }

    ehr_data = await load_ehr()
    prompt = f"User request:\n{query}\n\nPatient data: {ehr_data}\n\nGenerate the task workflow JSON."

    model = genai.GenerativeModel(MODEL, system_instruction=SYSTEM_PROMPT)
    resp = model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
            temperature=0.7,
        )
    )
    
    todo_json = json.loads(resp.text)
    with open(f"{config.output_dir}/generate_task_workflow.json", "w", encoding="utf-8") as f:
        json.dump(todo_json, f, ensure_ascii=False, indent=4)

    # Create TODO on board
    task_res = await canvas_ops.create_todo(todo_json)
    
    # Start background processing (non-blocking)
    asyncio.create_task(_process_task_workflow(todo_json, task_res))
    
    return {
        "status": "processing",
        "message": "Task workflow created - processing in background",
        "todo_id": task_res.get('id'),
        "workflow": todo_json
    }


async def _process_task_workflow(todo_json: dict, todo_obj: dict):
    """Background task to animate and process the workflow"""
    try:
        todo_id = todo_obj.get("id")
        
        for task in todo_json.get('todos', []):
            task_id = task.get('id')
            
            # Mark task as executing
            await canvas_ops.update_todo({"id": todo_id, "task_id": task_id, "index": "", "status": "executing"})
            
            # Process subtodos
            for i, subtodo in enumerate(task.get('subTodos', [])):
                await asyncio.sleep(random.uniform(0.3, 0.8))
                await canvas_ops.update_todo({"id": todo_id, "task_id": task_id, "index": str(i), "status": "finished"})
            
            # Mark task as finished
            await asyncio.sleep(random.uniform(0.2, 0.5))
            await canvas_ops.update_todo({"id": todo_id, "task_id": task_id, "index": "", "status": "finished"})
        
        # Generate response and post to board
        response_data = await generate_response(todo_json)
        agent_result = {
            'content': response_data.get('answer', ''),
            'title': todo_json.get('title', 'Analysis Result').replace("To Do", "Result"),
            'zone': "raw-ehr-data-zone"
        }
        
        await canvas_ops.create_result(agent_result)
        print(f"✅ Task workflow completed: {todo_id}")
        
    except Exception as e:
        print(f"❌ Task workflow error: {e}")


async def generate_todo(query: str):
    """Generate a simple TODO (without background processing)"""
    with open("system_prompts/task_generator.md", "r", encoding="utf-8") as f:
        SYSTEM_PROMPT = f.read()

    ehr_data = await load_ehr()
    prompt = f"User request:\n{query}\n\nPatient data: {ehr_data}\n\nGenerate the task workflow JSON."

    model = genai.GenerativeModel(MODEL, system_instruction=SYSTEM_PROMPT)
    resp = model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.7,
        )
    )
    
    result = json.loads(resp.text)
    with open(f"{config.output_dir}/generate_todo.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=4)

    response = await canvas_ops.create_todo(result)
    return response


# ============================================================================
# EHR DATA LOADING
# ============================================================================

async def load_ehr():
    """Load EHR data from board items"""
    print("📊 Loading EHR data...")
    try:
        data = canvas_ops.get_board_items()
        with open(f"{config.output_dir}/ehr_data.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        return data
    except Exception as e:
        print(f"❌ Error loading EHR: {e}")
        return []


async def generate_response(todo_obj):
    """Generate clinical response for a TODO"""
    with open("system_prompts/clinical_agent.md", "r", encoding="utf-8") as f:
        SYSTEM_PROMPT = f.read()
    
    model = genai.GenerativeModel(MODEL, system_instruction=SYSTEM_PROMPT)
    ehr_data = await load_ehr()
    
    prompt = f"""Please execute this todo: {todo_obj}

This is patient encounter data: {ehr_data}"""

    resp = model.generate_content(prompt)
    
    with open(f"{config.output_dir}/generate_response.md", "w", encoding="utf-8") as f:
        f.write(resp.text)

    return {"answer": resp.text.replace("```markdown", " ").replace("```", "")}


# ============================================================================
# REPORT GENERATION - DILI, Patient, Legal with animated workflows
# ============================================================================

async def create_dili_diagnosis():
    """Generate DILI diagnosis and post to board"""
    print("🔬 Starting DILI Diagnosis generation...")
    
    try:
        # Load EHR data and generate diagnosis
        ehr_data = await load_ehr()
        result = await generate_dili_diagnosis()
        print("✅ DILI diagnosis generated successfully")
        
        # Post to board (sync function)
        board_response = canvas_ops.create_diagnosis(result)
        print(f"✅ DILI diagnosis posted to board")
        
        return {"generated": result, "board_response": board_response}
        
    except Exception as e:
        print(f"❌ DILI diagnosis error: {e}")
        return {"generated": None, "board_response": {"status": "error", "message": str(e)}}


async def generate_dili_diagnosis():
    """Generate DILI diagnosis JSON"""
    with open("system_prompts/dili_diagnosis_prompt.md", "r", encoding="utf-8") as f:
        SYSTEM_PROMPT = f.read()

    model = genai.GenerativeModel(MODEL, system_instruction=SYSTEM_PROMPT)
    ehr_data = await load_ehr()
    
    prompt = f"Generate DILI diagnosis based on patient data.\n\nPatient data: {ehr_data}"

    resp = model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.7,
        )
    )

    result = json.loads(resp.text)
    with open(f"{config.output_dir}/generate_dili_diagnosis.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=4)

    return result


async def create_patient_report():
    """Generate patient report and post to board"""
    print("📄 Starting Patient Report generation...")
    
    try:
        # Generate the report
        result = await generate_patient_report()
        print("✅ Patient report generated successfully")
        
        # Post to board
        board_response = await canvas_ops.create_report(result)
        print(f"✅ Patient report posted to board")
        
        return {"generated": result, "board_response": board_response}
        
    except Exception as e:
        print(f"❌ Patient report error: {e}")
        return {"generated": None, "board_response": {"status": "error", "message": str(e)}}


async def generate_patient_report():
    """Generate patient report JSON"""
    with open("system_prompts/patient_report_prompt.md", "r", encoding="utf-8") as f:
        SYSTEM_PROMPT = f.read()

    model = genai.GenerativeModel(MODEL, system_instruction=SYSTEM_PROMPT)
    ehr_data = await load_ehr()
    
    prompt = f"Generate patient report based on patient data.\n\nPatient data: {ehr_data}"

    resp = model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.7,
        )
    )

    result = json.loads(resp.text)
    with open(f"{config.output_dir}/generate_patient_report.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=4)

    return result


async def create_legal_doc():
    """Generate legal compliance report and post to board"""
    print("⚖️ Starting Legal Report generation...")
    
    try:
        # Generate the report
        result = await generate_legal_report()
        print("✅ Legal report generated successfully")
        
        # Post to board using dedicated legal-compliance endpoint
        board_response = await canvas_ops.create_legal(result)
        print(f"✅ Legal report posted to board")
        
        return {"generated": result, "board_response": board_response}
        
    except Exception as e:
        print(f"❌ Legal report error: {e}")
        return {"generated": None, "board_response": {"status": "error", "message": str(e)}}


async def generate_legal_report():
    """Generate legal compliance report JSON"""
    with open("system_prompts/legal_report_prompt.md", "r", encoding="utf-8") as f:
        SYSTEM_PROMPT = f.read()

    model = genai.GenerativeModel(MODEL, system_instruction=SYSTEM_PROMPT)
    ehr_data = await load_ehr()
    
    prompt = f"Generate a legal compliance report based on patient data.\n\nPatient data: {ehr_data}"

    resp = model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.7,
        )
    )

    result = json.loads(resp.text)
    with open(f"{config.output_dir}/generate_legal_report.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=4)

    return result


# ============================================================================
# NOTIFICATION & SCHEDULE - Board operations
# ============================================================================

async def send_notification(message: str, notification_type: str = "info"):
    """Send notification to board"""
    try:
        result = await canvas_ops.create_notification({
            "message": message,
            "type": notification_type
        })
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def create_schedule(context: str):
    """Create schedule panel on board"""
    try:
        result = await canvas_ops.create_schedule({
            "schedulingContext": context
        })
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ============================================================================
# EASL DIAGNOSIS (separate from DILI)
# ============================================================================

async def generate_easl_diagnosis(ehr_data=None):
    """Generate EASL-specific diagnosis assessment"""
    with open("system_prompts/easl_diagnose.md", "r", encoding="utf-8") as f:
        SYSTEM_PROMPT = f.read()

    if not ehr_data:
        ehr_data = await load_ehr()

    model = genai.GenerativeModel(MODEL, system_instruction=SYSTEM_PROMPT)
    
    prompt = f"Please generate EASL diagnosis assessment.\n\nPatient encounter data: {ehr_data}"

    resp = model.generate_content(prompt)
    
    with open(f"{config.output_dir}/generate_easl_diagnosis.md", "w", encoding="utf-8") as f:
        f.write(resp.text)

    try:
        result_json = json.loads(resp.text.replace("```json", "").replace("```", "").strip())
        with open(f"{config.output_dir}/generate_easl_diagnosis.json", "w", encoding="utf-8") as f:
            json.dump(result_json, f, indent=4)
        return result_json
    except:
        return {"answer": resp.text.replace("```markdown", " ").replace("```", "")}


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def start_background_agent_processing(action_data, todo_obj):
    """Start background processing in separate thread (for sync contexts)"""
    threading.Thread(
        target=lambda: asyncio.run(_handle_agent_processing(action_data, todo_obj)),
        daemon=True
    ).start()
    print("🔄 Background processing started")


async def _handle_agent_processing(action_data, todo_obj):
    """Handle agent processing in background"""
    try:
        response_result = await generate_response(action_data)
        
        patient_id = patient_manager.get_patient_id()
        url = BASE_URL + "/api/canvas-ops"
        payload = {
            "boardId": patient_id,
            "objectId": action_data.get('objectId'),
            "operation": "agent_answer",
            "agent_answer": response_result.get('answer')
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    print("✅ Agent answer sent successfully")
                else:
                    print(f"⚠️ Agent answer returned {response.status}")
                    
    except Exception as e:
        print(f"❌ Background processing error: {e}")


async def generate_task_obj(query):
    """Generate task object without creating on board"""
    with open("system_prompts/task_generator.md", "r", encoding="utf-8") as f:
        SYSTEM_PROMPT = f.read()

    ehr_data = await load_ehr()
    prompt = f"User request: {query}\n\nPatient data: {ehr_data}"

    model = genai.GenerativeModel(MODEL, system_instruction=SYSTEM_PROMPT)
    resp = model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.7,
        )
    )

    result = json.loads(resp.text)
    with open(f"{config.output_dir}/generate_task_obj.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=4)

    return result
