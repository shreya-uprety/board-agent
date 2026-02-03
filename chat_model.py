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


async def get_answer(query: str, conversation_text: str = '', context: str = ''):
    """Get answer from Gemini - uses cached model and pre-loaded context"""
    if not context:
        # Only fetch if not provided (should be provided by chat_agent)
        context_raw = canvas_ops.get_board_items(quiet=True)
        context = json.dumps(context_raw, indent=2)
    
    # Keep prompt concise for faster response
    prompt = f"""Answer briefly (1-3 sentences). Be direct.

Query: {query}

Context:
{context[:15000]}"""  # Limit context size for speed

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
                result = await canvas_ops.focus_item(object_id)
                return f"✅ Navigated to {result}"
            return "❌ Could not identify the object to navigate to"
        except Exception as e:
            return f"❌ Navigation failed: {str(e)}"
    
    elif tool == "create_schedule":
        result = await canvas_ops.create_schedule({"schedulingContext": query})
        return f"✅ Schedule created: {result.get('message', 'Success')}"
    
    elif tool == "send_notification":
        result = await canvas_ops.create_notification({"message": query})
        return f"✅ Notification sent: {result.get('message', 'Success')}"
    
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
        return await get_answer(query, conversation_text, context)
