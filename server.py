"""
Board Agents Server - Streamlined version for canvas operations
Supports chat and voice agents that perform board operations like focus, generate reports, create TODOs, etc.
"""

import sys
import asyncio

# CRITICAL FIX for Windows: Must be applied BEFORE any google.genai imports
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# CRITICAL FIX: Monkey patch websockets to increase open_timeout
from contextlib import asynccontextmanager as _asynccontextmanager
from websockets.asyncio.client import connect as _original_ws_connect

@_asynccontextmanager
async def _patched_ws_connect(*args, **kwargs):
    """Patched version that adds longer timeout for Gemini Live API"""
    if 'open_timeout' not in kwargs:
        kwargs['open_timeout'] = 120  # 2 minutes instead of default 10 seconds
    async with _original_ws_connect(*args, **kwargs) as ws:
        yield ws

# Pre-import and patch google.genai.live before any other imports use it
import google.genai.live
google.genai.live.ws_connect = _patched_ws_connect

import uvicorn
import logging
import time
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import json
import os
import traceback

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("board-agents-server")

# Track startup time
_startup_time = time.time()
logger.info("🚀 Server initialization started...")

# Import core board agent modules
logger.info("⏱️ Importing board agent modules...")
_import_start = time.time()
try:
    import chat_model
    import side_agent
    import canvas_ops
    from patient_manager import patient_manager
    logger.info(f"✅ Board agent modules imported successfully ({time.time() - _import_start:.2f}s)")
except Exception as e:
    logger.error(f"❌ Failed to import board agent modules: {e}")
    chat_model = None
    side_agent = None
    canvas_ops = None
    patient_manager = None

logger.info("⏱️ Importing websocket_agent...")
_import_start = time.time()
try:
    from websocket_agent import websocket_chat_endpoint, get_websocket_agent
    logger.info(f"✅ websocket_agent imported successfully ({time.time() - _import_start:.2f}s)")
except Exception as e:
    logger.error(f"❌ Failed to import websocket_agent: {e}")
    websocket_chat_endpoint = None
    get_websocket_agent = None

logger.info("⏱️ Importing VoiceWebSocketHandler...")
_import_start = time.time()
try:
    from voice_websocket_handler import VoiceWebSocketHandler
    logger.info(f"✅ VoiceWebSocketHandler imported successfully ({time.time() - _import_start:.2f}s)")
except Exception as e:
    logger.error(f"❌ Failed to import VoiceWebSocketHandler: {e}")
    VoiceWebSocketHandler = None

# Import voice session manager for background connections
try:
    from voice_session_manager import voice_session_manager, SessionStatus
    logger.info("✅ Voice Session Manager imported")
except ImportError as e:
    voice_session_manager = None
    SessionStatus = None
    logger.warning(f"⚠️ Voice Session Manager not available: {e}")

logger.info(f"📦 All imports completed in {time.time() - _startup_time:.2f}s total")

# Initialize FastAPI app
app = FastAPI(title="Board Agents Server - Chat & Voice for Canvas Operations")

# Add CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Startup event
@app.on_event("startup")
async def startup_event():
    """Log startup information and pre-warm models"""
    port = os.environ.get("PORT", "8080")
    logger.info("=" * 60)
    logger.info("🚀 Board Agents Server Starting")
    logger.info(f"📍 Listening on port: {port}")
    logger.info(f"💬 Chat Agent: {'Ready' if chat_model else 'Not Available'}")
    logger.info(f"🎙️ Voice Agent: {'Ready' if VoiceWebSocketHandler else 'Not Available'}")
    logger.info(f"📋 Canvas Operations: {'Ready' if canvas_ops else 'Not Available'}")
    logger.info("=" * 60)
    
    # Start voice session cleanup task
    if voice_session_manager:
        voice_session_manager.start_cleanup_task()
    
    # Pre-warm models to avoid cold start delay on first request
    logger.info("🔥 Pre-warming Gemini models...")
    try:
        # Pre-warm chat_model
        if chat_model:
            await asyncio.get_event_loop().run_in_executor(
                None, chat_model._get_model
            )
            logger.info("  ✅ Chat model warmed up")
        
        # Pre-warm side_agent model
        if side_agent:
            side_agent._get_model("prompt_tool_call.txt")
            logger.info("  ✅ Side agent model warmed up")
        
        logger.info("🔥 Model pre-warming complete!")
    except Exception as e:
        logger.warning(f"⚠️ Model pre-warming failed (will warm on first request): {e}")


# --- Pydantic Models ---
class PatientSwitchRequest(BaseModel):
    patient_id: str


# --- Basic Endpoints ---

@app.get("/")
async def root():
    return {
        "status": "Board Agents Server is Running",
        "features": ["chat", "voice", "canvas_operations"],
        "endpoints": {
            "chat": "/send-chat",
            "voice_ws": "/ws/voice/{patient_id}",
            "chat_ws": "/ws/chat/{patient_id}",
            "canvas_focus": "/api/canvas/focus",
            "canvas_todo": "/api/canvas/create-todo",
            "generate_diagnosis": "/generate_diagnosis",
            "generate_report": "/generate_report"
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "board-agents",
        "port": os.environ.get("PORT", 8080)
    }


# --- Patient Management ---

@app.get("/patient/current")
async def get_current_patient():
    """Get current patient ID"""
    if patient_manager:
        return {"patient_id": patient_manager.get_patient_id()}
    return {"patient_id": "p0001"}


@app.post("/patient/switch")
async def switch_patient(payload: PatientSwitchRequest):
    """Switch current patient"""
    if patient_manager and payload.patient_id:
        patient_manager.set_patient_id(payload.patient_id)
        return {"status": "success", "patient_id": patient_manager.get_patient_id()}
    raise HTTPException(status_code=400, detail="Missing patient_id")


# --- Chat Endpoints ---

@app.post("/send-chat")
async def run_chat_agent(payload: list[dict]):
    """
    Chat endpoint using board agent architecture.
    Accepts chat history and returns agent response.
    """
    import time
    request_start = time.time()
    logger.info(f"⏱️ /send-chat: REQUEST RECEIVED at {request_start}")
    try:
        if patient_manager:
            # Extract patient_id if provided in first message metadata
            if len(payload) > 0 and isinstance(payload[0], dict):
                patient_id = payload[0].get('patient_id', patient_manager.get_patient_id())
                patient_manager.set_patient_id(patient_id)
        
        logger.info(f"⏱️ /send-chat: Calling chat_agent...")
        answer = await chat_model.chat_agent(payload)
        logger.info(f"⏱️ /send-chat: chat_agent returned in {time.time()-request_start:.2f}s")
        logger.info(f"Agent Answer: {answer[:200]}...")
        return {"response": answer, "status": "success"}
        
    except Exception as e:
        logger.error(f"Chat agent error: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


# --- Report Generation Endpoints ---

@app.post("/generate_diagnosis")
async def gen_diagnosis(payload: dict):
    """Generate DILI diagnosis"""
    try:
        if patient_manager and payload.get('patient_id'):
            patient_manager.set_patient_id(payload['patient_id'])
        
        result = await side_agent.create_dili_diagnosis()
        return {"status": "done", "data": result}
    except Exception as e:
        logger.error(f"Error generating diagnosis: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate_report")
async def gen_report(payload: dict):
    """Generate patient report"""
    try:
        if patient_manager and payload.get('patient_id'):
            patient_manager.set_patient_id(payload['patient_id'])
        
        result = await side_agent.create_patient_report()
        return {"status": "done", "data": result}
    except Exception as e:
        logger.error(f"Error generating report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate_legal")
async def gen_legal(payload: dict):
    """Generate legal report"""
    try:
        if patient_manager and payload.get('patient_id'):
            patient_manager.set_patient_id(payload['patient_id'])
        
        result = await side_agent.create_legal_doc()
        return {"status": "done", "data": result}
    except Exception as e:
        logger.error(f"Error generating legal report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# CANVAS TOOL OPERATIONS
# ============================================

@app.post("/api/canvas/focus")
async def canvas_focus(payload: dict):
    """Focus on a board item"""
    try:
        if patient_manager and payload.get('patient_id'):
            patient_manager.set_patient_id(payload['patient_id'])
        
        object_id = payload.get('object_id') or payload.get('objectId')
        if not object_id and payload.get('query'):
            # Resolve object_id from query
            context = json.dumps(canvas_ops.get_board_items())
            object_id = await side_agent.resolve_object_id(payload['query'], context)
        
        if object_id:
            result = await canvas_ops.focus_item(object_id)
            return {"status": "success", "object_id": object_id, "data": result}
        return {"status": "error", "message": "Could not resolve object_id"}
    except Exception as e:
        logger.error(f"Error focusing board item: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/canvas/create-todo")
async def canvas_create_todo(payload: dict):
    """Create a TODO task on the board"""
    try:
        if patient_manager and payload.get('patient_id'):
            patient_manager.set_patient_id(payload['patient_id'])
        
        query = payload.get('query') or payload.get('description')
        if query:
            result = await side_agent.generate_todo(query)
            return {"status": "success", "data": result}
        return {"status": "error", "message": "Query/description required"}
    except Exception as e:
        logger.error(f"Error creating TODO: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/canvas/send-to-easl")
async def canvas_send_to_easl(payload: dict):
    """Send a clinical question to EASL"""
    try:
        if patient_manager and payload.get('patient_id'):
            patient_manager.set_patient_id(payload['patient_id'])
        
        question = payload.get('question') or payload.get('query')
        if question:
            result = await side_agent.trigger_easl(question)
            return {"status": "success", "data": result}
        return {"status": "error", "message": "Question required"}
    except Exception as e:
        logger.error(f"Error sending to EASL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/canvas/prepare-easl-query")
async def canvas_prepare_easl_query(payload: dict):
    """Prepare an EASL query by generating context and refined question."""
    try:
        if patient_manager and payload.get('patient_id'):
            patient_manager.set_patient_id(payload['patient_id'])
        
        question = payload.get('question') or payload.get('query')
        if not question:
            return {"status": "error", "message": "Question required"}
        
        result = await side_agent.prepare_easl_query(question)
        return {"status": "success", "data": result}
    except Exception as e:
        logger.error(f"Error preparing EASL query: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/canvas/create-schedule")
async def canvas_create_schedule(payload: dict):
    """Create a schedule on the board"""
    try:
        if patient_manager and payload.get('patient_id'):
            patient_manager.set_patient_id(payload['patient_id'])
        
        result = await canvas_ops.create_schedule(payload)
        return {"status": "success", "data": result}
    except Exception as e:
        logger.error(f"Error creating schedule: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/canvas/send-notification")
async def canvas_send_notification(payload: dict):
    """Send a notification"""
    try:
        if patient_manager and payload.get('patient_id'):
            patient_manager.set_patient_id(payload['patient_id'])
        
        result = await canvas_ops.create_notification(payload)
        return {"status": "success", "data": result}
    except Exception as e:
        logger.error(f"Error sending notification: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/canvas/create-lab-results")
async def canvas_create_lab_results(payload: dict):
    """Create lab results on the board"""
    try:
        if patient_manager and payload.get('patient_id'):
            patient_manager.set_patient_id(payload['patient_id'])
        
        # Transform lab results to board API format
        raw_labs = payload.get('labResults', [])
        transformed_labs = []
        for lab in raw_labs:
            transformed_labs.append({
                "parameter": lab.get('name') or lab.get('parameter'),
                "value": lab.get('value'),
                "unit": lab.get('unit', ''),
                "status": lab.get('status', 'normal'),
                "range": lab.get('range') or lab.get('normalRange', '')
            })
        
        lab_payload = {
            "labResults": transformed_labs,
            "date": payload.get('date', datetime.now().strftime('%Y-%m-%d')),
            "source": payload.get('source', 'Agent Generated')
        }
        
        result = await canvas_ops.create_lab(lab_payload)
        return {"status": "success", "data": result}
    except Exception as e:
        logger.error(f"Error creating lab results: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/canvas/create-agent-result")
async def canvas_create_agent_result(payload: dict):
    """Create an agent analysis result on the board"""
    try:
        if patient_manager and payload.get('patient_id'):
            patient_manager.set_patient_id(payload['patient_id'])
        
        agent_payload = {
            "title": payload.get('title', 'Agent Analysis Result'),
            "content": payload.get('content') or payload.get('markdown', ''),
            "agentName": payload.get('agentName', 'Clinical Agent'),
            "timestamp": datetime.now().isoformat()
        }
        
        result = await canvas_ops.create_result(agent_payload)
        return {"status": "success", "data": result}
    except Exception as e:
        logger.error(f"Error creating agent result: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/canvas/board-items/{patient_id}")
async def get_board_items_api(patient_id: str):
    """Get all board items for a patient"""
    try:
        if patient_manager:
            patient_manager.set_patient_id(patient_id, quiet=True)
        
        items = canvas_ops.get_board_items(quiet=True)
        return {"status": "success", "patient_id": patient_id, "items": items, "count": len(items)}
    except Exception as e:
        logger.error(f"Error getting board items: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# WEBSOCKET ENDPOINTS
# ============================================

@app.websocket("/ws/chat/{patient_id}")
async def websocket_chat(websocket: WebSocket, patient_id: str):
    """
    WebSocket endpoint for real-time general chat with RAG + tools.
    """
    if websocket_chat_endpoint is None:
        await websocket.close(code=1011, reason="Service unavailable")
        return
    await websocket_chat_endpoint(websocket, patient_id)


@app.websocket("/ws/voice/{patient_id}")
async def websocket_voice(websocket: WebSocket, patient_id: str):
    """
    WebSocket endpoint for real-time voice communication using Gemini Live API.
    """
    if VoiceWebSocketHandler is None:
        await websocket.close(code=1011, reason="Voice service unavailable")
        return
    
    await websocket.accept()
    logger.info(f"🎙️ Voice WebSocket connected for patient: {patient_id}")
    
    try:
        handler = VoiceWebSocketHandler(websocket, patient_id)
        await handler.run()
    except Exception as e:
        logger.error(f"Voice WebSocket error: {e}")
        try:
            await websocket.close()
        except:
            pass


# ========== TWO-PHASE VOICE CONNECTION ==========

@app.post("/api/voice/start/{patient_id}")
async def start_voice_session(patient_id: str):
    """
    Phase 1: Start connecting to Gemini Live API in background.
    Returns immediately with session_id.
    """
    logger.info(f"🎙️ Voice start request received for patient: {patient_id}")
    
    if voice_session_manager is None:
        logger.error("❌ Voice session manager is None!")
        raise HTTPException(status_code=503, detail="Voice session manager not available")
    
    session_id = await voice_session_manager.create_session(patient_id)
    return {
        "session_id": session_id,
        "patient_id": patient_id,
        "status": "connecting",
        "poll_url": f"/api/voice/status/{session_id}",
        "websocket_url": f"/ws/voice-session/{session_id}",
        "message": "Connection started. Poll status endpoint until ready, then connect to WebSocket."
    }


@app.get("/api/voice/status/{session_id}")
async def get_voice_session_status(session_id: str):
    """
    Phase 2: Check if voice session is ready.
    """
    if voice_session_manager is None:
        raise HTTPException(status_code=503, detail="Voice session manager not available")
    
    status = voice_session_manager.get_status(session_id)
    
    if status["status"] == "not_found":
        raise HTTPException(status_code=404, detail="Session not found")
    
    return status


@app.delete("/api/voice/session/{session_id}")
async def close_voice_session(session_id: str):
    """Close a voice session and free resources."""
    if voice_session_manager is None:
        raise HTTPException(status_code=503, detail="Voice session manager not available")
    
    await voice_session_manager.close_session(session_id)
    return {"status": "closed", "session_id": session_id}


@app.websocket("/ws/voice-session/{session_id}")
async def websocket_voice_session(websocket: WebSocket, session_id: str):
    """
    Phase 3: WebSocket endpoint for pre-connected voice session.
    """
    if voice_session_manager is None:
        await websocket.close(code=1011, reason="Voice session manager not available")
        return
    
    session = await voice_session_manager.get_session(session_id)
    
    if session is None:
        await websocket.close(code=4004, reason="Session not ready or not found")
        return
    
    await websocket.accept()
    logger.info(f"🎙️ Voice WebSocket connected for pre-established session: {session_id}")
    
    try:
        if VoiceWebSocketHandler is not None:
            handler = VoiceWebSocketHandler(websocket, session.patient_id)
            handler.session = session.gemini_session
            handler.audio_in_queue = session.audio_in_queue
            handler.out_queue = session.out_queue
            handler.client = session.client
            
            await handler.run_with_session()
        else:
            await websocket.send_json({"type": "error", "message": "Voice handler not available"})
    except Exception as e:
        logger.error(f"Voice WebSocket error: {e}")
    finally:
        await voice_session_manager.release_session(session_id)
        try:
            await websocket.close()
        except:
            pass


# --- Test Endpoint ---

@app.get("/test-gemini-live")
async def test_gemini_live():
    """Quick test endpoint to check Gemini Live API connection speed"""
    import time
    from google import genai
    
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return {"error": "No API key"}
    
    client = genai.Client(api_key=api_key)
    model = "models/gemini-2.5-flash-native-audio-preview-12-2025"
    
    config = {
        "response_modalities": ["AUDIO"],
        "speech_config": {"voice_config": {"prebuilt_voice_config": {"voice_name": "Aoede"}}}
    }
    
    start = time.time()
    try:
        async with client.aio.live.connect(model=model, config=config) as session:
            connect_time = time.time() - start
            return {"status": "connected", "connect_time_seconds": round(connect_time, 2)}
    except Exception as e:
        return {"error": str(e), "elapsed": time.time() - start}


# --- WebSocket Sessions Info ---

@app.get("/ws/sessions")
async def get_active_websocket_sessions():
    """Get information about all active WebSocket sessions."""
    if get_websocket_agent is None:
        return {"error": "WebSocket agent not available", "sessions": []}
    
    agent = get_websocket_agent()
    if agent is None:
        return {"error": "WebSocket agent not available", "sessions": []}
    
    try:
        sessions = agent.get_active_sessions()
        return {
            "active_sessions": len(sessions),
            "sessions": sessions
        }
    except Exception as e:
        logger.error(f"Error getting session info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- UI Endpoint ---

@app.get("/ui/{file_path:path}")
async def serve_ui(file_path: str):
    """Serve UI files for testing"""
    try:
        ui_file = os.path.join("ui", file_path)
        if os.path.exists(ui_file):
            with open(ui_file, "r", encoding="utf-8") as f:
                content = f.read()
            return HTMLResponse(content=content)
        raise HTTPException(status_code=404, detail="File not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Run Block ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))

    import platform
    if platform.system() == "Windows":
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="info", loop="asyncio")
    else:
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
