import warnings
from google.genai.types import GenerateContentConfig
# Suppress deprecation warning for google.generativeai (agent-2.9 legacy code)
warnings.filterwarnings('ignore', category=FutureWarning, module='google.generativeai')
import google.generativeai as genai
import time
import json
import asyncio
import os
import logging
import threading
from dotenv import load_dotenv
import side_agent
import canvas_ops
load_dotenv()

logger = logging.getLogger("chat-model")

# Lazy initialization - configure only when needed
_genai_configured = False
_cached_model = None

def _ensure_genai_configured():
    global _genai_configured
    if not _genai_configured:
        genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
        _genai_configured = True

def _get_model():
    """Get or create cached model instance for faster responses"""
    global _cached_model
    _ensure_genai_configured()
    if _cached_model is None:
        with open("system_prompts/chat_model_system.md", "r", encoding="utf-8") as f:
            system_prompt = f.read()
        _cached_model = genai.GenerativeModel(
            "gemini-2.0-flash",  # Use faster model
            system_instruction=system_prompt
        )
    return _cached_model

MODEL = "gemini-2.0-flash"  # Faster model

# Topic to board item ID mapping
TOPIC_FOCUS_MAP = {
    # Encounters
    "encounter": "encounter-track-1",
    "visit": "encounter-track-1",
    "consultation": "encounter-track-1",
    "appointment": "encounter-track-1",
    "history": "encounter-track-1",
    
    # Labs
    "lab": "dashboard-item-lab-table",
    "alt": "dashboard-item-lab-table",
    "ast": "dashboard-item-lab-table",
    "bilirubin": "dashboard-item-lab-table",
    "albumin": "dashboard-item-lab-table",
    "inr": "dashboard-item-lab-table",
    "creatinine": "dashboard-item-lab-table",
    "hemoglobin": "dashboard-item-lab-table",
    "platelet": "dashboard-item-lab-table",
    "sodium": "dashboard-item-lab-table",
    "lft": "dashboard-item-lab-table",
    "liver function": "dashboard-item-lab-table",
    "blood test": "dashboard-item-lab-table",
    
    # Lab chart
    "chart": "dashboard-item-lab-chart",
    "graph": "dashboard-item-lab-chart",
    "trend": "dashboard-item-lab-chart",
    
    # Medications
    "medication": "medication-track-1",
    "drug": "medication-track-1",
    "medicine": "medication-track-1",
    "prescription": "medication-track-1",
    "lactulose": "medication-track-1",
    "furosemide": "medication-track-1",
    "propranolol": "medication-track-1",
    "sertraline": "medication-track-1",
    
    # Diagnosis
    "diagnosis": "differential-diagnosis",
    "differential": "differential-diagnosis",
    "dili": "differential-diagnosis",
    "liver injury": "differential-diagnosis",
    
    # Risk
    "risk": "risk-track-1",
    "adverse": "adverse-event-analytics",
    "event": "risk-track-1",
    "safety": "risk-track-1",
    
    # Key events
    "timeline": "key-events-track-1",
    "key event": "key-events-track-1",
}


def detect_focus_topic(query: str) -> str:
    """Detect which board item to focus based on query keywords"""
    query_lower = query.lower()
    
    for keyword, object_id in TOPIC_FOCUS_MAP.items():
        if keyword in query_lower:
            return object_id
    
    return None


async def get_answer(query: str, conversation_text: str = '', context: str = ''):
    """Get answer from Gemini - uses cached model and pre-loaded context"""
    if not context:
        # Only fetch if not provided (should be provided by chat_agent)
        context_raw = canvas_ops.get_board_items(quiet=True)
        context = json.dumps(context_raw, indent=2)
    
    # Keep prompt concise for faster response
    prompt = f"""Answer the user query using the patient data from the board context.
Be helpful and informative. Use 1-3 sentences.

Query: {query}

Context (Board Data):
{context[:30000]}"""  # Increased context size to include sidebar data

    model = _get_model()
    response = model.generate_content(prompt)
    return response.text.strip()


async def chat_agent(chat_history: list[dict]) -> str:
    """
    Chat Agent - Optimized for speed.
    Takes chat history and returns agent response.
    """
    start_time = time.time()
    query = chat_history[-1].get('content')
    logger.info(f"⏱️ chat_agent: START - Query: {query[:50]}...")
    
    # Fast tool routing (keyword-based, no API call)
    tool_res = side_agent.parse_tool(query)
    logger.info(f"⏱️ chat_agent: parse_tool in {time.time()-start_time:.2f}s")
    print("Tools use:", tool_res)

    # Get context once (uses cache)
    t0 = time.time()
    context_raw = canvas_ops.get_board_items(quiet=False)  # Show logs for debugging
    context = json.dumps(context_raw, indent=2)
    logger.info(f"⏱️ chat_agent: get_board_items in {time.time()-t0:.2f}s (context: {len(context)} chars)")

    tool = tool_res.get('tool')
    
    if tool == "get_easl_answer":
        result = await side_agent.trigger_easl(query)
        return f"✅ EASL query completed. Result: {json.dumps(result, indent=2)}"
    
    elif tool == "generate_task":
        result = await side_agent.generate_task_workflow(query)
        return f"✅ Task workflow created successfully. {json.dumps(result, indent=2)}"
    
    elif tool == "navigate_canvas":
        try:
            object_id = await side_agent.resolve_object_id(query, context)
            if object_id:
                await canvas_ops.focus_item(object_id)
                # Return friendly message based on object_id
                friendly_names = {
                    "encounter-track-1": "encounters timeline",
                    "dashboard-item-lab-table": "lab results table",
                    "dashboard-item-lab-chart": "lab results chart",
                    "lab-track-1": "lab timeline",
                    "medication-track-1": "medication timeline",
                    "differential-diagnosis": "differential diagnosis",
                    "adverse-event-analytics": "adverse events analytics",
                    "risk-track-1": "risk events timeline",
                    "key-events-track-1": "key events timeline",
                    "sidebar-1": "patient sidebar",
                }
                # Safely get friendly name
                object_id_str = str(object_id) if not isinstance(object_id, str) else object_id
                friendly_name = friendly_names.get(object_id_str, "the requested section")
                return f"✅ Focused on {friendly_name}"
            return "❌ Could not identify the section to focus on"
        except Exception as e:
            return f"❌ Navigation failed: {str(e)}"
    
    elif tool == "create_schedule":
        result = await side_agent.create_schedule(query, context)
        return f"✅ Schedule created: {result.get('message', result.get('status', 'Success'))}"
    
    elif tool == "send_notification":
        result = await canvas_ops.create_notification({"message": query})
        return f"✅ Notification sent: {result.get('message', 'Success')}"
    
    elif tool == "create_lab_results":
        # Parse lab values from query using AI
        lab_data = await side_agent.parse_lab_values(query, context)
        if lab_data:
            result = await canvas_ops.create_lab(lab_data)
            return f"✅ Lab results posted to board: {result.get('id', 'Success')}"
        return "❌ Could not parse lab values from the query. Please provide values like 'ALT 110, AST 150'"
    
    elif tool == "generate_diagnosis":
        result = await side_agent.create_dili_diagnosis()
        return f"✅ DILI diagnosis generated"
    
    elif tool == "generate_patient_report":
        result = await side_agent.create_patient_report()
        return f"✅ Patient report generated"
    
    elif tool == "generate_legal_report":
        result = await side_agent.create_legal_doc()
        return f"✅ Legal report generated"
    
    else:
        # General Q&A - pass context directly (no redundant fetch)
        conversation_text = ""
        if len(chat_history) > 1:
            conversation_text = "\n".join([
                f"{msg.get('role')}: {msg.get('content')}" 
                for msg in chat_history[:-1]
            ])
        
        # Get the answer first
        answer = await get_answer(query, conversation_text, context)
        
        # Auto-focus on relevant section based on query topic
        focus_object_id = detect_focus_topic(query)
        if focus_object_id:
            try:
                await canvas_ops.focus_item(focus_object_id)
                logger.info(f"🎯 Auto-focused on: {focus_object_id}")
            except Exception as e:
                logger.warning(f"⚠️ Auto-focus failed: {e}")
        
        return answer
